"""
Risk engine — computes geopolitical and fuel/port-congestion risk scores
for each trade lane based on:
  - Active surcharge count and types
  - Bunker price volatility
  - Known geopolitical risk zones
  - Port congestion indicators
"""
import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from app.config import DATA_DIR, RISK_ZONES, SURCHARGE_TYPES, TRADE_LANES

logger = logging.getLogger(__name__)


# Risk weights by surcharge type
SURCHARGE_RISK_WEIGHTS = {
    "WRS": 25,   # War Risk — highest
    "RSA": 22,   # Red Sea Avoidance
    "SCS": 20,   # Suez Canal
    "PCS": 18,   # Panama Canal
    "PSC": 15,   # Port Congestion
    "EBS": 12,   # Emergency Bunker
    "BAF": 10,   # Bunker Adj Factor
    "LSS": 10,   # Low Sulphur
    "ECS": 10,   # Emergency Cost
    "GRI": 8,    # General Rate Increase
    "PSS": 6,    # Peak Season
    "CAF": 5,    # Currency Adj
    "THC": 3,
    "AMS": 2,
    "ISF": 2,
    "OWS": 2,
}

# Geopolitical zone risk baseline scores (0-100)
ZONE_BASELINE_RISK = {
    "Red Sea / Hormuz": 88,
    "Panama Canal": 62,
    "LatAm Ports": 48,
    "China / Taiwan Strait": 55,
    "Black Sea": 72,
}

# Lane → zones mapping
LANE_ZONES = {
    "Asia–Europe": ["Red Sea / Hormuz"],
    "Transpacific (Asia–USWC)": ["China / Taiwan Strait"],
    "Transpacific (Asia–USEC)": ["Panama Canal", "China / Taiwan Strait"],
    "Asia–LatAm": ["Panama Canal", "LatAm Ports"],
    "Asia–Middle East": ["Red Sea / Hormuz"],
    "Europe–LatAm": ["LatAm Ports"],
    "Europe–Middle East": ["Red Sea / Hormuz"],
    "Transatlantic": ["Black Sea"],
    "Intra-Asia": ["China / Taiwan Strait"],
}


def compute_lane_risk_score(
    lane: str,
    surcharge_notices: List[Dict],
    bunker_volatility: float = 0.0,
) -> Dict:
    """
    Compute a composite risk score (0–100) for a trade lane.

    Components:
      - Geopolitical zone baseline (40%)
      - Active surcharge severity (35%)
      - Bunker price volatility (15%)
      - Surcharge frequency / velocity (10%)
    """
    # 1. Geopolitical zone score
    zones = LANE_ZONES.get(lane, [])
    geo_score = 0.0
    if zones:
        zone_scores = [ZONE_BASELINE_RISK.get(z, 0) for z in zones]
        geo_score = max(zone_scores)  # Use worst zone

    # 2. Active surcharge severity for this lane
    lane_notices = [
        n for n in surcharge_notices
        if lane in (n.get("trade_lanes") or [])
    ]
    surcharge_score = 0.0
    active_types = set()
    for notice in lane_notices:
        for stype in notice.get("surcharge_types", []):
            weight = SURCHARGE_RISK_WEIGHTS.get(stype, 3)
            surcharge_score += weight
            active_types.add(stype)
    surcharge_score = min(surcharge_score, 100)

    # 3. Bunker volatility score (0–100)
    bunker_score = min(bunker_volatility * 100, 100)

    # 4. Velocity score — how many distinct notices in last 7 days
    velocity_score = min(len(lane_notices) * 5, 100)

    # Weighted composite
    composite = (
        geo_score * 0.40
        + surcharge_score * 0.35
        + bunker_score * 0.15
        + velocity_score * 0.10
    )
    composite = round(min(composite, 100), 1)

    # Risk tier
    if composite >= 75:
        tier = "CRITICAL"
        tier_color = "#ef4444"
    elif composite >= 55:
        tier = "HIGH"
        tier_color = "#f97316"
    elif composite >= 35:
        tier = "MEDIUM"
        tier_color = "#eab308"
    else:
        tier = "LOW"
        tier_color = "#22c55e"

    return {
        "lane": lane,
        "composite_score": composite,
        "tier": tier,
        "tier_color": tier_color,
        "geo_score": round(geo_score, 1),
        "surcharge_score": round(surcharge_score, 1),
        "bunker_score": round(bunker_score, 1),
        "velocity_score": round(velocity_score, 1),
        "active_surcharge_types": sorted(active_types),
        "notice_count": len(lane_notices),
        "affected_zones": zones,
    }


def compute_bunker_volatility(history: List[Dict]) -> float:
    """
    Compute normalized bunker price volatility (0–1) from a price history list.
    Uses coefficient of variation over the series.
    """
    if len(history) < 3:
        return 0.0
    prices = [h["price_usd_mt"] for h in history if "price_usd_mt" in h]
    if not prices:
        return 0.0
    mean = sum(prices) / len(prices)
    if mean == 0:
        return 0.0
    variance = sum((p - mean) ** 2 for p in prices) / len(prices)
    std_dev = variance ** 0.5
    cv = std_dev / mean  # Coefficient of variation
    return round(min(cv * 5, 1.0), 4)  # Scale to 0–1


def compute_all_lane_risks(
    surcharge_notices: List[Dict],
    bunker_history: Optional[List[Dict]] = None,
) -> List[Dict]:
    """Compute risk scores for all trade lanes."""
    volatility = 0.0
    if bunker_history:
        volatility = compute_bunker_volatility(bunker_history)

    results = []
    for lane in TRADE_LANES:
        score = compute_lane_risk_score(lane, surcharge_notices, volatility)
        results.append(score)

    # Sort by composite score descending
    results.sort(key=lambda x: x["composite_score"], reverse=True)
    return results


def compute_carrier_exposure(surcharge_notices: List[Dict]) -> List[Dict]:
    """
    Per-carrier surcharge exposure: how many active surcharges, total estimated
    cost impact per TEU, and affected lanes.
    """
    from app.config import TRACKED_CARRIERS
    carrier_data: Dict[str, Dict] = {}

    for notice in surcharge_notices:
        carrier = notice.get("carrier")
        if not carrier:
            continue
        if carrier not in carrier_data:
            carrier_data[carrier] = {
                "carrier": carrier,
                "notice_count": 0,
                "surcharge_types": set(),
                "trade_lanes": set(),
                "amounts": [],
            }
        carrier_data[carrier]["notice_count"] += 1
        for st in notice.get("surcharge_types", []):
            carrier_data[carrier]["surcharge_types"].add(st)
        for lane in notice.get("trade_lanes", []):
            carrier_data[carrier]["trade_lanes"].add(lane)
        if notice.get("amount"):
            carrier_data[carrier]["amounts"].append(notice["amount"])

    results = []
    for carrier, data in carrier_data.items():
        results.append({
            "carrier": carrier,
            "notice_count": data["notice_count"],
            "surcharge_types": sorted(data["surcharge_types"]),
            "trade_lanes": sorted(data["trade_lanes"]),
            "sample_amounts": data["amounts"][:3],
            "exposure_score": min(data["notice_count"] * 8 + len(data["surcharge_types"]) * 5, 100),
        })

    results.sort(key=lambda x: x["exposure_score"], reverse=True)
    return results


def save_risk_report(report: Dict) -> str:
    """Save risk report to data directory."""
    os.makedirs(DATA_DIR, exist_ok=True)
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    path = os.path.join(DATA_DIR, f"risk_{date_str}.json")
    with open(path, "w") as f:
        json.dump(report, f, indent=2)
    return path


def load_risk_report(date_str: Optional[str] = None) -> Optional[Dict]:
    """Load risk report for a given date."""
    if not date_str:
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    path = os.path.join(DATA_DIR, f"risk_{date_str}.json")
    if not os.path.exists(path):
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return None
