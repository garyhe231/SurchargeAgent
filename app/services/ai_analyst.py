"""
AI Analyst — uses Claude via AWS Bedrock to synthesize surcharge notices,
bunker rates, and risk scores into actionable intelligence.
"""
import json
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional

import boto3
from botocore.config import Config

from app.config import AWS_REGION, CLAUDE_MODEL

logger = logging.getLogger(__name__)

_bedrock = None


def _get_client():
    global _bedrock
    if _bedrock is None:
        _bedrock = boto3.client(
            "bedrock-runtime",
            region_name=AWS_REGION,
            config=Config(read_timeout=120, connect_timeout=10),
        )
    return _bedrock


def _invoke(prompt: str, max_tokens: int = 4096) -> str:
    body = json.dumps({
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
    })
    resp = _get_client().invoke_model(
        modelId=CLAUDE_MODEL,
        body=body,
        contentType="application/json",
        accept="application/json",
    )
    return json.loads(resp["body"].read())["content"][0]["text"]


def _build_context(
    surcharge_notices: List[Dict],
    bunker_rates: List[Dict],
    lane_risks: List[Dict],
    carrier_exposure: List[Dict],
) -> str:
    top_notices = surcharge_notices[:15]
    notices_text = "\n".join(
        f"- [{n.get('carrier', 'Unknown carrier')}] {n['title'][:120]} "
        f"(Types: {', '.join(n.get('surcharge_types', ['?']))} | "
        f"Lanes: {', '.join(n.get('trade_lanes', ['?'])) or 'unspecified'} | "
        f"Amount: {n.get('amount', 'not stated')} | "
        f"Effective: {n.get('effective_date', 'not stated')})"
        for n in top_notices
    )

    sg_rates = {r["grade"]: r["price_usd_mt"] for r in bunker_rates if r.get("hub") == "Singapore"}
    rot_rates = {r["grade"]: r["price_usd_mt"] for r in bunker_rates if r.get("hub") == "Rotterdam"}
    fuj_rates = {r["grade"]: r["price_usd_mt"] for r in bunker_rates if r.get("hub") == "Fujairah"}

    bunker_text = (
        f"Singapore: VLSFO ${sg_rates.get('VLSFO', 'N/A')}/MT, "
        f"MGO ${sg_rates.get('MGO', 'N/A')}/MT, "
        f"IFO380 ${sg_rates.get('IFO380', 'N/A')}/MT\n"
        f"Rotterdam: VLSFO ${rot_rates.get('VLSFO', 'N/A')}/MT, "
        f"MGO ${rot_rates.get('MGO', 'N/A')}/MT\n"
        f"Fujairah: VLSFO ${fuj_rates.get('VLSFO', 'N/A')}/MT"
    )

    top_risks = lane_risks[:5]
    risk_text = "\n".join(
        f"- {r['lane']}: {r['tier']} ({r['composite_score']}/100) — "
        f"Zones: {', '.join(r['affected_zones']) or 'none'}"
        for r in top_risks
    )

    top_carriers = carrier_exposure[:5]
    carrier_text = "\n".join(
        f"- {c['carrier']}: {c['notice_count']} notices, "
        f"types: {', '.join(c['surcharge_types'])}"
        for c in top_carriers
    )

    return f"""SURCHARGE NOTICES ({len(surcharge_notices)} total):
{notices_text or 'No notices found'}

BUNKER RATES:
{bunker_text}

TOP RISK TRADE LANES:
{risk_text or 'No lane risk data'}

CARRIER SURCHARGE ACTIVITY:
{carrier_text or 'No carrier data'}
"""


def generate_executive_brief(
    surcharge_notices: List[Dict],
    bunker_rates: List[Dict],
    lane_risks: List[Dict],
    carrier_exposure: List[Dict],
) -> str:
    context = _build_context(surcharge_notices, bunker_rates, lane_risks, carrier_exposure)
    today = datetime.now(timezone.utc).strftime("%B %d, %Y")

    prompt = f"""You are a senior freight market analyst at a global logistics company. Today is {today}.

Based on the following real-time surcharge and market data, produce a comprehensive executive intelligence brief for freight procurement and operations teams. The brief should be formatted in clean HTML (no markdown) suitable for embedding in a dashboard.

DATA:
{context}

Your brief MUST cover all of the following sections in order:

1. <h3>Executive Summary</h3>
   2-3 sentence summary of the most critical surcharge developments today. What is the single biggest cost risk?

2. <h3>Critical Surcharge Alerts</h3>
   Bullet list of the most impactful active surcharges by carrier and trade lane. Flag any EBS/WRS/RSA surcharges as highest priority. Include amounts where available.

3. <h3>Bunker Rate Analysis</h3>
   Analysis of current bunker prices vs. expected BAF/EBS levels. Are carriers justified in current surcharge levels based on fuel costs? Are BAF levels aligned with VLSFO prices?

4. <h3>Trade Lane Risk Assessment</h3>
   For each high/critical risk lane, explain the compound risk factors (geopolitical + fuel + congestion). Include specific recommendations (e.g., "Consider booking WCSA cargo 30 days in advance to lock pre-GRI rates").

5. <h3>Geopolitical Risk Focus</h3>
   Deep analysis of Iran/Strait of Hormuz risk and its compounding effect on fuel costs and war risk surcharges. Include LatAm port congestion impact.

6. <h3>Carrier Strategy Intelligence</h3>
   Which carriers are most aggressively raising surcharges? Any carriers showing restraint that could be leveraged for rate negotiations?

7. <h3>Cost Impact Estimates</h3>
   Estimate total surcharge cost impact per TEU for key lanes (Asia-Europe, Transpacific). Break down by surcharge type.

8. <h3>Recommended Actions</h3>
   Concrete, prioritized action items for procurement teams. Be specific and time-bound where possible.

Use <strong> tags for carrier names and surcharge types. Use <span class="risk-critical">, <span class="risk-high">, <span class="risk-medium">, <span class="risk-low"> for risk levels. Keep the tone professional and direct."""

    try:
        return _invoke(prompt, max_tokens=4096)
    except Exception as exc:
        logger.error("AI brief generation failed: %s", exc)
        return f"<p><em>AI analysis error: {exc}</em></p>"


def generate_lane_deep_dive(
    lane: str,
    surcharge_notices: List[Dict],
    bunker_rates: List[Dict],
    risk_data: Dict,
) -> str:
    lane_notices = [n for n in surcharge_notices if lane in (n.get("trade_lanes") or [])]
    today = datetime.now(timezone.utc).strftime("%B %d, %Y")

    notices_text = "\n".join(
        f"- {n.get('carrier', 'Unknown')}: {n['title'][:100]} "
        f"(Amount: {n.get('amount', 'N/A')}, Effective: {n.get('effective_date', 'N/A')})"
        for n in lane_notices[:10]
    )

    bunker_summary = ", ".join(
        f"{r['hub']} {r['grade']}: ${r['price_usd_mt']}/MT"
        for r in bunker_rates
        if r.get("hub") in ["Singapore", "Rotterdam", "Fujairah"]
        and r.get("grade") == "VLSFO"
    )

    prompt = f"""You are a freight market analyst. Today is {today}.

Provide a detailed intelligence brief for the **{lane}** trade lane.

LANE RISK PROFILE:
- Composite Risk Score: {risk_data.get('composite_score', 'N/A')}/100
- Tier: {risk_data.get('tier', 'N/A')}
- Affected Risk Zones: {', '.join(risk_data.get('affected_zones', []))}
- Active Surcharge Types: {', '.join(risk_data.get('active_surcharge_types', []))}
- Notice Count: {risk_data.get('notice_count', 0)}

SURCHARGE NOTICES FOR THIS LANE:
{notices_text or 'No specific notices found'}

BUNKER RATES (VLSFO):
{bunker_summary or 'Not available'}

Write a focused 300-400 word HTML analysis covering:
1. Current surcharge situation on this lane
2. How bunker rates are driving costs
3. Geopolitical factors specific to this lane
4. Outlook for the next 30-60 days
5. Negotiation leverage points for shippers

Format as clean HTML paragraphs with <h4> subheadings."""

    try:
        return _invoke(prompt, max_tokens=1024)
    except Exception as exc:
        logger.error("Lane deep dive failed: %s", exc)
        return f"<p><em>Analysis error: {exc}</em></p>"


def answer_surcharge_question(
    question: str,
    surcharge_notices: List[Dict],
    bunker_rates: List[Dict],
    lane_risks: List[Dict],
) -> str:
    context = _build_context(surcharge_notices, bunker_rates, lane_risks, [])
    today = datetime.now(timezone.utc).strftime("%B %d, %Y")

    prompt = f"""You are a senior freight surcharge analyst. Today is {today}.

Use the following market data to answer the user's question. Be specific, cite data from the context, and be concise.

MARKET DATA:
{context}

USER QUESTION: {question}

Answer in 2-4 paragraphs. If the data doesn't contain enough information to fully answer, say so and provide what context you can."""

    try:
        return _invoke(prompt, max_tokens=800)
    except Exception as exc:
        logger.error("Q&A failed: %s", exc)
        return f"Error: {exc}"
