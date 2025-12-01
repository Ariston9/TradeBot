import requests
import pandas as pd

TD_API_KEY = "24e4b8641e37437a80c42cb7c0949fe1"

# соответствие TF твоего бота ↔ TwelveData
TD_RES_MAP = {
    "1min": "1min",
    "5min": "5min",
    "15min": "15min",
    "30min": "30min",
    "1h": "1h",
}


def load_twelvedata(pair: str, interval: str, n_bars: int = 300):
    """
    Returns standardized DataFrame with:
    time, open, high, low, close, datetime
    """

    # EUR/USD → EUR/USD (TwelveData принимает такой формат)
    # symbol = pair
    symbol = pair.replace("/", "")
    if "/" in pair:
        symbol = pair  # TwelveData как раз принимает формат EUR/USD


    url = "https://api.twelvedata.com/time_series"

    params = {
        "symbol": symbol,
        "interval": TD_RES_MAP.get(interval, "1min"),
        "outputsize": n_bars,
        "apikey": TD_API_KEY
    }

    try:
        r = requests.get(url, params=params)
        data = r.json()

        if "values" not in data:
            print("TwelveData error:", data)
            return None

        df = pd.DataFrame(data["values"])

        df.rename(columns={
            "datetime": "datetime",
            "open": "open",
            "high": "high",
            "low": "low",
            "close": "close"
        }, inplace=True)

        # превращаем datetime → pandas.Timestamp UTC
        df["datetime"] = pd.to_datetime(df["datetime"], utc=True)

        # создаём UNIX timestamp
        df["time"] = df["datetime"].astype("int64") // 10**9

        # приводим порядок колонок под analyzer
        df = df[["time", "open", "high", "low", "close", "datetime"]]

        # привести типы к float
        df["open"] = df["open"].astype(float)
        df["high"] = df["high"].astype(float)
        df["low"] = df["low"].astype(float)
        df["close"] = df["close"].astype(float)

        return df.iloc[::-1].reset_index(drop=True)  # реверс, чтобы шли от старых к новым

    except Exception as e:
        print("TwelveData exception:", e)
        return None
