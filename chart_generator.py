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
    We just keep the most recent continuous block. Does not require a minimum
    candle count because BB has ALREADY been mathematically computed.
    """
    if len(df) < 5:
        return df

    df = df.copy()
    time_diffs = df.index.to_series().diff()
    
    # Catch significant gaps (>4 hours): weekends, holidays.
    gap_threshold = pd.Timedelta(hours=4)
    gap_mask = time_diffs > gap_threshold
    
    if gap_mask.any():
        last_gap_idx = gap_mask[gap_mask].index[-1]
        last_gap_pos = df.index.get_loc(last_gap_idx)
        # get_loc can return a slice if duplicate timestamps exist
        if isinstance(last_gap_pos, slice):
            last_gap_pos = last_gap_pos.start
        df = df.iloc[last_gap_pos:]
        
    return df


def generate_chart(df: pd.DataFrame, symbol: str, name: str, signal: dict) -> str | None:
    """
    Generate a BB chart image for the given instrument.
    Returns the file path to the saved PNG, or None on failure.
    """
    try:
        from bollinger import compute_bollinger_bands

        # Step 1: Compute BB on the FULL history to guarantee mathematical accuracy
        df = compute_bollinger_bands(df)
        df = df.dropna(subset=["BB_Upper"])

        # Step 2: Remove time gaps VISUALLY. Plots only the continuous post-gap block
        df = _clean_continuous_data(df)

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
        
        # Lock timezone to IST so it matches user's TradingView exactly
        if df.index.tz is None:
            dates = df.index.tz_localize('UTC').tz_convert('Asia/Kolkata')
        else:
            dates = df.index.tz_convert('Asia/Kolkata')

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
            # get_loc can return a slice if duplicate timestamps exist
            if isinstance(g_pos, slice):
                g_pos = g_pos.start
            if g_pos > 0 and g_pos < len(x):
                mid_x = (x[g_pos-1] + x[g_pos]) / 2.0
                ax.axvline(x=mid_x, color="#666666", linestyle=":", alpha=0.8, linewidth=1)
                ax.text(mid_x, max(float(df["High"].max()), float(df["BB_Upper"].max() if not pd.isna(df["BB_Upper"].max()) else 0)), "Weekend/Holiday Gap", color="#888888", fontsize=8, rotation=90, va='top', ha='right', style='italic')

        # Signal marker
        ax.scatter(x[-1], close, s=200, color=signal_color, zorder=10, edgecolors="white", linewidth=2)

        # ── Y-axis: Focus on candles and RECENT BB (clip extreme past BB expansions) ──
        price_min = float(df["Low"].min())
        price_max = float(df["High"].max())
        
        recent_bb = df.tail(15)
        recent_bb_min = float(recent_bb["BB_Lower"].min()) if not pd.isna(recent_bb["BB_Lower"].min()) else price_min
        recent_bb_max = float(recent_bb["BB_Upper"].max()) if not pd.isna(recent_bb["BB_Upper"].max()) else price_max

        y_bottom = min(price_min, recent_bb_min)
        y_top = max(price_max, recent_bb_max)

        # Add 15% strict padding top and bottom
        padding = (y_top - y_bottom) * 0.15
        if padding < 0.001:
            padding = price_max * 0.01

        ax.set_ylim(y_bottom - padding, y_top + padding)

        # Position annotation smartly using price range (not BB range)
        price_range = max(price_max - price_min, 0.001)
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

        # Compute first for math robustness
        df = compute_bollinger_bands(df)
        df = df.dropna(subset=["BB_Upper"])
        
        # Remove time gaps visually
        df = _clean_continuous_data(df)
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

        # Lock timezone to IST so it matches user's TradingView exactly
        if df.index.tz is None:
            dates = df.index.tz_localize('UTC').tz_convert('Asia/Kolkata')
        else:
            dates = df.index.tz_convert('Asia/Kolkata')

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
            # get_loc can return a slice if duplicate timestamps exist
            if isinstance(g_pos, slice):
                g_pos = g_pos.start
            if g_pos > 0 and g_pos < len(x):
                mid_x = (x[g_pos-1] + x[g_pos]) / 2.0
                ax.axvline(x=mid_x, color="#666666", linestyle=":", alpha=0.8, linewidth=1)
                ax.text(mid_x, max(float(df["High"].max()), float(df["BB_Upper"].max() if not pd.isna(df["BB_Upper"].max()) else 0)), "Weekend/Holiday Gap", color="#888888", fontsize=8, rotation=90, va='top', ha='right', style='italic')

        # Current price horizontal line
        ax.axhline(y=close, color=pos_color, linewidth=1, linestyle=":", alpha=0.8)
        ax.text(x[-1] + 0.5, close, f"${close:,.2f}", color=pos_color, fontsize=10, fontweight="bold", va="center")

        # ── Y-axis: Focus on candles and RECENT BB (clip extreme past BB expansions) ──
        price_min = float(df["Low"].min())
        price_max = float(df["High"].max())
        
        recent_bb = df.tail(15)
        recent_bb_min = float(recent_bb["BB_Lower"].min()) if not pd.isna(recent_bb["BB_Lower"].min()) else price_min
        recent_bb_max = float(recent_bb["BB_Upper"].max()) if not pd.isna(recent_bb["BB_Upper"].max()) else price_max

        y_bottom = min(price_min, recent_bb_min)
        y_top = max(price_max, recent_bb_max)

        # Add 15% strict padding top and bottom
        padding = (y_top - y_bottom) * 0.15
        if padding < 0.001:
            padding = price_max * 0.01

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
