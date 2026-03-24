"""
Configuration for Commodity Bollinger Band Alert Tool.
All tunables in one place.
"""
import os

# ─── Instruments ───────────────────────────────────────────────────────────────
INSTRUMENTS = {
    "MGC": {
        "ticker": "MGC=F",
        "name": "Micro Gold",
        "exchange": "COMEX",
        "fallback_ticker": None,
    },
    "SIL": {
        "ticker": "SIL=F",
        "name": "Micro Silver",
        "exchange": "COMEX",
        "fallback_ticker": None,
    },
    "MCL": {
        "ticker": "MCL=F",
        "name": "Micro Crude",
        "exchange": "NYMEX",
        "fallback_ticker": "CL=F",  # Standard WTI crude as fallback
    },
}

# ─── Bollinger Band Settings ──────────────────────────────────────────────────
BB_PERIOD = 20          # SMA lookback period
BB_STD_DEV = 1.5        # Standard deviation multiplier

# ─── Timeframe ────────────────────────────────────────────────────────────────
INTERVAL = "15m"         # yfinance interval
LOOKBACK_PERIOD = "5d"   # How far back to fetch (need >= BB_PERIOD candles)

# ─── Telegram ─────────────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

# ─── State File (for dedup across runs) ──────────────────────────────────────
STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "alert_state.json")
