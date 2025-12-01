from bot.api.twelvedata_api import load_twelvedata

def get_tv_series(pair: str, interval: str = "1min", n_bars: int = 300):
    """
    Главная функция загрузки свечей.
    Теперь источник — TwelveData API.
    """

    df = load_twelvedata(pair, interval, n_bars)

    if df is None or df.empty:
        return None, {"error": f"No data for {pair} (TwelveData API)"}

    # ВАЖНО: возвращаем полный набор колонок
    # analyzer ожидает dt_utc
    df["dt_utc"] = df["datetime"]

    return df, None
