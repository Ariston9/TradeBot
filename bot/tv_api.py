# bot/api/tv_api.py
import yfinance as yf
import pandas as pd

def get_tv_series(pair: str, interval="1min", n_bars=300):
    """
    Рабочий и надежный метод загрузки котировок через Yahoo Finance.
    Поддерживает все пары Forex в формате EUR/USD.
    """
    # EUR/USD -> EURUSD=X (формат Yahoo)
    symbol = pair.replace("/", "") + "=X"

    tf = {
        "1min": "1m",
        "5min": "5m",
        "15min": "15m",
        "30min": "30m",
        "1h": "60m",
    }.get(interval, "1m")

    try:
        df = yf.download(
            tickers=symbol,
            interval=tf,
            period="7d",
            progress=False
        )

        if df is None or df.empty:
            return None, {"error": f"⚠️ Нет котировок Yahoo для {pair}"}

        # приведение формата
        df = df.reset_index().rename(columns={
            "Datetime": "datetime",
            "Open": "open",
            "High": "high",
            "Low": "low",
            "Close": "close",
        })

        df["datetime"] = pd.to_datetime(df["datetime"], utc=True)
        df["dt_utc"] = df["datetime"]
        df["time"] = df["datetime"].astype("int64") // 10**9

        return df.tail(n_bars), None

    except Exception as e:
        print("Yahoo error:", e)
        return None, {"error": "⚠️ Ошибка загрузки Yahoo"}
