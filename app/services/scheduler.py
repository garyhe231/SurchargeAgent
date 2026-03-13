"""
APScheduler — automated data collection and analysis pipeline.
Runs surcharge collection + bunker rates + risk computation every 4 hours.
"""
import logging
import os
from datetime import datetime, timezone

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

logger = logging.getLogger(__name__)
_scheduler: BackgroundScheduler = None


def run_collection_pipeline():
    """Full data collection and analysis pipeline."""
    logger.info("Starting surcharge collection pipeline...")
    try:
        from app.services.surcharge_collector import collect_all_surcharges, save_surcharges
        from app.services.bunker_collector import collect_bunker_rates, save_bunker_rates
        from app.services.risk_engine import (
            compute_all_lane_risks,
            compute_carrier_exposure,
            compute_bunker_volatility,
            save_risk_report,
        )
        from app.services.bunker_collector import build_bunker_timeseries

        # Step 1: Collect surcharge notices
        notices = collect_all_surcharges()
        save_surcharges(notices)
        logger.info("Step 1: Collected %d surcharge notices", len(notices))

        # Step 2: Collect bunker rates
        rates = collect_bunker_rates()
        save_bunker_rates(rates)
        logger.info("Step 2: Collected %d bunker rate records", len(rates))

        # Step 3: Compute risks
        sg_vlsfo_history = build_bunker_timeseries("VLSFO", "Singapore")
        lane_risks = compute_all_lane_risks(notices, sg_vlsfo_history)
        carrier_exposure = compute_carrier_exposure(notices)

        volatility = compute_bunker_volatility(sg_vlsfo_history)
        report = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "lane_risks": lane_risks,
            "carrier_exposure": carrier_exposure,
            "bunker_volatility": volatility,
            "notice_count": len(notices),
            "rate_count": len(rates),
        }
        save_risk_report(report)
        logger.info("Step 3: Risk report saved")

        # Step 4: Generate AI brief
        from app.services.ai_analyst import generate_executive_brief
        from app.config import DATA_DIR
        import json

        brief_html = generate_executive_brief(notices, rates, lane_risks, carrier_exposure)
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        brief_path = os.path.join(DATA_DIR, f"brief_{date_str}.json")
        with open(brief_path, "w") as f:
            json.dump({
                "date": date_str,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "html": brief_html,
            }, f)
        logger.info("Step 4: AI brief saved")

    except Exception as exc:
        logger.error("Pipeline error: %s", exc, exc_info=True)


def start_scheduler():
    """Start the background scheduler."""
    global _scheduler
    _scheduler = BackgroundScheduler(timezone="UTC")

    # Run at startup after 5 seconds
    from apscheduler.triggers.date import DateTrigger
    from datetime import timedelta
    _scheduler.add_job(
        run_collection_pipeline,
        trigger=DateTrigger(run_date=datetime.now(timezone.utc) + timedelta(seconds=5)),
        id="initial_run",
        name="Initial data collection",
    )

    # Then every 4 hours
    _scheduler.add_job(
        run_collection_pipeline,
        trigger=IntervalTrigger(hours=4),
        id="periodic_collection",
        name="Periodic surcharge collection",
        replace_existing=True,
    )

    _scheduler.start()
    logger.info("Scheduler started — pipeline runs every 4 hours")


def stop_scheduler():
    """Stop the background scheduler."""
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")


def trigger_now():
    """Manually trigger the collection pipeline."""
    import threading
    t = threading.Thread(target=run_collection_pipeline, daemon=True)
    t.start()
    return True
