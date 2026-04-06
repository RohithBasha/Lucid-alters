"""
Fetches 15-minute OHLC candle data from Yahoo Finance (COMEX/NYMEX).
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
        for interval in [config.INTERVAL, "5m"]:
            for attempt in range(1, 4):  # 3 retries per interval
                try:
                    data = yf.download(
                        t,
                        period=config.LOOKBACK_PERIOD,
                        interval=interval,
                        progress=False,
                        auto_adjust=True,
                    )
                    if data is not None and not data.empty and len(data) >= config.BB_PERIOD:
                        # Flatten multi-level columns if present
                        if isinstance(data.columns, pd.MultiIndex):
                            data.columns = data.columns.get_level_values(0)

                        if interval == "5m":
                            print(f"[DataFetcher] Data fallback triggered! Resampling 5m data to 15m for {t}")
                            try:
                                agg_dict = {'Open': 'first', 'High': 'max', 'Low': 'min', 'Close': 'last', 'Volume': 'sum'}
                                available_cols = {col: agg_dict[col] for col in agg_dict if col in data.columns}
                                data = data.resample("15min", closed='left', label='left').agg(available_cols).dropna()
                            except Exception as e:
                                print(f"[DataFetcher] Resampling error: {e}")

                        # Drop rows with NaN in critical columns
                        if all(c in data.columns for c in ["Open", "High", "Low", "Close"]):
                            data = data.dropna(subset=["Open", "High", "Low", "Close"])

                        if len(data) >= config.BB_PERIOD:
                            return data

                        print(f"[DataFetcher] {t}: Not enough clean rows ({len(data)}/{config.BB_PERIOD})")
                    else:
                        print(f"[DataFetcher] {t} [{interval}]: Empty or insufficient data (attempt {attempt}/3)")

                except Exception as e:
                    print(f"[DataFetcher] Error fetching {t} [{interval}] (attempt {attempt}/3): {e}")

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


def fetch_htf_candles(ticker: str, fallback_ticker: str | None = None) -> pd.DataFrame | None:
    """
    Fetch higher-timeframe (1h) candles for multi-TF analysis.
    Same retry logic as fetch_candles but uses HTF config.
    """
    tickers_to_try = [t for t in [ticker, fallback_ticker] if t is not None]

    for t in tickers_to_try:
        for attempt in range(1, 4):
            try:
                data = yf.download(
                    t,
                    period=config.HTF_LOOKBACK,
                    interval=config.HTF_INTERVAL,
                    progress=False,
                    auto_adjust=True,
                )
                if data is not None and not data.empty and len(data) >= config.BB_PERIOD:
                    if isinstance(data.columns, pd.MultiIndex):
                        data.columns = data.columns.get_level_values(0)
                    data = data.dropna(subset=["Open", "High", "Low", "Close"])
                    if len(data) >= config.BB_PERIOD:
                        return data
                else:
                    print(f"[DataFetcher] {t} (HTF): Empty or insufficient data (attempt {attempt}/3)")
            except Exception as e:
                print(f"[DataFetcher] Error fetching {t} HTF (attempt {attempt}/3): {e}")
            if attempt < 3:
                time.sleep(2)
    return None


def fetch_all_htf_instruments() -> dict[str, pd.DataFrame]:
    """Fetch 1h candles for all configured instruments."""
    results = {}
    for symbol, info in config.INSTRUMENTS.items():
        df = fetch_htf_candles(info["ticker"], info.get("fallback_ticker"))
        if df is not None:
            results[symbol] = df
        else:
            print(f"[DataFetcher] WARNING: No HTF data for {symbol}")
    return results
