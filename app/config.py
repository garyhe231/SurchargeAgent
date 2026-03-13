"""
SurchargeAgent — configuration constants.
"""
import os

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL = "claude-opus-4-6"

# Carriers to monitor
TRACKED_CARRIERS = [
    "Maersk", "MSC", "CMA CGM", "Evergreen", "Hapag-Lloyd",
    "ONE", "Yang Ming", "HMM", "Cosco", "PIL",
    "ZIM", "OOCL",
]

# Surcharge types
SURCHARGE_TYPES = {
    "EBS": "Emergency Bunker Surcharge",
    "BAF": "Bunker Adjustment Factor",
    "GRI": "General Rate Increase",
    "PSS": "Peak Season Surcharge",
    "CAF": "Currency Adjustment Factor",
    "LSS": "Low Sulphur Surcharge",
    "ECS": "Emergency Cost Surcharge",
    "WRS": "War Risk Surcharge",
    "PSC": "Port Surcharge / Congestion",
    "SCS": "Suez Canal Surcharge",
    "RSA": "Red Sea Avoidance Surcharge",
    "PCS": "Panama Canal Surcharge",
    "OWS": "Overweight Surcharge",
    "THC": "Terminal Handling Charge",
    "AMS": "Automated Manifest System Fee",
    "ISF": "Importer Security Filing",
}

# Trade lanes
TRADE_LANES = [
    "Asia–Europe",
    "Transpacific (Asia–USWC)",
    "Transpacific (Asia–USEC)",
    "Asia–LatAm",
    "Asia–Middle East",
    "Europe–LatAm",
    "Europe–Middle East",
    "Transatlantic",
    "Intra-Asia",
]

# Geopolitical risk zones
RISK_ZONES = {
    "Red Sea / Hormuz": {
        "description": "Houthi attacks, Iranian tensions, Strait of Hormuz disruption risk",
        "affected_lanes": ["Asia–Europe", "Asia–Middle East", "Europe–Middle East"],
    },
    "Panama Canal": {
        "description": "Water level restrictions, drought-driven capacity limits",
        "affected_lanes": ["Transpacific (Asia–USEC)", "Europe–LatAm"],
    },
    "LatAm Ports": {
        "description": "Labor strikes, congestion at Santos, Manzanillo, Callao",
        "affected_lanes": ["Asia–LatAm", "Europe–LatAm"],
    },
    "China / Taiwan Strait": {
        "description": "Geopolitical tensions, potential disruption to intra-Asia trade",
        "affected_lanes": ["Transpacific (Asia–USWC)", "Transpacific (Asia–USEC)", "Intra-Asia"],
    },
    "Black Sea": {
        "description": "Ukraine-Russia conflict, grain corridor disruption",
        "affected_lanes": ["Transatlantic"],
    },
}

# RSS / news feeds to monitor for surcharge notices
SURCHARGE_FEEDS = [
    # Freightos blog / news
    "https://www.freightos.com/feed/",
    # The Loadstar
    "https://theloadstar.com/feed/",
    # Splash247
    "https://splash247.com/feed/",
    # TradeWinds
    "https://www.tradewindsnews.com/rss",
    # JOC
    "https://www.joc.com/rss.xml",
    # Hellenic Shipping News
    "https://www.hellenicshippingnews.com/feed/",
]

# Bunker price sources (public data)
BUNKER_SOURCES = [
    "https://shipandbunker.com/prices",
]

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
