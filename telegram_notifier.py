"""
Telegram Bot API integration for sending alerts.
Completely free, unlimited messages.
"""
import requests
import config


def send_alert(signal: dict, symbol: str) -> bool:
    """
    Send a Telegram message for a detected Bollinger Band signal.
    Returns True if sent successfully.
    """
    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_ID:
        print("[Telegram] ERROR: Bot token or chat ID not configured.")
        return False

    instrument = config.INSTRUMENTS.get(symbol, {})
    name = instrument.get("name", symbol)

    # Build the message
    emoji = signal["emoji"]
    label = signal["label"]

    if "CROSS" in signal["type"]:
        price_line = f"💰 Close: ${signal['close']:,.2f}"
    else:
        price_line = f"💰 Price: ${signal['close']:,.2f} | High: ${signal['high']:,.2f} | Low: ${signal['low']:,.2f}"

    message = (
        f"{emoji} *{name} ({symbol})* — {label}\n"
        f"\n"
        f"{price_line}\n"
        f"📊 Upper BB: ${signal['upper_bb']:,.2f} | Lower BB: ${signal['lower_bb']:,.2f}\n"
        f"⏱️ 15m candle | {signal['timestamp']}\n"
        f"📍 Trade on TradeSea"
    )

    url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": config.TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown",
    }

    try:
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code == 200:
            print(f"[Telegram] ✅ Alert sent: {symbol} — {label}")
            return True
        else:
            print(f"[Telegram] ❌ Failed ({response.status_code}): {response.text}")
            return False
    except Exception as e:
        print(f"[Telegram] ❌ Error: {e}")
        return False
