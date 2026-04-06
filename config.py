"""
Configuration for Commodity Bollinger Band Alert Tool.
All tunables in one place.
"""
import os

# ─── Instruments ───────────────────────────────────────────────────────────────
INSTRUMENTS = {
    "MGC": {
        "ticker": "GC=F",
        "name": "Micro Gold",
        "exchange": "COMEX",
        "fallback_ticker": None,
    },
    "SIL": {
        "ticker": "SI=F",
        "name": "Micro Silver",
        "exchange": "COMEX",
        "fallback_ticker": None,
    },
    "MCL": {
        "ticker": "CL=F",
        "name": "Micro Crude",
        "exchange": "NYMEX",
        "fallback_ticker": None,
    },
}

# ─── Bollinger Band Settings ──────────────────────────────────────────────────
BB_PERIOD = 20          # SMA lookback period
BB_STD_DEV = 1.5        # Standard deviation multiplier

# ─── Timeframe ────────────────────────────────────────────────────────────────
INTERVAL = "15m"         # yfinance interval
LOOKBACK_PERIOD = "7d"  # How far back to fetch (7d circumvents yfinance dropped candle bugs)

# ─── Higher Timeframe (for multi-TF confirmation) ────────────────────────────
HTF_INTERVAL = "1h"      # Higher timeframe interval
HTF_LOOKBACK = "15d"     # Longer lookback for 1h candles

# ─── Win/Loss Tracking ───────────────────────────────────────────────────────
RISK_REWARD_RATIO = 1.5  # 1:1.5 risk-to-reward for signal scoring
TRACKING_MAX_CANDLES = 16  # Max candles (4 hours on 15m) before marking as EXPIRED

# ─── Telegram ─────────────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

# ─── State File (for dedup across runs) ──────────────────────────────────────
STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "alert_state.json")
