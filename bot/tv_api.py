import requests
import pandas as pd
from datetime import datetime, timezone

# TradingView scanner endpoints:
TV_SCAN_URL = "https://scanner.tradingview.com/forex/scan"

# Timeframe mapping for TradingView scanner
TF_MAP = {
    "1min": "1",
    "5min": "5",
    "15min": "15",
}


def get_tv_series(pair: str, interval: str = "1min", n_bars: int = 300):
    """
    Скачать OHLC свечи через TradingView Scanner API.
    Работает без авторизации.
    Полностью совместим с сервером Railway.
    """

    try:
        symbol = pair.replace("/", "")
        tf_code = TF_MAP.get(interval, "1")

        payload = {
            "symbols": {
                "tickers": [f"FX:{symbol}"],
                "query": {"types": []}
            },
            "columns": [
                f"close|{tf_code}",
                f"open|{tf_code}",
                f"high|{tf_code}",
                f"low|{tf_code}",
                f"time|{tf_code}"
            ]
        }

        response = requests.post(TV_SCAN_URL, json=payload, timeout=10)

        if not response.ok:
            return None, {"error": f"TradingView API error: {response.status_code}"}

        data = response.json()

        if "data" not in data or not data["data"]:
            return None, {"error": f"No data from TradingView for {pair}"}

        d = data["data"][0]["d"]

        closes = d.get(f"close|{tf_code}", [])
        opens = d.get(f"open|{tf_code}", [])
        highs = d.get(f"high|{tf_code}", [])
        lows = d.get(f"low|{tf_code}", [])
        times = d.get(f"time|{tf_code}", [])

        if not closes or not times:
            return None, {"error": f"Empty OHLC for {pair}"}

        df = pd.DataFrame({
            "close": closes,
            "open": opens,
            "high": highs,
            "low": lows,
            "time": times
        })

        # Convert timestamps
        df["datetime"] = pd.to_datetime(df["time"], unit="s", utc=True)
        df["dt_utc"] = df["datetime"]

        # Keep last N bars
        df = df.tail(n_bars)

        # Standard format for your indicators
        df = df[["datetime", "open", "high", "low", "close", "dt_utc"]]

        return df, None

    except Exception as e:
        return None, {"error": str(e)}
