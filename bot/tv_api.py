import pandas as pd
from bot.api.finnhub_api import load_finnhub

def get_tv_series(pair: str, interval: str = "1min", n_bars: int = 300):
    """
    Главная функция → возвращает свечи.
    Теперь источник — Finnhub (реальные форекс котировки).
    """

    df = load_finnhub(pair, interval, n_bars)

    if df is None or df.empty:
        return None, {"error": f"No data for {pair} (Finnhub API)"}

    # analyzer ожидает именно эти колонки
    df = df[["time", "open", "high", "low", "close", "datetime"]]

    return df, None
