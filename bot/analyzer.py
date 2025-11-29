# bot/analyzer.py
import time
from datetime import datetime, timezone

from .config import (
    PAIRS,
    TFS,
    MAX_CANDLES,
    REQUEST_DELAY,
)
from .tv_api import get_tv_series
from .indicators import compute_indicators
from .scoring import score_on_tf, calc_overall_probability
from .logger import log_signal


# -------------------- Проверка свежести свечей --------------------
def check_market_open(df):
    if df is None or df.empty:
        return {"error": "⚠️ Рынок закрыт.\nНет свежих котировок."}

    if "datetime" not in df.columns:
        return {"error": "⚠️ Рынок закрыт.\nНет timestamp у свечей."}

    ts = df["datetime"].iloc[-1]

    try:
        if ts.tzi
