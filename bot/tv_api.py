from datetime import datetime, timezone
from typing import Tuple, Optional, Dict

import pandas as pd
from tvDatafeed import TvDatafeed, Interval

from .config import TV_USERNAME, TV_PASSWORD, TV_MAP

INTERVAL_MAP = {
    "1min":  Interval.in_1_minute,
    "5min":  Interval.in_5_minute,
    "15min": Interval.in_15_minute,
}

tv = TvDatafeed(username=TV_USERNAME, password=TV_PASSWORD)


def get_tv_series(
    pair: str,
    interval: str = "5min",
    n_bars: int = 300
) -> Tuple[Optional[pd.DataFrame], Optional[Dict]]:
    if pair not in TV_MAP:
        return None, {"error": f"Пара {pair} не найдена в TV_MAP"}
    sym, ex = TV_MAP[pair]
    try:
        df = tv.get_hist(symbol=sym, exchange=ex, interval=INTERVAL_MAP[interval], n_bars=n_bars)
        if df is None or df.empty:
            return None, {"error": "Пустой ответ от TradingView"}

        df = df.reset_index().rename(columns={"datetime": "datetime"})
        for c in ["open", "high", "low", "close"]:
            df[c] = df[c].astype(float)
        df["dt_utc"] = pd.to_datetime(df["datetime"], utc=True)

        last_candle_time = df["dt_utc"].iloc[-1]
        age_sec = (datetime.now(timezone.utc) - last_candle_time).total_seconds()
        if age_sec > 3600:
            last_time_str = last_candle_time.strftime("%Y-%m-%d %H:%M UTC")
            return None, {"error": f"⚠️ Нет свежих котировок ({last_time_str}). Рынок, возможно, закрыт."}

        return df, None
    except Exception as e:
        return None, {"error": str(e)}
