# po_candles.py

from collections import defaultdict, deque
from dataclasses import dataclass, asdict
from typing import Deque, Dict, List
import pandas as pd


@dataclass
class Candle:
    ts: int
    open: float
    high: float
    low: float
    close: float


class CandleBuilder:
    """
    Собирает свечи OHLC из любых тиков.
    Использование:
        builder = CandleBuilder(timeframe_sec=60)
        builder.on_tick("EURUSD_otc", ts_ms, price)
        df = builder.get_candles_df("EURUSD_otc")
    """

    def __init__(self, timeframe_sec: int = 60, max_candles: int = 2000):
        self.tf = timeframe_sec
        self.max_candles = max_candles
        self.data: Dict[str, Deque[Candle]] = defaultdict(
            lambda: deque(maxlen=self.max_candles)
        )

    def _bucket(self, ts_sec: int) -> int:
        return ts_sec - ts_sec % self.tf

    def on_tick(self, symbol: str, ts_ms: int, price: float):
        if ts_ms > 10 ** 11:  # ms
            ts_sec = ts_ms // 1000
        else:
            ts_sec = int(ts_ms)

        bucket_ts = self._bucket(ts_sec)
        dq = self.data[symbol]

        if dq and dq[-1].ts == bucket_ts:
            c = dq[-1]
            c.high = max(c.high, price)
            c.low = min(c.low, price)
            c.close = price
        else:
            dq.append(Candle(bucket_ts, price, price, price, price))

    def get_candles(self, symbol: str, limit: int = 200) -> List[Candle]:
        dq = self.data.get(symbol)
        if not dq:
            return []
        return list(dq)[-limit:]

    def get_candles_df(self, symbol: str, limit: int = 200) -> pd.DataFrame:
        candles = self.get_candles(symbol, limit)
        if not candles:
            return pd.DataFrame(columns=["time", "open", "high", "low", "close"])

        df = pd.DataFrame([asdict(c) for c in candles])
        df["datetime"] = pd.to_datetime(df["ts"], unit="s", utc=True)
        return df[["datetime", "open", "high", "low", "close"]]
