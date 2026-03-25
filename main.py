"""
Commodity Bollinger Band Alert Tool — Main Entry Point.

Runs as a single invocation (called by GitHub Actions every 15 min).
Fetches data → computes BB → checks signals → sends Telegram alerts → exits.
"""
import json
import os
import sys
from datetime import datetime, timezone

import config
from data_fetcher import fetch_all_instruments, is_market_open
from bollinger import detect_signals
from telegram_notifier import send_alert
import journaler
import bot_commands
import traceback



def load_state() -> dict:
    """Load the last alert state to prevent duplicate alerts."""
    if os.path.exists(config.STATE_FILE):
        try:
            with open(config.STATE_FILE, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return {}
    return {}


def save_state(state: dict):
    """Save alert state for dedup across runs."""
    with open(config.STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def is_duplicate(state: dict, symbol: str, signal_type: str, timestamp: str) -> bool:
    """
    Check if this exact signal was already sent.
    Dedup key: symbol + signal_type + candle_timestamp
    Max one message per alert type per 15-min candle per instrument.
    """
    key = f"{symbol}_{signal_type}_{timestamp}"
    return key in state.get("sent_alerts", {})


def record_alert(state: dict, symbol: str, signal_type: str, timestamp: str):
    """Record that an alert was sent."""
    if "sent_alerts" not in state:
        state["sent_alerts"] = {}
    key = f"{symbol}_{signal_type}_{timestamp}"
    state["sent_alerts"][key] = datetime.now(timezone.utc).isoformat()

    # Clean old entries (keep only last 200 to prevent file growth)
    if len(state["sent_alerts"]) > 200:
        entries = sorted(state["sent_alerts"].items(), key=lambda x: x[1])
        state["sent_alerts"] = dict(entries[-100:])


def main():
    print("=" * 60)
    print(f"🕐 Commodity BB Alert — {datetime.now(timezone.utc).isoformat()} UTC")
    print("=" * 60)

    # Check for interactive commands (/status, /s)
    print("\n🤖 Checking for bot commands...")
    bot_commands.process_commands()

    # Load dedup state
    state = load_state()
    
    # Market open/close state tracking
    currently_open = is_market_open()
    last_status = state.get("last_market_status", None)
    
    if currently_open and last_status == "CLOSED":
        # Market just opened!
        send_alert({"emoji": "🟢", "label": "Market is OPEN!", "type": "INFO", "close": 0, "high": 0, "low": 0, "upper_bb": 0, "lower_bb": 0, "timestamp": datetime.now(timezone.utc).isoformat()}, "SYSTEM")
    elif not currently_open and last_status == "OPEN":
        # Market just closed!
        send_alert({"emoji": "🔴", "label": "Market is CLOSED for the weekend/break.", "type": "INFO", "close": 0, "high": 0, "low": 0, "upper_bb": 0, "lower_bb": 0, "timestamp": datetime.now(timezone.utc).isoformat()}, "SYSTEM")
        
    # Update last known status
    state["last_market_status"] = "OPEN" if currently_open else "CLOSED"
    save_state(state) # Save early in case of later errors

    # Check if market is open
    if not currently_open:
        print("📴 Market is closed. Skipping data fetch.")
        return

    # Fetch candles for all instruments
    print("\n📊 Fetching 15-min candle data...")
    data = fetch_all_instruments()

    if not data:
        print("❌ No data fetched for any instrument. Exiting.")
        return

    alerts_sent = 0

    for symbol, df in data.items():
        instrument_name = config.INSTRUMENTS[symbol]["name"]
        print(f"\n🔍 Analyzing {instrument_name} ({symbol})...")

        # Detect signals on last candle
        signals = detect_signals(df)

        if not signals:
            print(f"   ✅ No signal — price within bands.")
            continue

        for signal in signals:
            # Check dedup
            if is_duplicate(state, symbol, signal["type"], signal["timestamp"]):
                print(f"   ⏭️  Skipping duplicate: {signal['type']} at {signal['timestamp']}")
                continue

            # Send alert
            print(f"   🚨 Signal: {signal['label']}")
            success = send_alert(signal, symbol)

            if success:
                record_alert(state, symbol, signal["type"], signal["timestamp"])
                journaler.log_alert(symbol, signal["type"], signal["close"], signal["upper_bb"], signal["lower_bb"], signal["timestamp"])
                alerts_sent += 1

    # Save state
    save_state(state)

    print(f"\n{'=' * 60}")
    print(f"✅ Done. {alerts_sent} alert(s) sent.")
    print(f"{'=' * 60}")

def run_with_error_handling():
    """Wrapper to catch and alert on fatal errors."""
    try:
        main()
    except Exception as e:
        error_trace = traceback.format_exc()
        print(f"❌ FATAL ERROR:\n{error_trace}")
        
        # Send error alert to Telegram
        error_msg = {
            "emoji": "⚠️",
            "label": f"SYSTEM ERROR: {str(e)[:50]}...",
            "type": "ERROR",
            "close": 0, "high": 0, "low": 0, "upper_bb": 0, "lower_bb": 0,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        send_alert(error_msg, "SYSTEM")

if __name__ == "__main__":
    run_with_error_handling()
