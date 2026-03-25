"""
Fetches 15-minute OHLC candle data from Yahoo Finance (COMEX/NYMEX).
Same exchange data that TradeSea uses via Rithmic.
"""
import yfinance as yf
import pandas as pd
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import time
import config


def is_market_open() -> bool:
    """
    Check if CME Globex is likely open.
    Globex hours: Sunday 5:00 PM CT – Friday 4:00 PM CT
    with a daily maintenance break 4:00 PM – 5:00 PM CT (Mon-Thu).
    """
    ct = datetime.now(ZoneInfo("America/Chicago"))
    weekday = ct.weekday()  # Mon=0 ... Sun=6
    hour = ct.hour

    # Saturday: market closed all day
    if weekday == 5:
        return False
    # Sunday: opens at 5 PM CT
    if weekday == 6:
        return hour >= 17
    # Friday: closes at 4 PM CT
    if weekday == 4:
        return hour < 16
    # Mon-Thu: closed during 4 PM - 5 PM CT maintenance window
    if 0 <= weekday <= 3:
        if hour == 16:
            return False
        return True

    return True


def fetch_candles(ticker: str, fallback_ticker: str | None = None) -> pd.DataFrame | None:
    """
    Fetch recent 15-minute candles for a given ticker.
    Returns DataFrame with columns: Open, High, Low, Close, Volume
    or None if fetch fails. Retries up to 3 times on failure.
    """
    tickers_to_try = [t for t in [ticker, fallback_ticker] if t is not None]

    for t in tickers_to_try:
        for attempt in range(1, 4):  # 3 retries
            try:
                data = yf.download(
                    t,
                    period=config.LOOKBACK_PERIOD,
                    interval=config.INTERVAL,
                    progress=False,
                    auto_adjust=True,
                )
                if data is not None and not data.empty and len(data) >= config.BB_PERIOD:
                    # Flatten multi-level columns if present
                    if isinstance(data.columns, pd.MultiIndex):
                        data.columns = data.columns.get_level_values(0)

                    # Drop rows with NaN in critical columns
                    data = data.dropna(subset=["Open", "High", "Low", "Close"])

                    if len(data) >= config.BB_PERIOD:
                        return data

                    print(f"[DataFetcher] {t}: Not enough clean rows ({len(data)}/{config.BB_PERIOD})")
                else:
                    print(f"[DataFetcher] {t}: Empty or insufficient data (attempt {attempt}/3)")

            except Exception as e:
                print(f"[DataFetcher] Error fetching {t} (attempt {attempt}/3): {e}")

            if attempt < 3:
                time.sleep(2)  # Brief pause before retry

    return None


def fetch_all_instruments() -> dict[str, pd.DataFrame]:
    """
    Fetch candles for all configured instruments.
    Returns dict: symbol -> DataFrame
    """
    results = {}
    for symbol, info in config.INSTRUMENTS.items():
        df = fetch_candles(info["ticker"], info.get("fallback_ticker"))
        if df is not None:
            results[symbol] = df
        else:
            print(f"[DataFetcher] WARNING: No data for {symbol} ({info['ticker']})")
    return results
