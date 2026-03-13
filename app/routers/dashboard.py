"""
Dashboard router — serves the main dashboard and all API endpoints.
"""
import json
import logging
import os
from datetime import datetime, timezone
from typing import Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from app.config import (
    DATA_DIR,
    RISK_ZONES,
    SURCHARGE_TYPES,
    TRADE_LANES,
    TRACKED_CARRIERS,
)

logger = logging.getLogger(__name__)
router = APIRouter()

BASE_DIR = os.path.dirname(os.path.dirname(__file__))
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))


# ── helpers ──────────────────────────────────────────────────────────────────

def _load_latest_data():
    """Load the most recent available data files."""
    from app.services.surcharge_collector import load_surcharges, list_available_dates
    from app.services.bunker_collector import load_bunker_rates, build_bunker_timeseries
    from app.services.risk_engine import load_risk_report

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    available = list_available_dates()
    date_str = available[0] if available else today

    notices = load_surcharges(date_str)
    bunker_rates = load_bunker_rates(date_str)
    risk_report = load_risk_report(date_str)
    vlsfo_series = build_bunker_timeseries("VLSFO", "Singapore")
    mgo_series = build_bunker_timeseries("MGO", "Singapore")
    ifo_series = build_bunker_timeseries("IFO380", "Singapore")

    return {
        "date_str": date_str,
        "notices": notices,
        "bunker_rates": bunker_rates,
        "risk_report": risk_report,
        "vlsfo_series": vlsfo_series,
        "mgo_series": mgo_series,
        "ifo_series": ifo_series,
    }


def _load_brief(date_str: Optional[str] = None) -> Optional[Dict]:
    if not date_str:
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    path = os.path.join(DATA_DIR, f"brief_{date_str}.json")
    if not os.path.exists(path):
        # Try latest available
        if os.path.exists(DATA_DIR):
            files = sorted(
                [f for f in os.listdir(DATA_DIR) if f.startswith("brief_")],
                reverse=True,
            )
            if files:
                path = os.path.join(DATA_DIR, files[0])
            else:
                return None
        else:
            return None
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return None


# ── page routes ──────────────────────────────────────────────────────────────

@router.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@router.get("/lane/{lane_name}", response_class=HTMLResponse)
def lane_detail(request: Request, lane_name: str):
    return templates.TemplateResponse(
        "lane_detail.html", {"request": request, "lane": lane_name}
    )


# ── API: dashboard summary ────────────────────────────────────────────────────

@router.get("/api/dashboard")
def api_dashboard():
    """Full dashboard data payload."""
    data = _load_latest_data()
    notices = data["notices"]
    bunker_rates = data["bunker_rates"]
    risk_report = data["risk_report"] or {}

    lane_risks = risk_report.get("lane_risks", [])
    carrier_exposure = risk_report.get("carrier_exposure", [])

    # Surcharge type distribution
    type_counts: Dict[str, int] = {}
    for notice in notices:
        for st in notice.get("surcharge_types", []):
            type_counts[st] = type_counts.get(st, 0) + 1

    # Lane distribution of notices
    lane_counts: Dict[str, int] = {}
    for notice in notices:
        for lane in notice.get("trade_lanes", []):
            lane_counts[lane] = lane_counts.get(lane, 0) + 1

    # Hub bunker summary
    bunker_summary: Dict[str, Dict] = {}
    for r in bunker_rates:
        hub = r.get("hub", "")
        grade = r.get("grade", "")
        if hub not in bunker_summary:
            bunker_summary[hub] = {}
        bunker_summary[hub][grade] = r.get("price_usd_mt")

    # Critical notices (WRS, RSA, SCS, EBS, ECS)
    critical_types = {"WRS", "RSA", "SCS", "ECS", "EBS"}
    critical_notices = [
        n for n in notices
        if any(st in critical_types for st in n.get("surcharge_types", []))
    ]

    return {
        "as_of": data["date_str"],
        "total_notices": len(notices),
        "critical_alerts": len(critical_notices),
        "carriers_active": len(set(n["carrier"] for n in notices if n.get("carrier"))),
        "lane_risks": lane_risks,
        "carrier_exposure": carrier_exposure,
        "type_distribution": type_counts,
        "lane_distribution": lane_counts,
        "bunker_summary": bunker_summary,
        "bunker_volatility": risk_report.get("bunker_volatility", 0),
        "vlsfo_series": data["vlsfo_series"],
        "mgo_series": data["mgo_series"],
        "ifo_series": data["ifo_series"],
        "recent_notices": notices[:20],
        "critical_notices": critical_notices[:10],
        "surcharge_type_labels": SURCHARGE_TYPES,
        "risk_zones": RISK_ZONES,
    }


# ── API: surcharge notices ────────────────────────────────────────────────────

@router.get("/api/notices")
def api_notices(
    carrier: Optional[str] = None,
    surcharge_type: Optional[str] = None,
    lane: Optional[str] = None,
    limit: int = Query(50, le=200),
):
    """Filtered surcharge notice list."""
    from app.services.surcharge_collector import load_surcharges
    from app.services.surcharge_collector import list_available_dates
    available = list_available_dates()
    date_str = available[0] if available else datetime.now(timezone.utc).strftime("%Y-%m-%d")
    notices = load_surcharges(date_str)

    if carrier:
        notices = [n for n in notices if (n.get("carrier") or "").lower() == carrier.lower()]
    if surcharge_type:
        notices = [n for n in notices if surcharge_type.upper() in n.get("surcharge_types", [])]
    if lane:
        notices = [n for n in notices if lane in n.get("trade_lanes", [])]

    return {
        "total": len(notices),
        "notices": notices[:limit],
        "carriers": TRACKED_CARRIERS,
        "surcharge_types": SURCHARGE_TYPES,
        "trade_lanes": TRADE_LANES,
    }


# ── API: bunker rates ─────────────────────────────────────────────────────────

@router.get("/api/bunker")
def api_bunker(hub: Optional[str] = None, grade: Optional[str] = None):
    """Bunker rates with optional filtering."""
    from app.services.bunker_collector import load_bunker_rates
    from app.services.surcharge_collector import list_available_dates
    available = list_available_dates()
    date_str = available[0] if available else datetime.now(timezone.utc).strftime("%Y-%m-%d")
    rates = load_bunker_rates(date_str)

    if hub:
        rates = [r for r in rates if r.get("hub", "").lower() == hub.lower()]
    if grade:
        rates = [r for r in rates if r.get("grade", "").upper() == grade.upper()]

    return {"rates": rates, "as_of": date_str}


@router.get("/api/bunker/timeseries")
def api_bunker_timeseries(
    grade: str = Query("VLSFO"),
    hub: str = Query("Singapore"),
):
    """Bunker price time series for charting."""
    from app.services.bunker_collector import build_bunker_timeseries
    series = build_bunker_timeseries(grade, hub)
    return {"grade": grade, "hub": hub, "series": series}


# ── API: risk scores ──────────────────────────────────────────────────────────

@router.get("/api/risk")
def api_risk():
    """Trade lane risk scores."""
    from app.services.risk_engine import load_risk_report
    from app.services.surcharge_collector import list_available_dates
    available = list_available_dates()
    date_str = available[0] if available else datetime.now(timezone.utc).strftime("%Y-%m-%d")
    report = load_risk_report(date_str)
    if not report:
        return {"lane_risks": [], "carrier_exposure": [], "as_of": date_str}
    return {**report, "risk_zones": RISK_ZONES}


@router.get("/api/risk/lane/{lane_name}")
def api_lane_risk(lane_name: str, deep_dive: bool = False):
    """Risk data for a specific lane, with optional AI deep dive."""
    from app.services.risk_engine import load_risk_report
    from app.services.surcharge_collector import load_surcharges, list_available_dates
    from app.services.bunker_collector import load_bunker_rates

    available = list_available_dates()
    date_str = available[0] if available else datetime.now(timezone.utc).strftime("%Y-%m-%d")
    report = load_risk_report(date_str)
    if not report:
        raise HTTPException(status_code=404, detail="No risk data available")

    lane_risk = next(
        (r for r in report.get("lane_risks", []) if r["lane"] == lane_name),
        None,
    )
    if not lane_risk:
        raise HTTPException(status_code=404, detail=f"Lane '{lane_name}' not found")

    result = {"lane_risk": lane_risk}

    if deep_dive:
        from app.services.ai_analyst import generate_lane_deep_dive
        notices = load_surcharges(date_str)
        rates = load_bunker_rates(date_str)
        result["deep_dive_html"] = generate_lane_deep_dive(
            lane_name, notices, rates, lane_risk
        )

    return result


# ── API: AI brief ─────────────────────────────────────────────────────────────

@router.get("/api/brief")
def api_brief():
    """Return cached AI executive brief HTML."""
    brief = _load_brief()
    if not brief:
        return {"html": "<p>No brief available. Click 'Refresh Data' to generate one.</p>", "generated_at": None}
    return brief


# ── API: Q&A ──────────────────────────────────────────────────────────────────

class QuestionRequest(BaseModel):
    question: str


@router.post("/api/ask")
def api_ask(req: QuestionRequest):
    """Ask an ad-hoc question about the surcharge landscape."""
    from app.services.ai_analyst import answer_surcharge_question
    from app.services.surcharge_collector import load_surcharges, list_available_dates
    from app.services.bunker_collector import load_bunker_rates
    from app.services.risk_engine import load_risk_report

    available = list_available_dates()
    date_str = available[0] if available else datetime.now(timezone.utc).strftime("%Y-%m-%d")
    notices = load_surcharges(date_str)
    rates = load_bunker_rates(date_str)
    report = load_risk_report(date_str) or {}
    lane_risks = report.get("lane_risks", [])

    answer = answer_surcharge_question(req.question, notices, rates, lane_risks)
    return {"answer": answer, "question": req.question}


# ── API: manual refresh ───────────────────────────────────────────────────────

@router.post("/api/refresh")
def api_refresh():
    """Manually trigger data collection pipeline."""
    from app.services.scheduler import trigger_now
    trigger_now()
    return {"status": "pipeline_triggered", "message": "Data collection started in background"}
