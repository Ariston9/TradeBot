import requests
import pandas as pd
from datetime import datetime, timezone

FINNHUB_KEY = "d4mv0u1r01qsn6g8j7n0d4mv0u1r01qsn6g8j7ng"  # бесплатный API KEY

def get_tv_series(pair: str, interval="1min", n_bars=300):
    symbol = pair.replace("/", "")  # EURUSD
    tf_map = {
        "1min": "1",
        "5min": "5",
        "15min": "15",
    }
    res = requests.get(
        "https://finnhub.io/api/v1/forex/candle",
        params=dict(
            symbol=f"OANDA:{symbol}",
            resolution=tf_map[interval],
            token=FINNHUB_KEY,
            count=n_bars,
        )
    ).json()

    if res.get("s") != "ok":
        return None, {"error": "Нет свечей от TradingView source"}

    df = pd.DataFrame({
        "time": res["t"],
        "open": res["o"],
        "high": res["h"],
        "low": res["l"],
        "close": res["c"],
    })
    df["datetime"] = pd.to_datetime(df["time"], unit="s", utc=True)
    df["dt_utc"] = df["datetime"]

    return df.tail(n_bars), None
