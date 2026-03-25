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


def generate_chart(df: pd.DataFrame, symbol: str, name: str, signal: dict) -> str | None:
    """
    Generate a BB chart image for the given instrument.
    Returns the file path to the saved PNG, or None on failure.
    """
    try:
        from bollinger import compute_bollinger_bands
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
        elif "CROSS_UPPER" in sig_type:
            signal_color = "#FF4444"
        elif "CROSS_LOWER" in sig_type:
            signal_color = "#00CC66"
        elif "TOUCH" in sig_type:
            signal_color = "#FF8800"
        else:
            signal_color = "#888888"

        # --- Build Chart ---
        fig, ax = plt.subplots(figsize=(12, 6), facecolor="#1a1a2e")
        ax.set_facecolor("#1a1a2e")
        x = np.arange(len(df))
        dates = df.index

        # Candlesticks
        for i in range(len(df)):
            row = df.iloc[i]
            o, h, l, c = float(row["Open"]), float(row["High"]), float(row["Low"]), float(row["Close"])
            color = "#00CC66" if c >= o else "#FF4444"
            ax.plot([x[i], x[i]], [l, h], color=color, linewidth=0.8)
            body_bottom = min(o, c)
            body_height = max(abs(c - o), 0.1)
            ax.bar(x[i], body_height, bottom=body_bottom, width=0.6, color=color, edgecolor=color)

        # Bollinger Bands
        ax.plot(x, df["BB_Upper"].values, color="#FF6B6B", linewidth=1.5, label="Upper BB (1.5\u03c3)", linestyle="--", alpha=0.9)
        ax.plot(x, df["BB_Mid"].values, color="#4ECDC4", linewidth=1.2, label="Mid BB (SMA 20)", alpha=0.7)
        ax.plot(x, df["BB_Lower"].values, color="#45B7D1", linewidth=1.5, label="Lower BB (1.5\u03c3)", linestyle="--", alpha=0.9)
        ax.fill_between(x, df["BB_Upper"].values, df["BB_Lower"].values, alpha=0.08, color="#4ECDC4")

        # Signal marker
        upper_val = float(df.iloc[-1]["BB_Upper"])
        lower_val = float(df.iloc[-1]["BB_Lower"])
        band_range = upper_val - lower_val

        ax.scatter(x[-1], close, s=200, color=signal_color, zorder=10, edgecolors="white", linewidth=2)

        # Position annotation smartly (above or below based on signal)
        if "LOWER" in sig_type:
            text_y = close - band_range * 0.3
        else:
            text_y = close + band_range * 0.3

        ax.annotate(sig_label, xy=(x[-1], close), xytext=(x[-1] - 6, text_y),
                    fontsize=10, fontweight="bold", color=signal_color,
                    arrowprops=dict(arrowstyle="->", color=signal_color, lw=2),
                    bbox=dict(boxstyle="round,pad=0.3", facecolor="#1a1a2e", edgecolor=signal_color))

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

        ax.text(0.98, 0.02, "Lucid Alerts \u2022 TradeSea", transform=ax.transAxes,
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
