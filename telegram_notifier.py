"""
Telegram Bot API integration for sending alerts.
Completely free, unlimited messages. Retries on transient failures.
"""
import requests
import time
from datetime import datetime
from zoneinfo import ZoneInfo
import config

IST = ZoneInfo("Asia/Kolkata")


def send_alert(signal: dict, symbol: str) -> bool:
    """
    Send a Telegram message for a detected Bollinger Band signal.
    Returns True if sent successfully. Retries up to 3 times.
    """
    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_ID:
        print("[Telegram] ERROR: Bot token or chat ID not configured.")
        return False

    instrument = config.INSTRUMENTS.get(symbol, {})
    name = instrument.get("name", symbol)

    # Build the message
    emoji = signal["emoji"]
    label = signal["label"]

    # Convert timestamp to IST
    try:
        ts = datetime.fromisoformat(str(signal["timestamp"]))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=ZoneInfo("UTC"))
        ist_time = ts.astimezone(IST).strftime("%d-%b-%Y %I:%M %p IST")
    except Exception:
        ist_time = str(signal.get("timestamp", "N/A"))

    # Build price line based on signal type
    if "PRIORITY" in signal.get("type", ""):
        price_line = (
            f"💰 Open: ${signal.get('close', 0):,.2f} | High: ${signal.get('high', 0):,.2f}\n"
            f"💰 Low: ${signal.get('low', 0):,.2f} | Close: ${signal.get('close', 0):,.2f}"
        )
    elif "CROSS" in signal.get("type", ""):
        price_line = f"💰 Close: ${signal.get('close', 0):,.2f}"
    else:
        price_line = f"💰 Price: ${signal.get('close', 0):,.2f} | High: ${signal.get('high', 0):,.2f} | Low: ${signal.get('low', 0):,.2f}"

    message = (
        f"{emoji} *{name} ({symbol})* — {label}\n"
        f"\n"
        f"{price_line}\n"
        f"📊 Upper BB: ${signal.get('upper_bb', 0):,.2f} | Lower BB: ${signal.get('lower_bb', 0):,.2f}\n"
        f"⏱️ 15m candle | {ist_time}\n"
        f"📍 Trade on TradeSea"
    )

    url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": config.TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown",
    }

    for attempt in range(1, 4):  # 3 retries
        try:
            response = requests.post(url, json=payload, timeout=10)
            if response.status_code == 200:
                print(f"[Telegram] ✅ Alert sent: {symbol} — {label}")
                return True
            elif response.status_code == 429:
                # Rate limited — wait and retry
                retry_after = int(response.headers.get("Retry-After", 5))
                print(f"[Telegram] ⏳ Rate limited, waiting {retry_after}s...")
                time.sleep(retry_after)
            else:
                print(f"[Telegram] ❌ Failed ({response.status_code}): {response.text}")
                return False
        except requests.exceptions.Timeout:
            print(f"[Telegram] ⏳ Timeout (attempt {attempt}/3)")
            time.sleep(2)
        except requests.exceptions.ConnectionError:
            print(f"[Telegram] ⏳ Connection error (attempt {attempt}/3)")
            time.sleep(2)
        except Exception as e:
            print(f"[Telegram] ❌ Error: {e}")
            return False

    print(f"[Telegram] ❌ Failed after 3 retries: {symbol} — {label}")
    return False


def send_photo(image_path: str, caption: str = "") -> bool:
    """Send a photo to Telegram. Returns True if sent successfully."""
    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_ID:
        return False

    url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendPhoto"

    for attempt in range(1, 4):
        try:
            with open(image_path, "rb") as photo:
                payload = {
                    "chat_id": config.TELEGRAM_CHAT_ID,
                    "caption": caption[:1024],  # Telegram caption limit
                    "parse_mode": "Markdown",
                }
                files = {"photo": photo}
                response = requests.post(url, data=payload, files=files, timeout=15)

            if response.status_code == 200:
                print(f"[Telegram] ✅ Chart image sent")
                return True
            elif response.status_code == 429:
                retry_after = int(response.headers.get("Retry-After", 5))
                time.sleep(retry_after)
            else:
                print(f"[Telegram] ❌ Photo failed ({response.status_code}): {response.text}")
                return False
        except requests.exceptions.Timeout:
            print(f"[Telegram] ⏳ Photo timeout (attempt {attempt}/3)")
            time.sleep(2)
        except Exception as e:
            print(f"[Telegram] ❌ Photo error: {e}")
            return False

    return False
