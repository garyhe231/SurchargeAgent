"""
Surcharge collector — scrapes RSS feeds and shipping news for carrier
emergency surcharge announcements, parses structured data, and stores results.
"""
import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Dict, List, Optional

import feedparser
import requests
from bs4 import BeautifulSoup

from app.config import (
    DATA_DIR,
    SURCHARGE_FEEDS,
    SURCHARGE_TYPES,
    TRACKED_CARRIERS,
    TRADE_LANES,
)

logger = logging.getLogger(__name__)

SURCHARGE_KEYWORDS = list(SURCHARGE_TYPES.keys()) + [
    "surcharge", "rate increase", "emergency", "bunker", "fuel adjustment",
    "war risk", "congestion", "peak season", "GRI", "BAF", "EBS", "PSS",
    "notice", "effective", "per TEU", "per FEU", "USD/TEU", "USD/FEU",
]


def _extract_amount(text: str) -> Optional[str]:
    """Extract dollar amount from text, e.g. '$450/TEU'."""
    patterns = [
        r"\$\s?[\d,]+(?:\.\d+)?(?:\s?(?:per|/)\s?(?:TEU|FEU|container|box))?",
        r"USD\s?[\d,]+(?:\.\d+)?(?:\s?(?:per|/)\s?(?:TEU|FEU|container|box))?",
        r"[\d,]+(?:\.\d+)?\s?USD(?:\s?(?:per|/)\s?(?:TEU|FEU|container|box))?",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            return m.group(0).strip()
    return None


def _extract_effective_date(text: str) -> Optional[str]:
    """Extract an effective date from surcharge notice text."""
    patterns = [
        r"effective\s+(?:from\s+)?([A-Z][a-z]+\.?\s+\d{1,2},?\s+\d{4})",
        r"effective\s+(?:from\s+)?(\d{1,2}\s+[A-Z][a-z]+\.?\s+\d{4})",
        r"(?:from|as of|starting)\s+([A-Z][a-z]+\.?\s+\d{1,2},?\s+\d{4})",
        r"(\d{4}-\d{2}-\d{2})",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            return m.group(1).strip()
    return None


def _detect_carrier(text: str) -> Optional[str]:
    """Detect which carrier the notice is about."""
    text_lower = text.lower()
    for carrier in TRACKED_CARRIERS:
        if carrier.lower() in text_lower:
            return carrier
    return None


def _detect_surcharge_types(text: str) -> List[str]:
    """Detect which surcharge types are mentioned."""
    found = []
    for code, name in SURCHARGE_TYPES.items():
        if code in text or name.lower() in text.lower():
            found.append(code)
    return found


def _detect_trade_lanes(text: str) -> List[str]:
    """Detect which trade lanes are mentioned."""
    found = []
    text_lower = text.lower()
    lane_keywords = {
        "Asia–Europe": ["asia europe", "asia-europe", "far east europe", "fe/europe", "europe/fe"],
        "Transpacific (Asia–USWC)": ["transpacific", "asia uswc", "far east west coast", "tpwc", "usw"],
        "Transpacific (Asia–USEC)": ["usec", "east coast", "us east", "asia usec"],
        "Asia–LatAm": ["latin america", "latam", "south america", "wcsa", "ecsa"],
        "Asia–Middle East": ["middle east", "persian gulf", "arabian gulf"],
        "Europe–LatAm": ["europe latam", "europe latin", "europe south america"],
        "Europe–Middle East": ["europe middle east"],
        "Transatlantic": ["transatlantic", "north atlantic", "europe us", "us europe"],
        "Intra-Asia": ["intra asia", "intra-asia", "southeast asia", "sea"],
    }
    for lane, keywords in lane_keywords.items():
        for kw in keywords:
            if kw in text_lower:
                found.append(lane)
                break
    return list(set(found))


def fetch_feed_entries(feed_url: str) -> List[Dict]:
    """Fetch RSS feed and return surcharge-relevant entries."""
    entries = []
    try:
        parsed = feedparser.parse(feed_url)
        for entry in parsed.entries[:30]:
            title = entry.get("title", "")
            summary = entry.get("summary", "") or entry.get("description", "")
            content_raw = summary
            if hasattr(entry, "content"):
                content_raw = entry.content[0].value if entry.content else summary

            full_text = f"{title} {content_raw}"
            full_text_clean = BeautifulSoup(full_text, "html.parser").get_text(" ")

            # Check relevance
            relevant = any(
                kw.lower() in full_text_clean.lower() for kw in SURCHARGE_KEYWORDS
            )
            if not relevant:
                continue

            carrier = _detect_carrier(full_text_clean)
            surcharge_types = _detect_surcharge_types(full_text_clean)
            trade_lanes = _detect_trade_lanes(full_text_clean)
            amount = _extract_amount(full_text_clean)
            effective_date = _extract_effective_date(full_text_clean)

            pub_date = entry.get("published", "")
            link = entry.get("link", "")

            entries.append({
                "title": title[:200],
                "summary": full_text_clean[:600],
                "carrier": carrier,
                "surcharge_types": surcharge_types,
                "trade_lanes": trade_lanes,
                "amount": amount,
                "effective_date": effective_date,
                "published": pub_date,
                "source_url": link,
                "source_feed": feed_url,
                "fetched_at": datetime.now(timezone.utc).isoformat(),
            })
    except Exception as exc:
        logger.warning("Feed fetch error %s: %s", feed_url, exc)
    return entries


def collect_all_surcharges() -> List[Dict]:
    """Collect surcharge notices from all configured feeds."""
    all_entries: List[Dict] = []
    seen_titles = set()
    for feed_url in SURCHARGE_FEEDS:
        entries = fetch_feed_entries(feed_url)
        for entry in entries:
            key = entry["title"].lower().strip()
            if key not in seen_titles:
                seen_titles.add(key)
                all_entries.append(entry)
    logger.info("Collected %d surcharge notices", len(all_entries))
    return all_entries


def save_surcharges(notices: List[Dict]) -> str:
    """Persist surcharge notices to JSON. Returns file path."""
    os.makedirs(DATA_DIR, exist_ok=True)
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    path = os.path.join(DATA_DIR, f"surcharges_{date_str}.json")

    existing: List[Dict] = []
    if os.path.exists(path):
        try:
            with open(path) as f:
                existing = json.load(f)
        except Exception:
            existing = []

    # Merge, deduplicate by title
    existing_titles = {e["title"].lower().strip() for e in existing}
    new_entries = [n for n in notices if n["title"].lower().strip() not in existing_titles]
    merged = existing + new_entries

    with open(path, "w") as f:
        json.dump(merged, f, indent=2)

    logger.info("Saved %d notices to %s (%d new)", len(merged), path, len(new_entries))
    return path


def load_surcharges(date_str: Optional[str] = None) -> List[Dict]:
    """Load surcharge notices for a given date (default today)."""
    if not date_str:
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    path = os.path.join(DATA_DIR, f"surcharges_{date_str}.json")
    if not os.path.exists(path):
        return []
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return []


def list_available_dates() -> List[str]:
    """Return sorted list of dates that have surcharge data."""
    if not os.path.exists(DATA_DIR):
        return []
    dates = []
    for fname in os.listdir(DATA_DIR):
        m = re.match(r"surcharges_(\d{4}-\d{2}-\d{2})\.json", fname)
        if m:
            dates.append(m.group(1))
    return sorted(dates, reverse=True)
