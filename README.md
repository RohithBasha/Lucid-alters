# Commodity Bollinger Band Alert Tool

Sends **Telegram alerts** when Micro Gold (MGC), Micro Silver (SIL), or Micro Crude (MCL) 15-minute charts **touch or cross** Bollinger Bands (SMA 20, σ=1.5) on COMEX/NYMEX.

Runs **24/7 for free** on GitHub Actions — works even when your PC is off.

---

## Quick Setup (5 minutes)

### 1. Create a Telegram Bot

1. Open Telegram and search for **@BotFather**
2. Send `/newbot` and follow the prompts
3. Copy the **API token** (looks like `123456:ABC-DEF...`)

### 2. Get Your Chat ID

1. Start a chat with your new bot (send any message like "hi")
2. Open this URL in your browser (replace `YOUR_TOKEN`):
   ```
   https://api.telegram.org/botYOUR_TOKEN/getUpdates
   ```
3. Find `"chat":{"id":123456789}` — that number is your **chat ID**

### 3. Push to GitHub

```bash
cd commodity-bb-alerts
git init
git add .
git commit -m "Initial commit"
git remote add origin https://github.com/YOUR_USERNAME/commodity-bb-alerts.git
git branch -M main
git push -u origin main
```

### 4. Add Secrets to GitHub

1. Go to your repo → **Settings** → **Secrets and variables** → **Actions**
2. Add two secrets:
   - `TELEGRAM_BOT_TOKEN` → your bot token
   - `TELEGRAM_CHAT_ID` → your chat ID

### 5. Done! 🎉

The GitHub Actions workflow will automatically run every 15 minutes and send you Telegram alerts when any instrument touches or crosses its Bollinger Bands.

You can also trigger a manual run: **Actions** tab → **Check Bollinger Bands** → **Run workflow**

---

## Alert Types

| Alert | Condition | Example |
|---|---|---|
| 👆 Touch Upper | High ≥ Upper BB, Close ≤ Upper BB | Price wicked up to band |
| 👇 Touch Lower | Low ≤ Lower BB, Close ≥ Lower BB | Price wicked down to band |
| 🔴 Cross Upper | Close > Upper BB | Candle closed above band |
| 🟢 Cross Lower | Close < Lower BB | Candle closed below band |

Max **one alert per type per 15-min candle per instrument** (no spam).

---

## Configuration

Edit `config.py` to adjust:
- **BB_PERIOD**: SMA lookback (default: 20)
- **BB_STD_DEV**: Standard deviation multiplier (default: 1.5)
- **INSTRUMENTS**: Add/remove instruments

---

## Local Testing

```bash
pip install -r requirements.txt

# Set env vars
set TELEGRAM_BOT_TOKEN=your_token_here
set TELEGRAM_CHAT_ID=your_chat_id_here

python main.py
```

---

## Cost

**$0.** Everything is free: yfinance, Telegram Bot API, GitHub Actions.
