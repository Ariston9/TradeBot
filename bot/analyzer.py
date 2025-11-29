# ✔ ОЧИЩЕННАЯ ВЕРСИЯ analyzer.py
import time
from datetime import datetime, timezone

from .config import PAIRS, TFS, MAX_CANDLES, REQUEST_DELAY
from .tv_api import get_tv_series
from .indicators import compute_indicators
from .scoring import score_on_tf, calc_overall_probability
from .logger import log_signal, stats_last_24h


# --- Проверка свежести рынка (точно как в Colab) ---
def check_market_open(df):
    if df is None or df.empty:
        return {"error": "⚠️ Рынок закрыт.\nНет свежих котировок."}

    if "datetime" not in df.columns:
        return {"error": "⚠️ Рынок закрыт.\nНет timestamp у свечей."}

    ts = df["datetime"].iloc[-1]

    try:
        if ts.tzinfo is None:
            ts = ts.tz_localize("UTC")
    except:
        return {"error": "⚠️ Рынок закрыт.\nОшибка метки времени."}

    now_utc = datetime.now(timezone.utc)
    age_sec = (now_utc - ts).total_seconds()

    if age_sec > 3600:
        return {
            "error": (
                "⚠️ Рынок закрыт.\n"
                f"Последняя свеча была: {ts.strftime('%Y-%m-%d %H:%M UTC')}"
            )
        }

    return None


async def analyze_pair_for_user(user_id: int, pair: str):
    tf_results = []
    last_close_1m = None

    for tf_name, tf_int in TFS.items():
        df_tf, err = get_tv_series(pair, tf_int, MAX_CANDLES)
        time.sleep(REQUEST_DELAY)

        if df_tf is None:
            continue

        df_tf = compute_indicators(df_tf)

        # --- ПРОВЕРКА РЫНКА ---
        market_state = check_market_open(df_tf)
        if market_state:
            return None, market_state["error"]
        # ----------------------

        ind = score_on_tf(df_tf, tf_name)
        ind["tf"] = tf_name
        tf_results.append(ind)

        if tf_int == "1min":
            last_close_1m = float(df_tf["close"].iloc[-1])

    if not tf_results:
        return None, f"Нет данных для {pair}."

    prob = calc_overall_probability(tf_results)

    m1 = next((r for r in tf_results if r["tf"] == "M1"), None)
    m5 = next((r for r in tf_results if r["tf"] == "M5"), None)
    m15 = next((r for r in tf_results if r["tf"] == "M15"), None)

    dirs = [r["direction"] for r in tf_results]
    buy_count = dirs.count("BUY")
    sell_count = dirs.count("SELL")

    overall = "NONE"
    if m1 and m1["direction"] in ("BUY", "SELL"):
        overall = m1["direction"]
    elif buy_count > sell_count:
        overall = "BUY"
    elif sell_count > buy_count:
        overall = "SELL"

    # --- Экспирация ---
    expiry = None
    expiry = 3 if prob >= 75 else None

    # --- WICK ENTRY ---
    entry_price = last_close_1m

    try:
        df_1m, _ = get_tv_series(pair, "1min", 3)
        if df_1m is not None and not df_1m.empty and overall in ("BUY", "SELL"):
            last = df_1m.iloc[-1]
            high = float(last["high"])
            low = float(last["low"])
            close = float(last["close"])

            if overall == "BUY":
                entry_price = low
            else:
                entry_price = high
    except:
        pass

    if entry_price is None:
        entry_price = last_close_1m

    if overall != "NONE" and expiry:
        log_signal(
            pair,
            overall,
            prob,
            expiry,
            entry_price or 0.0,
            {},
        )

    return {
        "pair": pair,
        "dir": overall,
        "prob": prob,
        "expiry": expiry,
        "entry_price": entry_price,
    }, None


def current_utc_str() -> str:
    return datetime.now(timezone.utc).strftime("%H:%M UTC")
