"""
Automated CSV Journaler for Commodity BB Alerts.
Appends alert data to a local CSV file.
"""
import csv
import os

JOURNAL_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "trade_journal.csv")

def log_alert(symbol: str, signal_type: str, close_price: float, upper_bb: float, lower_bb: float, timestamp: str):
    """Appends a recorded alert to the CSV journal."""
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
