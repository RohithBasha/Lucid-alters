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

    # Check if market is open
    if not is_market_open():
        print("📴 Market is closed. Skipping.")
        return

    # Load dedup state
    state = load_state()

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
                alerts_sent += 1

    # Save state
    save_state(state)

    print(f"\n{'=' * 60}")
    print(f"✅ Done. {alerts_sent} alert(s) sent.")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
