import yfinance as yf
from datetime import datetime
import pandas as pd

def compare_data():
    print("Fetching 15m data for the last 2 days...")
    
    # Fetch Micro Silver (SIL=F)
    df_sil = yf.download("SIL=F", period="2d", interval="15m", progress=False)
    
    # Fetch Standard Silver (SI=F)
    df_si = yf.download("SI=F", period="2d", interval="15m", progress=False)

    print("\n=============================================")
    print(f"Candles Found (Last 2 Days):")
    print(f"Micro Silver (SIL=F)   : {len(df_sil)} candles")
    print(f"Standard Silver (SI=F) : {len(df_si)} candles")
    print("=============================================\n")
    
    print("Notice how Standard Silver has way more candles! SIL=F is missing hours of data.\n")
    
    print("Let's look at the timestamps from yesterday evening (when the gaps happened):")
    
    # Just show a slice of timestamps to see the gaps
    # We will pick a recent 5-hour window
    
    if len(df_sil) > 0 and len(df_si) > 0:
        # Convert index to localized time for easier reading, or just use string
        print("\n--- Micro Silver (SIL=F) Timestamps ---")
        for ts in df_sil.index[-30:]:
            print(ts.strftime('%Y-%m-%d %H:%M'))
            
        print("\n--- Standard Silver (SI=F) Timestamps ---")
        for ts in df_si.index[-30:]:
            print(ts.strftime('%Y-%m-%d %H:%M'))

if __name__ == "__main__":
    compare_data()
