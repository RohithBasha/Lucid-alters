"""
Bollinger Band calculation and signal detection.
Detects two signal types: Cross (close beyond BB) and Priority (full candle outside BB).
Also checks for reversal confirmations on active trigger candles.
"""
import pandas as pd
import config


def compute_bollinger_bands(df: pd.DataFrame) -> pd.DataFrame:
    """
    Compute Bollinger Bands on the Close price.
    Adds columns: BB_Mid, BB_Upper, BB_Lower, BB_Width
    """
    df = df.copy()
    df["BB_Mid"] = df["Close"].rolling(window=config.BB_PERIOD).mean()
    df["BB_Std"] = df["Close"].rolling(window=config.BB_PERIOD).std()
    df["BB_Upper"] = df["BB_Mid"] + (config.BB_STD_DEV * df["BB_Std"])
    df["BB_Lower"] = df["BB_Mid"] - (config.BB_STD_DEV * df["BB_Std"])
    df["BB_Width"] = df["BB_Upper"] - df["BB_Lower"]
    return df


def detect_signals(df: pd.DataFrame) -> list[dict]:
    """
    Check the LAST CLOSED candle for cross/priority signals.
    Returns a list of signal dicts (can be 0, 1, or 2 signals).

    Signal types:
    - CROSS_UPPER:    Close > Upper Band (candle closed above band)
    - CROSS_LOWER:    Close < Lower Band (candle closed below band)
    - PRIORITY_UPPER: Entire candle above upper band (Low > Upper Band — no wick contact)
    - PRIORITY_LOWER: Entire candle below lower band (High < Lower Band — no wick contact)

    Note: Priority is a subset of Cross. If Priority fires, Cross does NOT also fire
    (one signal per band side, the strongest one wins).
    """
    if df is None or df.empty:
        return []

    df = compute_bollinger_bands(df)

    last = df.iloc[-1]

    if pd.isna(last.get("BB_Upper")) or pd.isna(last.get("BB_Lower")):
        return []

    signals = []
    close = float(last["Close"])
    high = float(last["High"])
    low = float(last["Low"])
    upper = float(last["BB_Upper"])
    lower = float(last["BB_Lower"])
    mid = float(last["BB_Mid"])
    timestamp = df.index[-1]

    candle_data = {
        "close": close,
        "high": high,
        "low": low,
        "upper_bb": round(upper, 2),
        "lower_bb": round(lower, 2),
        "mid_bb": round(mid, 2),
        "timestamp": str(timestamp),
    }

    # ── Upper Band ──
    if low > upper:
        # PRIORITY: Entire candle is ABOVE the upper band (no wick contact at all)
        signals.append({
            "type": "PRIORITY_UPPER",
            "emoji": "🚨🔴",
            "label": "⚠️ PRIORITY: Full candle ABOVE Upper Band!",
            **candle_data,
        })
    elif close > upper:
        # CROSS: close is above upper band (but wick dipped inside)
        signals.append({
            "type": "CROSS_UPPER",
            "emoji": "🔴",
            "label": "Crossed Upper Band!",
            **candle_data,
        })

    # ── Lower Band ──
    if high < lower:
        # PRIORITY: Entire candle is BELOW the lower band (no wick contact at all)
        signals.append({
            "type": "PRIORITY_LOWER",
            "emoji": "🚨🟢",
            "label": "⚠️ PRIORITY: Full candle BELOW Lower Band!",
            **candle_data,
        })
    elif close < lower:
        # CROSS: close is below lower band (but wick reached inside)
        signals.append({
            "type": "CROSS_LOWER",
            "emoji": "🟢",
            "label": "Crossed Lower Band!",
            **candle_data,
        })

    return signals


def check_reversal(df: pd.DataFrame, trigger_info: dict) -> tuple[list[dict], bool]:
    """
    Check candles after the trigger for reversal signals.

    For PRIORITY_UPPER trigger: check if any candle's Low < trigger Low (bearish reversal)
    For PRIORITY_LOWER trigger: check if any candle's High > trigger High (bullish reversal)

    Returns:
        (signals_list, expired_bool)
        - signals: list of REVERSAL_BREAK / REVERSAL_CLOSE signal dicts
        - expired: True if the 4-candle buffer has elapsed with no reversal
    """
    if df is None or df.empty:
        return [], True

    trigger_type = trigger_info["type"]
    trigger_ts_str = trigger_info["trigger_timestamp"]
    trigger_low = trigger_info["trigger_low"]
    trigger_high = trigger_info["trigger_high"]

    last = df.iloc[-1]
    current_ts = str(df.index[-1])

    # Don't check the trigger candle itself
    if current_ts == trigger_ts_str:
        return [], False

    # Check if within 4-candle buffer (60 minutes for 15-min candles)
    try:
        trigger_dt = pd.Timestamp(trigger_ts_str)
        current_dt = df.index[-1]
        elapsed_minutes = (current_dt - trigger_dt).total_seconds() / 60
        if elapsed_minutes > 60:  # Beyond 4 candles
            return [], True  # expired
    except Exception:
        return [], True

    # Compute BB for context in signal data
    df_bb = compute_bollinger_bands(df)
    last_bb = df_bb.iloc[-1]
    upper_bb = float(last_bb["BB_Upper"]) if not pd.isna(last_bb.get("BB_Upper")) else 0
    lower_bb = float(last_bb["BB_Lower"]) if not pd.isna(last_bb.get("BB_Lower")) else 0
    mid_bb = float(last_bb["BB_Mid"]) if not pd.isna(last_bb.get("BB_Mid")) else 0

    close = float(last["Close"])
    high = float(last["High"])
    low = float(last["Low"])

    candle_data = {
        "close": close,
        "high": high,
        "low": low,
        "upper_bb": round(upper_bb, 2),
        "lower_bb": round(lower_bb, 2),
        "mid_bb": round(mid_bb, 2),
        "timestamp": current_ts,
        "trigger_timestamp": trigger_ts_str,
    }

    signals = []

    if "UPPER" in trigger_type:
        # Bearish reversal: Price must come BACK INTO the bands
        # Conditions: (1) Low breaks below trigger Low AND (2) Low is below the Upper BB
        # This prevents false signals from candle-to-candle noise when price is still above BB
        if low < trigger_low and low < upper_bb:
            signals.append({
                "type": "REVERSAL_BREAK_UPPER",
                "emoji": "🔻",
                "label": "Reversal Break! Low broke below Trigger Low & Upper BB",
                "trigger_level": trigger_low,
                **candle_data,
            })
        # Close-based confirmation: Close must be below trigger Low AND below Upper BB
        if close < trigger_low and close < upper_bb:
            signals.append({
                "type": "REVERSAL_CLOSE_UPPER",
                "emoji": "✅🔻",
                "label": "Reversal Confirmed! Close below Trigger Low & Upper BB",
                "trigger_level": trigger_low,
                **candle_data,
            })

    elif "LOWER" in trigger_type:
        # Bullish reversal: Price must come BACK INTO the bands
        # Conditions: (1) High breaks above trigger High AND (2) High is above the Lower BB
        if high > trigger_high and high > lower_bb:
            signals.append({
                "type": "REVERSAL_BREAK_LOWER",
                "emoji": "🔺",
                "label": "Reversal Break! High broke above Trigger High & Lower BB",
                "trigger_level": trigger_high,
                **candle_data,
            })
        # Close-based confirmation: Close must be above trigger High AND above Lower BB
        if close > trigger_high and close > lower_bb:
            signals.append({
                "type": "REVERSAL_CLOSE_LOWER",
                "emoji": "✅🔺",
                "label": "Reversal Confirmed! Close above Trigger High & Lower BB",
                "trigger_level": trigger_high,
                **candle_data,
            })

    return signals, False
