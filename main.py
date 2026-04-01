"""
Commodity Bollinger Band Alert Tool — Main Entry Point.

Runs as a single invocation (called by cron-job.org / GitHub Actions).
Fetches data → computes BB → checks signals → sends Telegram alerts → exits.
Includes run-dedup to prevent double-firing when both triggers are active.
"""
import json
import os
import sys
from datetime import datetime, timezone, timedelta

import config
import pandas as pd
from data_fetcher import fetch_all_instruments, fetch_all_htf_instruments, is_market_open
from bollinger import detect_signals, check_reversal, compute_bollinger_bands
from telegram_notifier import send_alert, send_photo
import journaler
import chart_generator
import bot_commands
import signal_tracker
import traceback


# Minimum gap between runs (seconds). If last run was within this window, skip.
# Prevents double-firing when both cron-job.org and GitHub cron trigger.
RUN_DEDUP_SECONDS = 180  # 3 minutes


def load_state() -> dict:
    """Load the last alert state to prevent duplicate alerts."""
    if os.path.exists(config.STATE_FILE):
        try:
            with open(config.STATE_FILE, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return {}
    return {}


def save_state(memory_state: dict):
    """Save alert state for dedup across runs, safely merging variables modified by Telegram bot."""
    current_state = {}
    if os.path.exists(config.STATE_FILE):
        try:
            with open(config.STATE_FILE, "r") as f:
                current_state = json.load(f)
        except (json.JSONDecodeError, IOError):
            pass

    # Preserve Telegram-driven states if they were modified mid-run
    if "is_sleeping" in current_state:
        memory_state["is_sleeping"] = current_state["is_sleeping"]

    # Preserve custom price alarms added mid-run
    if "price_alarms" in current_state:
        mem_alarms = memory_state.get("price_alarms", {})
        file_alarms = current_state["price_alarms"]
        for sym, alarms in file_alarms.items():
            if sym not in mem_alarms:
                mem_alarms[sym] = alarms
            else:
                # Merge unique values
                merged = list(set(mem_alarms[sym] + alarms))
                mem_alarms[sym] = merged
        memory_state["price_alarms"] = mem_alarms

    try:
        with open(config.STATE_FILE, "w") as f:
            json.dump(memory_state, f, indent=2)
    except IOError as e:
        print(f"❌ Error saving state: {e}")


def is_run_duplicate(state: dict) -> bool:
    """
    Check if another run completed recently (within RUN_DEDUP_SECONDS).
    Prevents double-firing when both cron-job.org and GitHub cron trigger.
    """
    last_run = state.get("last_run_time")
    if not last_run:
        return False
    try:
        last_dt = datetime.fromisoformat(last_run)
        elapsed = (datetime.now(timezone.utc) - last_dt).total_seconds()
        if elapsed < RUN_DEDUP_SECONDS:
            print(f"⏭️  Run dedup: last run was {elapsed:.0f}s ago (< {RUN_DEDUP_SECONDS}s). Skipping.")
            return True
    except (ValueError, TypeError):
        pass
    return False


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


def send_error_alert(error_type: str, details: str):
    """Send a structured error alert to Telegram."""
    error_msg = {
        "emoji": "⚠️",
        "label": f"{error_type}: {details[:80]}",
        "type": "ERROR",
        "close": 0, "high": 0, "low": 0, "upper_bb": 0, "lower_bb": 0,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }
    send_alert(error_msg, "SYSTEM")


def main():
    print("=" * 60)
    print(f"🕐 Commodity BB Alert — {datetime.now(timezone.utc).isoformat()} UTC")
    print("=" * 60)

    # Check for interactive commands (/status, /s) — ALWAYS runs
    print("\n🤖 Checking for bot commands...")
    bot_commands.process_commands()

    # Quiet hours: 1 AM - 6 AM IST — skip BB alerts (save GitHub minutes)
    from zoneinfo import ZoneInfo
    ist_hour = datetime.now(ZoneInfo("Asia/Kolkata")).hour
    if 1 <= ist_hour < 6:
        print("🌙 Quiet hours (1-6 AM IST). Skipping BB check. /status still active.")
        return

    # Load dedup state
    state = load_state()

    # ── Run dedup: skip if another trigger already ran recently ──
    if is_run_duplicate(state):
        return

    # Mark this run's timestamp (save immediately for dedup)
    state["last_run_time"] = datetime.now(timezone.utc).isoformat()

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
    save_state(state)  # Save early in case of later errors

    # Check if bot is asleep from Telegram command
    if state.get("is_sleeping", False):
        print("💤 Bot is sleeping (/sleep). Skipping all checks.")
        return

    # Check if market is open
    if not currently_open:
        print("📴 Market is closed. Skipping data fetch.")
        return

    # Fetch candles for all instruments
    print("\n📊 Fetching 15-min candle data...")
    data = fetch_all_instruments()

    if not data:
        print("❌ No data fetched for any instrument. Exiting.")
        send_error_alert("DATA ERROR", "No data fetched for any instrument. yfinance may be down.")
        return

    # Fetch 1h candles for multi-timeframe confirmation
    print("📊 Fetching 1h candle data (multi-TF)...")
    htf_data = fetch_all_htf_instruments()

    # Check for partial failures (some instruments missing)
    missing = [sym for sym in config.INSTRUMENTS if sym not in data]
    if missing:
        print(f"⚠️ Missing data for: {', '.join(missing)}")
        send_error_alert("DATA WARNING", f"No data for: {', '.join(missing)}")

    # ── Update Win/Loss Tracking ──
    print("\n📈 Updating signal tracking...")
    completed_signals = signal_tracker.update_tracking(state, data)
    for outcome in completed_signals:
        emoji = "✅" if outcome["result"] == "WIN" else "❌" if outcome["result"] == "LOSS" else "⏳"
        result_msg = (
            f"{emoji} *Signal Result: {outcome['result']}*\n"
            f"\n"
            f"📍 {outcome['symbol']} {outcome['direction']}\n"
            f"💰 Entry: ${outcome['entry_price']:,.2f}\n"
            f"🎯 Target: ${outcome['target']:,.2f} | 🛑 SL: ${outcome['sl']:,.2f}\n"
            f"📊 Exit: ${outcome['exit_price']:,.2f} ({outcome['pnl_points']:+,.2f} pts)\n"
            f"⏱️ Resolved in {outcome['candles_to_resolve']} candles"
        )
        send_alert({"emoji": emoji, "label": f"Signal {outcome['result']}", "type": "RESULT", "close": outcome['exit_price'], "high": 0, "low": 0, "upper_bb": 0, "lower_bb": 0, "timestamp": outcome['resolved_at']}, "SYSTEM")
        # Send the detailed result as a separate message
        from telegram_notifier import send_alert as _sa
        import requests
        if config.TELEGRAM_BOT_TOKEN and config.TELEGRAM_CHAT_ID:
            url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage"
            requests.post(url, json={"chat_id": config.TELEGRAM_CHAT_ID, "text": result_msg, "parse_mode": "Markdown"}, timeout=10)

    alerts_sent = 0

    for symbol, df in data.items():
        instrument_name = config.INSTRUMENTS[symbol]["name"]
        print(f"\n🔍 Analyzing {instrument_name} ({symbol})...")

        signals = []

        # ── 1. Check for Reversal Confirmations on Active Triggers ──
        if "trigger_candles" not in state:
            state["trigger_candles"] = {}
            
        active_trigger = state["trigger_candles"].get(symbol)
        if active_trigger:
            reversal_signals, expired = check_reversal(df, active_trigger)
            
            if expired:
                print(f"   ⏳ Trigger expired for {symbol} (4 candles passed).")
                del state["trigger_candles"][symbol]
            elif reversal_signals:
                # We have a reversal break or close!
                signals.extend(reversal_signals)
                
                # If a CLOSE confirmation happens, the setup has completed its lifecycle.
                # Remove the trigger so we don't get duplicate 'Reversal Confirmed' spam 
                # on the next 15-min candle if price stays below the trigger line.
                if any("CLOSE" in s["type"] for s in reversal_signals):
                    print(f"   ✅ Reversal Confirmed for {symbol}. Setup complete, removing trigger.")
                    del state["trigger_candles"][symbol]

        # ── 1.5 Check Custom Price Alarms ──
        active_alarms = state.get("price_alarms", {}).get(symbol, [])
        if active_alarms:
            new_alarms = []
            triggered_any = False
            
            for alarm_price in active_alarms:
                c_low = float(df.iloc[-1]["Low"])
                c_high = float(df.iloc[-1]["High"])
                c_close = float(df.iloc[-1]["Close"])
                
                # If the alarm price is within this candle's High/Low range, it crossed!
                if c_low <= alarm_price <= c_high:
                    signals.append({
                        "type": "ALARM",
                        "emoji": "⏰",
                        "label": f"PRICE ALARM TRIGGERED: ${alarm_price:,.2f}!",
                        "close": c_close,
                        "high": c_high,
                        "low": c_low,
                        "timestamp": str(df.index[-1]),
                        "upper_bb": float(df.iloc[-1].get("BB_Upper", 0)) if not pd.isna(df.iloc[-1].get("BB_Upper")) else 0,
                        "lower_bb": float(df.iloc[-1].get("BB_Lower", 0)) if not pd.isna(df.iloc[-1].get("BB_Lower")) else 0,
                    })
                    triggered_any = True
                    print(f"   ⏰ Custom Alarm fired for {symbol} at {alarm_price}")
                else:
                    new_alarms.append(alarm_price)
            
            if triggered_any:
                # Remove the triggered alarms from state so they don't fire again
                state["price_alarms"][symbol] = new_alarms

        # ── 2. Detect Standard Signals on Last Candle ──
        try:
            standard_signals = detect_signals(df)
            signals.extend(standard_signals)
        except Exception as e:
            print(f"   ❌ Signal detection error for {symbol}: {e}")
            send_error_alert("SIGNAL ERROR", f"{symbol}: {str(e)}")
            continue

        # ── 3. Multi-Timeframe Confirmation ──
        htf_df = htf_data.get(symbol)
        htf_above_upper = False
        htf_below_lower = False
        if htf_df is not None and not htf_df.empty:
            try:
                htf_bb = compute_bollinger_bands(htf_df)
                htf_last = htf_bb.iloc[-1]
                if not pd.isna(htf_last.get("BB_Upper")) and not pd.isna(htf_last.get("BB_Lower")):
                    htf_close = float(htf_last["Close"])
                    htf_upper = float(htf_last["BB_Upper"])
                    htf_lower = float(htf_last["BB_Lower"])
                    htf_above_upper = htf_close > htf_upper
                    htf_below_lower = htf_close < htf_lower
            except Exception as e:
                print(f"   ⚠️ HTF check error for {symbol}: {e}")

        # Tag signals with multi-TF confirmation
        for signal in signals:
            sig_type = signal.get("type", "")
            if "UPPER" in sig_type and htf_above_upper:
                signal["multi_tf"] = True
                signal["label"] = "🚨🚨 DOUBLE TIMEFRAME! " + signal["label"]
                print(f"   🔥 Multi-TF CONFIRMED on 1h for {symbol} UPPER")
            elif "LOWER" in sig_type and htf_below_lower:
                signal["multi_tf"] = True
                signal["label"] = "🚨🚨 DOUBLE TIMEFRAME! " + signal["label"]
                print(f"   🔥 Multi-TF CONFIRMED on 1h for {symbol} LOWER")

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

                # ── Record New Triggers ──
                # If this was a PRIORITY signal, save it as an active trigger for reversal checks
                sig_type = signal["type"]
                if "PRIORITY" in sig_type:
                    if "trigger_candles" not in state:
                        state["trigger_candles"] = {}
                    
                    state["trigger_candles"][symbol] = {
                        "type": sig_type,
                        "trigger_timestamp": signal["timestamp"],
                        "trigger_low": signal["low"],
                        "trigger_high": signal["high"]
                    }
                    print(f"   🎯 Saved active trigger for {symbol}: {sig_type}")

                    # ── Start Win/Loss Tracking ──
                    signal_tracker.track_new_signal(state, symbol, signal)

                # ── Generate Charts ──
                # Only for PRIORITY (trigger), REVERSAL signals, and ALARMs
                if "PRIORITY" in sig_type or "REVERSAL" in sig_type or "ALARM" in sig_type:
                    try:
                        chart_path = chart_generator.generate_chart(df, symbol, instrument_name, signal)
                        if chart_path:
                            send_photo(chart_path, f"📊 {instrument_name} ({symbol}) — {signal['label']}")
                    except Exception as e:
                        print(f"   ❌ Chart generation error: {e}")
                        send_error_alert("CHART ERROR", f"{symbol}: {str(e)}")

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
        
        # Send detailed error alert to Telegram
        send_error_alert("🔥 FATAL ERROR", str(e))

if __name__ == "__main__":
    run_with_error_handling()
