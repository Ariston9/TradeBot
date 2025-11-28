import pandas as pd
import yfinance as yf


# Соответствие таймфреймов бота и yfinance
INTERVAL_MAP = {
    "1min": "1m",
    "5min": "5m",
    "15min": "15m",
}


def _pair_to_yahoo_symbol(pair: str) -> str:
    """
    'EUR/CHF' -> 'EURCHF=X'
    'GBP/USD' -> 'GBPUSD=X'
    и т.п.
    """
    return pair.replace("/", "") + "=X"


def fetch_yahoo_data(symbol: str, interval: str, n_bars: int) -> pd.DataFrame | None:
    """
    Получаем историю свечей с Yahoo Finance.

    symbol  – строка вида 'EURCHF=X'
    interval – '1min' / '5min' / '15min'
    n_bars – сколько баров вернуть
    """

    yf_interval = INTERVAL_MAP.get(interval, "1m")

    # Берём запас по времени, чтобы точно хватило n_bars
    # Для минутных таймфреймов достаточно пары дней
    df = yf.download(
        symbol,
        period="7d",
        interval=yf_interval,
        progress=False,
        auto_adjust=False,
    )

    if df is None or df.empty:
        return None

    # Приводим к формату, который дальше использует бот
    df = df.reset_index()

    # У yfinance индекс – колонка Datetime / DatetimeUTC
    # Приведём к единому виду: time (unix) и dt_utc (datetime)
    if "Datetime" in df.columns:
        dt_col = "Datetime"
    elif "Date" in df.columns:
        dt_col = "Date"
    else:
        # На всякий случай – неизвестный формат
        return None

    df["dt_utc"] = pd.to_datetime(df[dt_col], utc=True)
    df["time"] = df["dt_utc"].view("int64") // 10**9  # unix-timestamp в секундах

    # Переименуем цены под твой код
    df.rename(
        columns={
            "Open": "open",
            "High": "high",
            "Low": "low",
            "Close": "close",
        },
        inplace=True,
    )

    # Оставим только нужные колонки
    df = df[["time", "open", "high", "low", "close", "dt_utc"]]

    # Вернём хвост нужной длины
    return df.tail(n_bars)


def get_tv_series(pair: str, interval: str = "1min", n_bars: int = 300):
    """
    Основная функция, которую вызывает бот.

    Возвращает:
      (DataFrame, None)  – если данные есть
      (None, {"error": ...}) – если данных нет
    """
    symbol = _pair_to_yahoo_symbol(pair)

    df = fetch_yahoo_data(symbol, interval, n_bars)
    if df is None or df.empty:
        return None, {"error": f"No data for {pair} from Yahoo Finance"}

    # Совместимость с остальным кодом: он ожидает колонку dt_utc
    # (она уже есть в fetch_yahoo_data)
    return df, None
