import requests
import pandas as pd

FINNHUB_KEY = "d4mkro1r01qnt4h0ku4gd4mkro1r01qnt4h0ku50"

# соответствие TF → Finnhub resolution
RES_MAP = {
    "1min": "1",
    "5min": "5",
    "15min": "15",
    "30min": "30",
    "1h": "60",
}


def load_finnhub(pair: str, interval: str, n_bars: int = 300):
    """
    Returns standardized DataFrame:
    columns: time, open, high, low, close, datetime
    """

    # EUR/USD → OANDA:EUR_USD
    fx_symbol = "OANDA:" + pair.replace("/", "_")

    res = RES_MAP.get(interval, "1")

    url = "https://finnhub.io/api/v1/forex/candle"
    params = {
        "symbol": fx_symbol,
        "resolution": res,
        "count": n_bars,
        "token": FINNHUB_KEY
    }

    try:
        r = requests.get(url, params=params)
        data = r.json()

        if data.get("s") != "ok":
            return None

        df = pd.DataFrame({
            "time": data["t"],
            "open": data["o"],
            "high": data["h"],
            "low": data["l"],
            "close": data["c"]
        })

        # timestamp → datetime
        df["datetime"] = pd.to_datetime(df["time"], unit="s", utc=True)
        df["dt_utc"] = df["datetime"]

        return df

    except Exception as e:
        print("Finnhub error:", e)
        return None
