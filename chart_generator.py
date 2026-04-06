"""
BB Chart Generator — Creates candlestick + Bollinger Band charts as PNG images.
Sends the chart alongside Telegram alerts for visual context.
"""
import os
import tempfile
import matplotlib
matplotlib.use('Agg')  # Non-interactive backend for server/CI
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import config


def _clean_continuous_data(df: pd.DataFrame) -> pd.DataFrame:
    """
    Remove large time gaps from the data to prevent visual gaps in charts.
    Keeps the most recent continuous block that has enough candles for BB.
    Only catches significant gaps (weekends, holidays) — NOT daily maintenance.
    
    Mirrors data_fetcher._remove_time_gaps logic: walks backwards through gaps
    to find a block with >= BB_PERIOD candles, so charts always have data.
    """
    if len(df) < 5:
        return df

    df = df.copy()
    time_diffs = df.index.to_series().diff()
    
    # Only catch significant gaps (>4 hours): weekends, holidays.
    # Daily CME maintenance break (~1h) is fine to compute BB across.
    gap_threshold = pd.Timedelta(hours=4)
    gap_mask = time_diffs > gap_threshold
    gap_indices = gap_mask[gap_mask].index
    
    if len(gap_indices) == 0:
        return df  # No gaps, data is continuous
    
    # Walk backwards through gaps, looking for a post-gap block
    # large enough for BB computation + chart display
    min_candles = max(config.BB_PERIOD, 30)  # Need at least 30 for a clean chart
    
    for gap_idx in reversed(gap_indices):
        gap_pos = df.index.get_loc(gap_idx)
        candidate = df.iloc[gap_pos:]
        if len(candidate) >= min_candles:
            return candidate
    
    # No single post-gap block is large enough — return all data
    # (BB will still compute, charts may show a gap but won't fail)
    return df


def generate_chart(df: pd.DataFrame, symbol: str, name: str, signal: dict) -> str | None:
    """
    Generate a BB chart image for the given instrument.
    Returns the file path to the saved PNG, or None on failure.
    """
    try:
        from bollinger import compute_bollinger_bands

        # Step 1: Remove time gaps (weekends, session breaks) BEFORE computing BB
        df = _clean_continuous_data(df)

        # Step 2: Compute BB on clean, continuous data
        df = compute_bollinger_bands(df)
        df = df.dropna(subset=["BB_Upper"])

        # Last 30 candles for a clean chart
        df = df.tail(30).copy()
        if len(df) < 10:
            print(f"[Chart] Not enough data for {symbol}")
            return None

        sig_type = signal.get("type", "")
        sig_label = signal.get("label", "No Signal")
        close = float(signal.get("close", 0))

        # Determine signal marker color
        if "PRIORITY" in sig_type:
            signal_color = "#FF0000"
        elif "REVERSAL_CLOSE" in sig_type:
            signal_color = "#00E5FF"
        elif "REVERSAL_BREAK" in sig_type:
            signal_color = "#FF8800"
        elif "CROSS_UPPER" in sig_type:
            signal_color = "#FF4444"
        elif "CROSS_LOWER" in sig_type:
            signal_color = "#00CC66"
        elif "ALARM" in sig_type:
            signal_color = "#FFFF00"
        else:
            signal_color = "#888888"

        # --- Build Chart ---
        fig, ax = plt.subplots(figsize=(12, 8), facecolor="#1a1a2e")
        ax.set_facecolor("#1a1a2e")
        x = np.arange(len(df))
        dates = df.index

        # Candlesticks (thicker wicks + wider bodies for visibility)
        for i in range(len(df)):
            row = df.iloc[i]
            o, h, l, c = float(row["Open"]), float(row["High"]), float(row["Low"]), float(row["Close"])
            color = "#00CC66" if c >= o else "#FF4444"
            ax.plot([x[i], x[i]], [l, h], color=color, linewidth=1.2)
            body_bottom = min(o, c)
            body_height = max(abs(c - o), 0.1)
            ax.bar(x[i], body_height, bottom=body_bottom, width=0.7, color=color, edgecolor=color)

        # Bollinger Bands
        ax.plot(x, df["BB_Upper"].values, color="#FF6B6B", linewidth=1.5, label="Upper BB (1.5σ)", linestyle="--", alpha=0.9)
        ax.plot(x, df["BB_Mid"].values, color="#4ECDC4", linewidth=1.2, label="Mid BB (SMA 20)", alpha=0.7)
        ax.plot(x, df["BB_Lower"].values, color="#45B7D1", linewidth=1.5, label="Lower BB (1.5σ)", linestyle="--", alpha=0.9)
        ax.fill_between(x, df["BB_Upper"].values, df["BB_Lower"].values, alpha=0.08, color="#4ECDC4")

        # Emphasize large time gaps on chart directly
        time_diffs = dates.to_series().diff()
        gap_indices = time_diffs[time_diffs > pd.Timedelta(hours=4)].index
        for gap_idx in gap_indices:
            g_pos = df.index.get_loc(gap_idx)
            if g_pos > 0 and g_pos < len(x):
                mid_x = (x[g_pos-1] + x[g_pos]) / 2.0
                ax.axvline(x=mid_x, color="#666666", linestyle=":", alpha=0.8, linewidth=1)
                ax.text(mid_x, max(float(df["High"].max()), float(df["BB_Upper"].max() if not pd.isna(df["BB_Upper"].max()) else 0)), "Weekend/Holiday Gap", color="#888888", fontsize=8, rotation=90, va='top', ha='right', style='italic')

        # Signal marker
        ax.scatter(x[-1], close, s=200, color=signal_color, zorder=10, edgecolors="white", linewidth=2)

        # ── Y-axis: Focus on candles but gracefully include BB ──
        price_min = float(df["Low"].min())
        price_max = float(df["High"].max())
        price_range = price_max - price_min
        if price_range < 0.001:
            price_range = price_max * 0.01

        bb_min = float(df["BB_Lower"].min())
        bb_max = float(df["BB_Upper"].max())

        y_bottom = max(bb_min, price_min - (price_range * 1.5))
        y_bottom = min(y_bottom, price_min)
        
        y_top = min(bb_max, price_max + (price_range * 1.5))
        y_top = max(y_top, price_max)

        padding = (y_top - y_bottom) * 0.10
        ax.set_ylim(y_bottom - padding, y_top + padding)

        # Position annotation smartly using price range (not BB range)
        annotation_offset = price_range * 0.15
        if "LOWER" in sig_type:
            text_y = close - annotation_offset
        else:
            text_y = close + annotation_offset

        ax.annotate(sig_label, xy=(x[-1], close), xytext=(x[-1] - 6, text_y),
                    fontsize=10, fontweight="bold", color=signal_color,
                    arrowprops=dict(arrowstyle="->", color=signal_color, lw=2),
                    bbox=dict(boxstyle="round,pad=0.3", facecolor="#1a1a2e", edgecolor=signal_color),
                    annotation_clip=True)

        # Styling
        ax.set_title(f"{name} ({symbol}) - Bollinger Band Alert", fontsize=16, fontweight="bold", color="white", pad=15)
        ax.set_ylabel("Price ($)", fontsize=12, color="#cccccc")
        ax.tick_params(colors="#888888")
        for spine in ["top", "right"]:
            ax.spines[spine].set_visible(False)
        for spine in ["left", "bottom"]:
            ax.spines[spine].set_color("#333333")
        ax.grid(axis="y", color="#333333", linewidth=0.5, alpha=0.5)
        ax.legend(loc="upper left", fontsize=9, facecolor="#1a1a2e", edgecolor="#333333", labelcolor="white")

        # X-axis labels
        step = max(1, len(df) // 6)
        tick_positions = x[::step]
        tick_labels = [dates[i].strftime("%d %b\n%H:%M") for i in range(0, len(dates), step)]
        ax.set_xticks(tick_positions)
        ax.set_xticklabels(tick_labels, fontsize=8, color="#888888")

        ax.text(0.98, 0.02, "Lucid Alerts", transform=ax.transAxes,
                fontsize=8, color="#555555", ha="right", va="bottom", style="italic")

        plt.tight_layout()

        # Save to temp file
        chart_path = os.path.join(tempfile.gettempdir(), f"bb_chart_{symbol}.png")
        plt.savefig(chart_path, dpi=150, bbox_inches="tight", facecolor="#1a1a2e")
        plt.close(fig)

        print(f"[Chart] \u2705 Generated chart for {symbol} at {chart_path}")
        return chart_path


    except Exception as e:
        print(f"[Chart] \u274c Error generating chart for {symbol}: {e}")
        plt.close("all")
        return None


def generate_status_chart(df: pd.DataFrame, symbol: str, name: str) -> str | None:
    """
    Generate a live BB status chart (no signal marker).
    Used by the /chart command for on-demand visual checks.
    """
    try:
        from bollinger import compute_bollinger_bands

        # Remove time gaps before computing BB for clean charts
        df = _clean_continuous_data(df)

        df = compute_bollinger_bands(df)
        df = df.dropna(subset=["BB_Upper"])
        df = df.tail(40).copy()

        if len(df) < 10:
            print(f"[Chart] Not enough data for status chart {symbol}")
            return None

        close = float(df.iloc[-1]["Close"])
        upper = float(df.iloc[-1]["BB_Upper"])
        lower = float(df.iloc[-1]["BB_Lower"])
        mid = float(df.iloc[-1]["BB_Mid"])

        # Position label
        if close > upper:
            pos_label = "🔴 ABOVE Upper Band"
            pos_color = "#FF4444"
        elif close < lower:
            pos_label = "🟢 BELOW Lower Band"
            pos_color = "#00CC66"
        elif close > mid:
            pos_label = "↗️ Above midline"
            pos_color = "#FFAA00"
        else:
            pos_label = "↘️ Below midline"
            pos_color = "#4ECDC4"

        fig, ax = plt.subplots(figsize=(12, 8), facecolor="#1a1a2e")
        ax.set_facecolor("#1a1a2e")
        x = np.arange(len(df))
        dates = df.index

        # Candlesticks (thicker wicks + wider bodies for visibility)
        for i in range(len(df)):
            row = df.iloc[i]
            o, h, l, c = float(row["Open"]), float(row["High"]), float(row["Low"]), float(row["Close"])
            color = "#00CC66" if c >= o else "#FF4444"
            ax.plot([x[i], x[i]], [l, h], color=color, linewidth=1.2)
            body_bottom = min(o, c)
            body_height = max(abs(c - o), 0.1)
            ax.bar(x[i], body_height, bottom=body_bottom, width=0.7, color=color, edgecolor=color)

        # Bollinger Bands
        ax.plot(x, df["BB_Upper"].values, color="#FF6B6B", linewidth=1.5, label="Upper BB (1.5σ)", linestyle="--", alpha=0.9)
        ax.plot(x, df["BB_Mid"].values, color="#4ECDC4", linewidth=1.2, label="Mid BB (SMA 20)", alpha=0.7)
        ax.plot(x, df["BB_Lower"].values, color="#45B7D1", linewidth=1.5, label="Lower BB (1.5σ)", linestyle="--", alpha=0.9)
        ax.fill_between(x, df["BB_Upper"].values, df["BB_Lower"].values, alpha=0.08, color="#4ECDC4")

        # Emphasize large time gaps on chart directly
        time_diffs = dates.to_series().diff()
        gap_indices = time_diffs[time_diffs > pd.Timedelta(hours=4)].index
        for gap_idx in gap_indices:
            g_pos = df.index.get_loc(gap_idx)
            if g_pos > 0 and g_pos < len(x):
                mid_x = (x[g_pos-1] + x[g_pos]) / 2.0
                ax.axvline(x=mid_x, color="#666666", linestyle=":", alpha=0.8, linewidth=1)
                ax.text(mid_x, max(float(df["High"].max()), float(df["BB_Upper"].max() if not pd.isna(df["BB_Upper"].max()) else 0)), "Weekend/Holiday Gap", color="#888888", fontsize=8, rotation=90, va='top', ha='right', style='italic')

        # Current price horizontal line
        ax.axhline(y=close, color=pos_color, linewidth=1, linestyle=":", alpha=0.8)
        ax.text(x[-1] + 0.5, close, f"${close:,.2f}", color=pos_color, fontsize=10, fontweight="bold", va="center")

        # ── Y-axis: Focus on candles but gracefully include BB ──
        price_min = float(df["Low"].min())
        price_max = float(df["High"].max())
        price_range = price_max - price_min
        if price_range < 0.001:
            price_range = price_max * 0.01

        bb_min = float(df["BB_Lower"].min())
        bb_max = float(df["BB_Upper"].max())

        y_bottom = max(bb_min, price_min - (price_range * 1.5))
        y_bottom = min(y_bottom, price_min)
        
        y_top = min(bb_max, price_max + (price_range * 1.5))
        y_top = max(y_top, price_max)

        padding = (y_top - y_bottom) * 0.10
        ax.set_ylim(y_bottom - padding, y_top + padding)

        # Styling
        ax.set_title(f"{name} ({symbol}) — Live BB Status", fontsize=16, fontweight="bold", color="white", pad=15)
        ax.set_ylabel("Price ($)", fontsize=12, color="#cccccc")
        ax.tick_params(colors="#888888")
        for spine in ["top", "right"]:
            ax.spines[spine].set_visible(False)
        for spine in ["left", "bottom"]:
            ax.spines[spine].set_color("#333333")
        ax.grid(axis="y", color="#333333", linewidth=0.5, alpha=0.5)
        ax.legend(loc="upper left", fontsize=9, facecolor="#1a1a2e", edgecolor="#333333", labelcolor="white")

        step = max(1, len(df) // 6)
        tick_positions = x[::step]
        tick_labels = [dates[i].strftime("%d %b\n%H:%M") for i in range(0, len(dates), step)]
        ax.set_xticks(tick_positions)
        ax.set_xticklabels(tick_labels, fontsize=8, color="#888888")

        ax.text(0.98, 0.02, "Lucid Alerts", transform=ax.transAxes,
                fontsize=8, color="#555555", ha="right", va="bottom", style="italic")

        plt.tight_layout()

        chart_path = os.path.join(tempfile.gettempdir(), f"bb_status_{symbol}.png")
        plt.savefig(chart_path, dpi=150, bbox_inches="tight", facecolor="#1a1a2e")
        plt.close(fig)

        print(f"[Chart] \u2705 Generated status chart for {symbol}")
        return chart_path

    except Exception as e:
        print(f"[Chart] \u274c Error generating status chart for {symbol}: {e}")
        plt.close("all")
        return None
