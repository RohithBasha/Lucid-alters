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

import config
import pandas as pd
from data_fetcher import fetch_candles
from bollinger import compute_bollinger_bands

IST = ZoneInfo("Asia/Kolkata")
LAST_UPDATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "last_update_id.txt")


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


def _build_status_message() -> str:
    """Fetch live prices and BB levels for all instruments."""
    now_ist = datetime.now(IST).strftime("%d-%b-%Y %I:%M %p IST")
    lines = ["📊 *Live Status Report*", f"🕐 {now_ist}\n"]

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
        for update in results:
            update_id = update.get("update_id", 0)
            message = update.get("message", {})
            text = message.get("text", "").strip().lower()
            chat_id = message.get("chat", {}).get("id")

            print(f"[BotCmd] Processing update {update_id}: text='{text}' chat={chat_id}")

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
