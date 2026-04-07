"""
Interactive Telegram Bot Commands.
Checks for incoming /status commands via getUpdates polling
and replies with live price & BB data for all instruments.
Runs within the existing GitHub Actions cron (every 5 min).
"""
import os
import requests
import traceback
from datetime import datetime
from zoneinfo import ZoneInfo

import json
import config
import pandas as pd
from data_fetcher import fetch_candles
from bollinger import compute_bollinger_bands
import chart_generator
from telegram_notifier import send_photo
import signal_tracker

import re

IST = ZoneInfo("Asia/Kolkata")
LAST_UPDATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "last_update_id.txt")

CONTRACT_MULTIPLIERS = {
    "MGC": 10,
    "SIL": 1000,
    "MCL": 100,
    "MNQ": 2
}

def _build_list_message() -> str:
    """Generate Markdown table for profit target points."""
    targets = [100, 200, 300, 400, 500, 600, 700, 800, 900, 1000, 1500, 2000, 2500, 3000]
    
    lines = ["🎯 *Points Needed for Profit Targets*"]
    lines.append("```text")
    lines.append("Target | MGC   | SIL  | MCL   | MNQ   ")
    lines.append("-------|-------|------|-------|-------")
    
    for t in targets:
        mgc = t / CONTRACT_MULTIPLIERS["MGC"]
        sil = t / CONTRACT_MULTIPLIERS["SIL"]
        mcl = t / CONTRACT_MULTIPLIERS["MCL"]
        mnq = t / CONTRACT_MULTIPLIERS["MNQ"]
        
        # Format neatly: $100 -> $100  | 10.0  | 0.10 | 1.0   | 50.0 
        line = f"${t:<5}| {mgc:<5.1f} | {sil:<4.2f} | {mcl:<5.1f} | {mnq:<5.1f}"
        lines.append(line)
        
    lines.append("```")
    lines.append("_Note: Values represent full contract points, not minimum ticks._")
    return "\n".join(lines)

def _parse_dynamic_target(text: str) -> str:
    """Parse text like 'mgc 2000$' or 'mcl 500' and return the points needed."""
    match = re.search(r'\b(mgc|sil|mcl|mnq)\s*\$?(\d+)(?:\$|\b)', text, re.IGNORECASE)
    if not match:
        return ""
    
    symbol = match.group(1).upper()
    target = int(match.group(2))
    
    if symbol not in CONTRACT_MULTIPLIERS:
        return ""
        
    multiplier = CONTRACT_MULTIPLIERS[symbol]
    points = target / multiplier
    
    return f"🎯 To make *${target:,}* trading *{symbol}*, you need to capture *{points:,.2f}* points."

def _get_last_update_id() -> int:

    """Read the last processed Telegram update ID."""
    try:
        if os.path.exists(LAST_UPDATE_FILE):
            with open(LAST_UPDATE_FILE, "r") as f:
                val = f.read().strip()
                if val:
                    return int(val)
    except (ValueError, IOError) as e:
        print(f"[BotCmd] ⚠️ Error reading last_update_id: {e}")
    return 0


def _save_last_update_id(update_id: int):
    """Save the last processed Telegram update ID."""
    try:
        with open(LAST_UPDATE_FILE, "w") as f:
            f.write(str(update_id))
        print(f"[BotCmd] 💾 Saved last_update_id: {update_id}")
    except IOError as e:
        print(f"[BotCmd] ❌ Failed to save last_update_id: {e}")

def _set_sleep_state(asleep: bool):
    """Update global state to pause/resume alerts."""
    state = {}
    if os.path.exists(config.STATE_FILE):
        try:
            with open(config.STATE_FILE, "r") as f:
                state = json.load(f)
        except Exception:
            pass
    
    state["is_sleeping"] = asleep
    
    try:
        with open(config.STATE_FILE, "w") as f:
            json.dump(state, f, indent=2)
        print(f"[BotCmd] Sleep state set to: {asleep}")
    except Exception as e:
        print(f"[BotCmd] ❌ Failed to write sleep state: {e}")

def _add_alarm(symbol: str, price: float):
    state = {}
    if os.path.exists(config.STATE_FILE):
        try:
            with open(config.STATE_FILE, "r") as f:
                state = json.load(f)
        except Exception: pass
    alarms = state.setdefault("price_alarms", {})
    if symbol not in alarms:
        alarms[symbol] = []
    if price not in alarms[symbol]:
        alarms[symbol].append(price)
    with open(config.STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)

def _get_alarms() -> dict:
    if os.path.exists(config.STATE_FILE):
        try:
            with open(config.STATE_FILE, "r") as f:
                return json.load(f).get("price_alarms", {})
        except Exception: pass
    return {}

def _clear_alarms():
    state = {}
    if os.path.exists(config.STATE_FILE):
        try:
            with open(config.STATE_FILE, "r") as f:
                state = json.load(f)
        except Exception: pass
    state["price_alarms"] = {}
    with open(config.STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def _build_status_message() -> str:
    """Fetch live prices and BB levels for all instruments."""
    now_ist = datetime.now(IST).strftime("%d-%b-%Y %I:%M %p IST")
    lines = ["📊 *Live Status Report*", f"🕐 {now_ist}\n"]

    # Check sleep state
    if os.path.exists(config.STATE_FILE):
        try:
            with open(config.STATE_FILE, "r") as f:
                state = json.load(f)
                if state.get("is_sleeping", False):
                    lines.append("💤 *ALERTS PAUSED* (Bot is Sleeping)")
                    lines.append("_Use /wakeup to resume automated alerts_\n")
        except Exception:
            pass

    for symbol, info in config.INSTRUMENTS.items():
        name = info["name"]
        try:
            df = fetch_candles(info["ticker"], info.get("fallback_ticker"))

            if df is None or df.empty:
                lines.append(f"❌ *{name} ({symbol})*: Data unavailable\n")
                continue

            df = compute_bollinger_bands(df)
            last = df.iloc[-1]

            close = float(last["Close"])
            upper = float(last["BB_Upper"]) if not pd.isna(last.get("BB_Upper")) else 0
            lower = float(last["BB_Lower"]) if not pd.isna(last.get("BB_Lower")) else 0
            mid = float(last["BB_Mid"]) if not pd.isna(last.get("BB_Mid")) else 0

            # Determine position relative to bands
            if upper == 0 or lower == 0:
                position = "⚠️ BB not ready"
            elif close > upper:
                position = "🔴 ABOVE Upper Band"
            elif close < lower:
                position = "🟢 BELOW Lower Band"
            elif close > mid:
                position = "↗️ Above midline"
            else:
                position = "↘️ Below midline"

            # Calculate % distance from nearest band
            band_width = upper - lower
            if band_width > 0:
                dist_upper = ((upper - close) / band_width) * 100
                dist_lower = ((close - lower) / band_width) * 100
            else:
                dist_upper = dist_lower = 0

            lines.append(
                f"*{name} ({symbol})*\n"
                f"  💰 Close: ${close:,.2f}\n"
                f"  📈 Upper BB: ${upper:,.2f} ({dist_upper:.0f}% away)\n"
                f"  📉 Lower BB: ${lower:,.2f} ({dist_lower:.0f}% away)\n"
                f"  📍 Position: {position}\n"
            )
        except Exception as e:
            lines.append(f"❌ *{name} ({symbol})*: Error - {str(e)[:40]}\n")
            print(f"[BotCmd] ❌ Error building status for {symbol}: {e}")

    lines.append("_Use /status anytime to check again_")
    return "\n".join(lines)


def _send_reply(chat_id, text: str) -> bool:
    """Send a Telegram reply. Returns True if sent."""
    url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown",
    }
    try:
        r = requests.post(url, json=payload, timeout=15)
        if r.status_code == 200:
            print(f"[BotCmd] ✅ Status reply sent to chat {chat_id}")
            return True
        else:
            print(f"[BotCmd] ❌ Reply failed ({r.status_code}): {r.text[:200]}")
            return False
    except Exception as e:
        print(f"[BotCmd] ❌ Error sending reply: {e}")
        return False


def process_commands():
    """
    Check for new /status commands from Telegram and respond.
    Uses long-polling offset to avoid re-processing old messages.
    """
    if not config.TELEGRAM_BOT_TOKEN:
        print("[BotCmd] ⚠️ No TELEGRAM_BOT_TOKEN set, skipping commands.")
        return

    last_id = _get_last_update_id()
    print(f"[BotCmd] 📡 Polling for commands (offset={last_id + 1})...")

    url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/getUpdates"
    params = {"offset": last_id + 1, "timeout": 0, "limit": 25}

    try:
        r = requests.get(url, params=params, timeout=15)
        if r.status_code != 200:
            print(f"[BotCmd] ⚠️ getUpdates failed ({r.status_code}): {r.text[:200]}")
            return

        data = r.json()
        if not data.get("ok"):
            print(f"[BotCmd] ⚠️ getUpdates response not OK: {data}")
            return

        results = data.get("result", [])
        print(f"[BotCmd] 📬 Received {len(results)} update(s)")

        if not results:
            return

        commands_found = 0
        authorized_chat_id = config.TELEGRAM_CHAT_ID
        for update in results:
            update_id = update.get("update_id", 0)
            message = update.get("message", {})
            text = message.get("text", "").strip().lower()
            chat_id = message.get("chat", {}).get("id")

            print(f"[BotCmd] Processing update {update_id}: text='{text}' chat={chat_id}")

            # Security: Only accept commands from the authorized chat
            if chat_id and authorized_chat_id and str(chat_id) != str(authorized_chat_id):
                print(f"[BotCmd] ⛔ Unauthorized chat {chat_id} — ignoring command.")
                if update_id > last_id:
                    last_id = update_id
                continue

            if chat_id and text in ["/status", "/s", "status"]:
                print(f"[BotCmd] 📩 /status command from chat {chat_id}")
                commands_found += 1
                try:
                    status_msg = _build_status_message()
                    _send_reply(chat_id, status_msg)
                except Exception as e:
                    print(f"[BotCmd] ❌ Error handling /status: {e}")
                    traceback.print_exc()
                    # Send a simple error reply so the user knows something happened
                    _send_reply(chat_id, "⚠️ Error generating status report. Will retry on next cycle.")

            elif chat_id and text in ["/sleep", "sleep"]:
                print(f"[BotCmd] 📩 /sleep command from chat {chat_id}")
                commands_found += 1
                _set_sleep_state(True)
                _send_reply(chat_id, "💤 *Bot is now SLEEPING.*\n\nI will continue tracking prices in the background, but I will **NOT** send any signal alerts. \n\nSend `/wakeup` to resume alerts.")

            elif chat_id and text in ["/wakeup", "wakeup"]:
                print(f"[BotCmd] 📩 /wakeup command from chat {chat_id}")
                commands_found += 1
                _set_sleep_state(False)
                _send_reply(chat_id, "☀️ *Bot is AWAKE!*\n\nI will now resume sending signal alerts for all instruments.")

            elif chat_id and (text.startswith("/alarm ") or text.startswith("alarm ")):
                print(f"[BotCmd] 📩 /alarm command from chat {chat_id}")
                commands_found += 1
                parts = text.split()
                if len(parts) >= 3:
                    sym = parts[1].upper()
                    if sym not in config.INSTRUMENTS:
                        _send_reply(chat_id, f"⚠️ Unknown symbol `{sym}`. Valid options: {', '.join(config.INSTRUMENTS.keys())}")
                    else:
                        try:
                            price = float(parts[2])
                            _add_alarm(sym, price)
                            _send_reply(chat_id, f"⏰ *Alarm Set!*\n\nI will alert you instantly when {sym} crosses `${price:,.2f}`.")
                        except ValueError:
                            _send_reply(chat_id, "⚠️ Invalid price format. Use: `/alarm SIL 68.50`")
                else:
                    _send_reply(chat_id, "⚠️ Usage: `/alarm <SYMBOL> <PRICE>`\nExample: `/alarm MGC 4400.50`")

            elif chat_id and text in ["/alarms", "alarms"]:
                print(f"[BotCmd] 📩 /alarms command from chat {chat_id}")
                commands_found += 1
                alarms = _get_alarms()
                if not alarms or all(len(v) == 0 for v in alarms.values()):
                    _send_reply(chat_id, "ℹ️ You have no active price alarms. Set one with `/alarm <SYMBOL> <PRICE>`")
                else:
                    lines = ["⏰ *Active Price Alarms*"]
                    for sym, prices in alarms.items():
                        if prices:
                            lines.append(f"• *{sym}*: " + ", ".join(f"${p:,.2f}" for p in prices))
                    lines.append("\n_Use /clearalarms to remove all._")
                    _send_reply(chat_id, "\n".join(lines))

            elif chat_id and text in ["/clearalarms", "clearalarms"]:
                print(f"[BotCmd] 📩 /clearalarms command from chat {chat_id}")
                commands_found += 1
                _clear_alarms()
                _send_reply(chat_id, "🗑️ All custom price alarms have been cleared.")

            elif chat_id and (text.startswith("/chart") or text.startswith("/c ") or text == "/c"):
                print(f"[BotCmd] 📩 /chart command from chat {chat_id}")
                commands_found += 1
                parts = text.split()
                
                # Determine which instruments to chart
                if len(parts) >= 2:
                    sym = parts[1].upper()
                    if sym not in config.INSTRUMENTS:
                        _send_reply(chat_id, f"⚠️ Unknown symbol `{sym}`. Valid: {', '.join(config.INSTRUMENTS.keys())}")
                    else:
                        symbols_to_chart = {sym: config.INSTRUMENTS[sym]}
                else:
                    symbols_to_chart = config.INSTRUMENTS
                
                _send_reply(chat_id, f"📊 Generating {'chart' if len(symbols_to_chart) == 1 else 'charts'}...")
                
                for sym, info in symbols_to_chart.items():
                    try:
                        df = fetch_candles(info["ticker"], info.get("fallback_ticker"))
                        if df is None:
                            _send_reply(chat_id, f"❌ No data for {sym}")
                            continue
                        chart_path = chart_generator.generate_status_chart(df, sym, info["name"])
                        if chart_path:
                            send_photo(chart_path, f"📊 {info['name']} ({sym}) — Live BB Status")
                        else:
                            _send_reply(chat_id, f"❌ Chart generation failed for {sym}")
                    except Exception as e:
                        print(f"[BotCmd] ❌ Chart error for {sym}: {e}")
                        _send_reply(chat_id, f"❌ Error generating chart for {sym}: {str(e)[:50]}")

            elif chat_id and text in ["/stats", "stats"]:
                print(f"[BotCmd] 📩 /stats command from chat {chat_id}")
                commands_found += 1
                state = {}
                if os.path.exists(config.STATE_FILE):
                    try:
                        with open(config.STATE_FILE, "r") as f:
                            state = json.load(f)
                    except Exception: pass
                stats_msg = signal_tracker.get_stats(state)
                _send_reply(chat_id, stats_msg)

            elif chat_id and text in ["/reset", "reset"]:
                print(f"[BotCmd] 📩 /reset command from chat {chat_id}")
                commands_found += 1
                state = {}
                if os.path.exists(config.STATE_FILE):
                    try:
                        with open(config.STATE_FILE, "r") as f:
                            state = json.load(f)
                    except Exception: pass
                
                # Keep important user settings, wipe trading state (triggers, recent history)
                new_state = {}
                if "is_sleeping" in state: new_state["is_sleeping"] = state["is_sleeping"]
                if "price_alarms" in state: new_state["price_alarms"] = state["price_alarms"]
                if "last_market_status" in state: new_state["last_market_status"] = state["last_market_status"]
                
                try:
                    with open(config.STATE_FILE, "w") as f:
                        json.dump(new_state, f, indent=2)
                    _send_reply(chat_id, "🔄 *System Reset Complete!*\n\nAll active trade triggers and recent alert deduplication history have been wiped. The bot will evaluate the market completely fresh on the next run.")
                except Exception as e:
                    _send_reply(chat_id, f"❌ Failed to reset state: {str(e)}")

            elif chat_id and text in ["/list", "list"]:
                print(f"[BotCmd] 📩 /list command from chat {chat_id}")
                commands_found += 1
                try:
                    msg = _build_list_message()
                    _send_reply(chat_id, msg)
                except Exception as e:
                    print(f"[BotCmd] ❌ Error handling /list: {e}")
                    _send_reply(chat_id, "⚠️ Error generating target list.")

            else:
                # Fallback: check if the user is asking for a dynamic target (e.g. mgc 2000$)
                dynamic_resp = _parse_dynamic_target(text)
                if dynamic_resp and chat_id:
                    print(f"[BotCmd] 📩 Dynamic Target command from chat {chat_id} ('{text}')")
                    commands_found += 1
                    _send_reply(chat_id, dynamic_resp)

            # Always update the offset to acknowledge ALL messages
            if update_id > last_id:
                last_id = update_id

        # ALWAYS save the offset, even if no commands were found
        # This prevents re-processing old non-command messages
        _save_last_update_id(last_id)
        print(f"[BotCmd] ✅ Done. {commands_found} command(s) processed, offset saved as {last_id}")

    except Exception as e:
        print(f"[BotCmd] ❌ Fatal error in process_commands: {e}")
        traceback.print_exc()
        # Still try to save any offset we managed to get
        if last_id > _get_last_update_id():
            _save_last_update_id(last_id)
