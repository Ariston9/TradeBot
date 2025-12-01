import requests
import pandas as pd
from datetime import datetime, timedelta, timezone

BASE_URL = "https://dchart-api.tradingview.com/history"

def tv_symbol(pair: str) -> str:
    """
    EUR/USD → OANDA:EURUSD
    GBP/JPY → OANDA:GBPJPY
    """
    s = pair.replace("/", "")
    return f"OANDA:{s}"

def get_tv_series(pair: str, interval="1min", n_bars=300):
    # 1) Правильное преобразование интервала
    resolution_map = {
        "1min": "1",
        "5min": "5",
        "15min": "15",
        "30min": "30",
        "1h": "60",
    }
    res = resolution_map.get(interval, "1")

    # 2) Дата диапазон для n_bars
    now = int(datetime.now(timezone.utc).timestamp())
    # запас +10000 секунд
    _from = now - 10000

    # 3) TV symbol
    symbol = tv_symbol(pair)

    params = {
        "symbol": symbol,
        "resolution": res,
        "from": _from,
        "to": now,
    }

    try:
        r = requests.get(BASE_URL, params=params, timeout=7)
        data = r.json()

        if "s" not in data or data["s"] != "ok":
            return None, {"error": f"Нет данных TradingView для {pair}"}

        df = pd.DataFrame({
            "time": data["t"],
            "open": data["o"],
            "high": data["h"],
            "low": data["l"],
            "close": data["c"],
        })

        df["datetime"] = pd.to_datetime(df["time"], unit="s", utc=True)
        df["dt_utc"] = df["datetime"]

        return df.tail(n_bars), None

    except Exception as e:
        print("TV API ERROR:", e)
        return None, {"error": "Ошибка загрузки TradingView"}
