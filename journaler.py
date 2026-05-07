"""
Automated CSV Journaler for Commodity BB Alerts.
Appends alert data to a local CSV file.
"""
import csv
import os

JOURNAL_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "trade_journal.csv")

def log_alert(symbol: str, signal_type: str, close_price: float, upper_bb: float, lower_bb: float, timestamp: str):
    """Appends a recorded alert to the CSV journal."""
    try:
        file_exists = os.path.isfile(JOURNAL_FILE)
        
        with open(JOURNAL_FILE, mode='a', newline='') as f:
            writer = csv.writer(f)
            
            # Write header if file is entirely new
            if not file_exists:
                writer.writerow(["Timestamp_IST", "Instrument", "Signal_Type", "Close_Price", "Upper_BB", "Lower_BB"])
                
            writer.writerow([
                timestamp,
                symbol,
                signal_type,
                round(close_price, 2),
                round(upper_bb, 2),
                round(lower_bb, 2)
            ])
        print(f"[Journaler] Logged {signal_type} for {symbol} to trade_journal.csv")
    except Exception as e:
        print(f"[Journaler] ⚠️ Failed to log alert: {e}")


RESULTS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "signal_results.csv")

def log_result(symbol: str, signal_type: str, direction: str, entry_price: float,
               exit_price: float, sl: float, target: float, result: str, pnl: float, timestamp: str):
    """Appends a win/loss result to the signal results CSV."""
    try:
        file_exists = os.path.isfile(RESULTS_FILE)

        with open(RESULTS_FILE, mode='a', newline='') as f:
            writer = csv.writer(f)
            if not file_exists:
                writer.writerow(["Timestamp", "Instrument", "Signal_Type", "Direction",
                                 "Entry_Price", "SL", "Target", "Exit_Price", "Result", "PnL_Points"])
            writer.writerow([
                timestamp, symbol, signal_type, direction,
                round(entry_price, 2), round(sl, 2), round(target, 2),
                round(exit_price, 2), result, round(pnl, 2)
            ])
        print(f"[Journaler] Logged {result} for {symbol} to signal_results.csv")
    except Exception as e:
        print(f"[Journaler] ⚠️ Failed to log result: {e}")
