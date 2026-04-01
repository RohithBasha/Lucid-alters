"""
Signal Tracker — Tracks PRIORITY signals and scores Win/Loss outcomes.

Win/Loss logic:
- PRIORITY_UPPER (Short setup):
  SL = High of trigger candle
  Risk = High - Close
  Target = Close - (1.5 × Risk)
  WIN = price hits target | LOSS = price hits SL

- PRIORITY_LOWER (Long setup):
  SL = Low of trigger candle
  Risk = Close - Low
  Target = Close + (1.5 × Risk)
  WIN = price hits target | LOSS = price hits SL
"""
import config
from datetime import datetime
from zoneinfo import ZoneInfo


def track_new_signal(state: dict, symbol: str, signal: dict):
    """
    Start tracking a new PRIORITY signal for win/loss evaluation.
    Called when a PRIORITY alert is successfully sent.
    """
    if "tracked_signals" not in state:
        state["tracked_signals"] = []

    sig_type = signal["type"]
    close = signal["close"]
    high = signal["high"]
    low = signal["low"]

    # Calculate SL and Target based on direction
    if "UPPER" in sig_type:
        # Short setup: fade the upper band breakout
        sl = high
        risk = high - close
        target = close - (config.RISK_REWARD_RATIO * risk)
        direction = "SHORT"
    elif "LOWER" in sig_type:
        # Long setup: fade the lower band breakout
        sl = low
        risk = close - low
        target = close + (config.RISK_REWARD_RATIO * risk)
        direction = "LONG"
    else:
        return  # Not a PRIORITY signal we track

    if risk <= 0:
        print(f"[Tracker] Skipping {symbol} — zero or negative risk ({risk})")
        return

    entry = {
        "symbol": symbol,
        "type": sig_type,
        "direction": direction,
        "entry_price": round(close, 2),
        "sl": round(sl, 2),
        "target": round(target, 2),
        "risk": round(risk, 2),
        "reward": round(config.RISK_REWARD_RATIO * risk, 2),
        "entry_timestamp": signal["timestamp"],
        "candles_elapsed": 0,
        "status": "TRACKING",
    }

    # Avoid duplicate tracking for the same signal
    for existing in state["tracked_signals"]:
        if existing["symbol"] == symbol and existing["entry_timestamp"] == signal["timestamp"]:
            return

    state["tracked_signals"].append(entry)
    print(f"[Tracker] 🎯 Now tracking {symbol} {direction} — Entry: ${close:,.2f} | SL: ${sl:,.2f} | Target: ${target:,.2f}")


def update_tracking(state: dict, data: dict[str, 'pd.DataFrame']) -> list[dict]:
    """
    Check all active tracked signals against current price data.
    Returns a list of completed result dicts for notification.
    """
    if "tracked_signals" not in state:
        state["tracked_signals"] = []
    if "signal_results" not in state:
        state["signal_results"] = []

    completed = []
    still_active = []

    for entry in state["tracked_signals"]:
        symbol = entry["symbol"]
        df = data.get(symbol)

        if df is None or df.empty:
            still_active.append(entry)
            continue

        entry["candles_elapsed"] += 1
        last = df.iloc[-1]
        current_high = float(last["High"])
        current_low = float(last["Low"])
        current_close = float(last["Close"])

        result = None

        if entry["direction"] == "SHORT":
            # Check SL hit first (conservative — SL takes priority)
            if current_high >= entry["sl"]:
                result = "LOSS"
                exit_price = entry["sl"]
                pnl = -(entry["risk"])
            elif current_low <= entry["target"]:
                result = "WIN"
                exit_price = entry["target"]
                pnl = entry["reward"]
        elif entry["direction"] == "LONG":
            if current_low <= entry["sl"]:
                result = "LOSS"
                exit_price = entry["sl"]
                pnl = -(entry["risk"])
            elif current_high >= entry["target"]:
                result = "WIN"
                exit_price = entry["target"]
                pnl = entry["reward"]

        if result:
            outcome = {
                "symbol": symbol,
                "type": entry["type"],
                "direction": entry["direction"],
                "entry_price": entry["entry_price"],
                "sl": entry["sl"],
                "target": entry["target"],
                "exit_price": round(exit_price, 2),
                "result": result,
                "pnl_points": round(pnl, 2),
                "candles_to_resolve": entry["candles_elapsed"],
                "entry_timestamp": entry["entry_timestamp"],
                "resolved_at": datetime.now(ZoneInfo("UTC")).isoformat(),
            }
            state["signal_results"].append(outcome)
            completed.append(outcome)
            print(f"[Tracker] {'✅' if result == 'WIN' else '❌'} {symbol} {entry['direction']} → {result} (${pnl:+,.2f} pts in {entry['candles_elapsed']} candles)")

        elif entry["candles_elapsed"] >= config.TRACKING_MAX_CANDLES:
            # Expired — neither SL nor target hit
            pnl = current_close - entry["entry_price"]
            if entry["direction"] == "SHORT":
                pnl = entry["entry_price"] - current_close

            outcome = {
                "symbol": symbol,
                "type": entry["type"],
                "direction": entry["direction"],
                "entry_price": entry["entry_price"],
                "sl": entry["sl"],
                "target": entry["target"],
                "exit_price": round(current_close, 2),
                "result": "EXPIRED",
                "pnl_points": round(pnl, 2),
                "candles_to_resolve": entry["candles_elapsed"],
                "entry_timestamp": entry["entry_timestamp"],
                "resolved_at": datetime.now(ZoneInfo("UTC")).isoformat(),
            }
            state["signal_results"].append(outcome)
            completed.append(outcome)
            print(f"[Tracker] ⏳ {symbol} {entry['direction']} → EXPIRED (${pnl:+,.2f} pts, {entry['candles_elapsed']} candles)")

        else:
            still_active.append(entry)

    state["tracked_signals"] = still_active

    # Keep only the last 200 results to prevent file bloat
    if len(state["signal_results"]) > 200:
        state["signal_results"] = state["signal_results"][-150:]

    return completed


def get_stats(state: dict, days: int = 30) -> str:
    """
    Build a formatted stats message for the /stats command.
    Shows per-instrument win/loss/expired rates.
    """
    results = state.get("signal_results", [])

    if not results:
        return "📊 No tracked signals yet. Stats will appear after PRIORITY signals resolve."

    # Filter by recent days
    from datetime import timedelta
    cutoff = datetime.now(ZoneInfo("UTC")) - timedelta(days=days)
    recent = []
    for r in results:
        try:
            ts = datetime.fromisoformat(r["resolved_at"])
            if ts >= cutoff:
                recent.append(r)
        except (ValueError, KeyError):
            recent.append(r)  # Include if we can't parse date

    if not recent:
        return f"📊 No signals resolved in the last {days} days."

    # Aggregate by symbol
    stats = {}
    for r in recent:
        sym = r["symbol"]
        if sym not in stats:
            stats[sym] = {"wins": 0, "losses": 0, "expired": 0, "total_pnl": 0}
        if r["result"] == "WIN":
            stats[sym]["wins"] += 1
        elif r["result"] == "LOSS":
            stats[sym]["losses"] += 1
        else:
            stats[sym]["expired"] += 1
        stats[sym]["total_pnl"] += r.get("pnl_points", 0)

    # Build message
    lines = [f"📊 *Signal Scorecard (Last {days} Days)*\n"]

    total_w, total_l, total_e, total_pnl = 0, 0, 0, 0

    for sym in sorted(stats.keys()):
        s = stats[sym]
        total = s["wins"] + s["losses"] + s["expired"]
        decided = s["wins"] + s["losses"]
        hit_rate = (s["wins"] / decided * 100) if decided > 0 else 0
        total_w += s["wins"]
        total_l += s["losses"]
        total_e += s["expired"]
        total_pnl += s["total_pnl"]

        name = config.INSTRUMENTS.get(sym, {}).get("name", sym)
        lines.append(
            f"*{name} ({sym})*\n"
            f"  ✅ {s['wins']}W | ❌ {s['losses']}L | ⏳ {s['expired']}E\n"
            f"  📈 Hit Rate: {hit_rate:.0f}% | PnL: ${s['total_pnl']:+,.2f} pts\n"
        )

    # Overall
    overall_decided = total_w + total_l
    overall_rate = (total_w / overall_decided * 100) if overall_decided > 0 else 0
    lines.append(
        f"─────────────\n"
        f"*Overall:* {total_w}W / {total_l}L / {total_e}E ({overall_rate:.0f}% hit rate)\n"
        f"*Net PnL:* ${total_pnl:+,.2f} points\n"
        f"*R:R Ratio:* 1:{config.RISK_REWARD_RATIO}"
    )

    # Active tracking count
    active = len(state.get("tracked_signals", []))
    if active > 0:
        lines.append(f"\n🔄 _{active} signal(s) currently being tracked_")

    return "\n".join(lines)
