"""
Bollinger Band calculation and signal detection.
Detects three signal types: Touch, Cross, and Priority (full candle outside).
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
    Check the LAST CLOSED candle for touch/cross/priority signals.
    Returns a list of signal dicts (can be 0, 1, or 2 signals).

    Signal types:
    - TOUCH_UPPER:    High >= Upper Band AND Close <= Upper Band (wick touched)
    - TOUCH_LOWER:    Low <= Lower Band AND Close >= Lower Band (wick touched)
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
    elif high >= upper and close <= upper:
        # TOUCH: wick reached upper band but closed inside
        signals.append({
            "type": "TOUCH_UPPER",
            "emoji": "👆",
            "label": "Touched Upper Band",
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
    elif low <= lower and close >= lower:
        # TOUCH: wick reached lower band but closed inside
        signals.append({
            "type": "TOUCH_LOWER",
            "emoji": "👇",
            "label": "Touched Lower Band",
            **candle_data,
        })

    return signals
