import requests
import pandas as pd

TV_SCAN_URL = "https://scanner.tradingview.com/{}/scan"

TF_MAP = {
    "1min": "1",
    "5min": "5",
    "15min": "15",
}

DATA_SOURCES = [
    ("forex", "FX:{}"),
    ("forex", "OANDA:{}"),
    ("forex", "FXCM:{}"),
    ("forex", "FOREXCOM:{}"),
]


def fetch_tv_data(market: str, symbol: str, interval: str):
    tf = TF_MAP.get(interval, "1")

    payload = {
        "symbols": {
            "tickers": [symbol],
            "query": {"types": []}
        },
        "columns": [
            f"open|{tf}",
            f"high|{tf}",
            f"low|{tf}",
            f"close|{tf}",
            f"time|{tf}"
        ]
    }

    r = requests.post(TV_SCAN_URL.format(market), json=payload)
    if not r.ok:
        return None

    data = r.json()
    if "data" not in data or not data["data"]:
        return None

    d = data["data"][0]["d"]

    # FORMAT 1 — Correct dict
    if isinstance(d, dict):
        return pd.DataFrame({
            "open": d.get(f"open|{tf}", []),
            "high": d.get(f"high|{tf}", []),
            "low": d.get(f"low|{tf}", []),
            "close": d.get(f"close|{tf}", []),
            "time": d.get(f"time|{tf}", []),
        })

    # FORMAT 2 — TradingView returns list (rare pairs)
    if isinstance(d, list) and len(d) >= 5:
        return pd.DataFrame({
            "open": d[0],
            "high": d[1],
            "low": d[2],
            "close": d[3],
            "time": d[4],
        })

    return None

def get_tv_series(pair: str, interval: str = "1min", n_bars: int = 300):
    symbol = pair.replace("/", "")

    # Пробуем разные поставщики
    for market, fmt in DATA_SOURCES:
        ticker = fmt.format(symbol)
        df = fetch_tv_data(market, ticker, interval)

        if df is not None and len(df) > 0:
            df["datetime"] = pd.to_datetime(df["time"], unit="s", utc=True)
            df["dt_utc"] = df["datetime"]
            return df.tail(n_bars), None

    return None, {"error": f"No TradingView data for {pair}"}
