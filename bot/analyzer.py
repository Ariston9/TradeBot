import time
from datetime import datetime
from typing import Dict, Any, Tuple, Optional, List

from .tv_api import get_tv_series
from .indicators import compute_indicators
from .scoring import score_on_tf, calc_overall_probability
from .logger import log_signal

# Пытаемся взять настройки из config, если есть
try:
    from .config import TFS, MAX_CANDLES, REQUEST_DELAY
except ImportError:
    # Запасные значения, если в config нет
    TFS = {"M1": "1min", "M5": "5min", "M15": "15min"}
    MAX_CANDLES = 120
    REQUEST_DELAY = 1.2


def analyze_pair_for_user(user_id: int, pair: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """
    Главная функция анализа одной пары для конкретного пользователя.
    Возвращает:
      res: {
         "pair": str,
         "dir": "BUY"/"SELL"/"NONE",
         "prob": float,
         "expiry": int|None,
         "entry_price": float|None,
      }, err: str|None
    """
    tf_results: List[Dict[str, Any]] = []
    last_close_1m: Optional[float] = None

    # --- Анализ по таймфреймам M1, M5, M15 ---
    for tf_name, tf_int in TFS.items():  # M1, M5, M15
        df_tf, err = get_tv_series(pair, tf_int, MAX_CANDLES)
        time.sleep(REQUEST_DELAY)

        if df_tf is None or df_tf.empty:
            print(f"⚠️ Не удалось получить данные {pair} {tf_int}: {err}")
            continue

        # Индикаторы
        df_tf = compute_indicators(df_tf)

        # Скоринг по TF (используем новую сигнатуру score_on_tf)
        ind = score_on_tf(df_tf, tf_name=tf_name)
        ind["tf"] = tf_name
        tf_results.append(ind)

        if tf_int == "1min":
            last_close_1m = float(df_tf["close"].iloc[-1])

    if not tf_results:
        return None, f"Нет данных для {pair}. Проверь источник котировок."

    # --- Вероятность по всем TF ---
    prob = calc_overall_probability(tf_results)

    # Разбор по TF
    m1 = next((r for r in tf_results if r.get("tf") == "M1"), None)
    m5 = next((r for r in tf_results if r.get("tf") == "M5"), None)
    m15 = next((r for r in tf_results if r.get("tf") == "M15"), None)

    dirs = [r["direction"] for r in tf_results]
    buy_count = dirs.count("BUY")
    sell_count = dirs.count("SELL")

    overall = "NONE"

    # 1) Основное направление — M1, если оно не NONE
    if m1 and m1.get("direction") in ("BUY", "SELL"):
        overall = m1["direction"]
    # 2) Иначе — по большинству голосов TF
    elif buy_count > sell_count:
        overall = "BUY"
    elif sell_count > buy_count:
        overall = "SELL"
    else:
        overall = "NONE"

    # --- Оценка волатильности по M1 ---
    df_vol, _ = get_tv_series(pair, "1min", 50)
    if df_vol is not None and not df_vol.empty:
        vol_df = df_vol.copy()
        volatility = vol_df["close"].diff().abs().tail(10).mean()
    else:
        volatility = 0.0004  # запасное значение

    # --- Экспирация (логика как в твоём исходном коде, слегка упрощённая) ---
    expiry: Optional[int] = None
    if prob >= 85:
        # В исходнике всё равно везде 3
        expiry = 3
    elif prob >= 75:
        # В исходнике везде 4
        expiry = 4
    elif prob >= 68:
        expiry = 4
    else:
        expiry = None  # слабый сигнал — вход не рекомендуем

    # -----------------------------
    #  Точный вход по хвостам свечей (WICK ENTRY)
    # -----------------------------
    entry_price: Optional[float] = None
    try:
        df_1m, _ = get_tv_series(pair, "1min", 3)
        if df_1m is not None and not df_1m.empty:
            last = df_1m.iloc[-1]
            high = float(last["high"])
            low = float(last["low"])
            close = float(last["close"])

            # M1-индикаторы для признаков разворота/ректжекта
            m1_data = m1 or {}
            reversal_up = bool(m1_data.get("reversal_up", False))
            reversal_down = bool(m1_data.get("reversal_down", False))
            rejection_up = bool(m1_data.get("rejection_up", False))
            rejection_down = bool(m1_data.get("rejection_down", False))

            if overall == "BUY":
                # Разворот/отбой снизу -> вход по low (нижний фитиль)
                if reversal_up or rejection_up:
                    entry_price = low
                else:
                    # Обычный сигнал -> среднее между low и close
                    entry_price = (low + close) / 2.0

            elif overall == "SELL":
                # Разворот/отбой сверху -> вход по high (верхний фитиль)
                if reversal_down or rejection_down:
                    entry_price = high
                else:
                    # Обычный сигнал -> среднее между high и close
                    entry_price = (high + close) / 2.0

            else:
                # Если нет чёткого направления — просто close
                entry_price = close
        else:
            entry_price = None
    except Exception as e:
        print(f"⚠️ Ошибка wick-entry для {pair}: {e}")
        entry_price = None

    # Fallback — если по какой-то причине entry_price не удалось посчитать
    if entry_price is None:
        if last_close_1m is not None:
            entry_price = last_close_1m
        else:
            df1, _ = get_tv_series(pair, "1min", 5)
            if df1 is not None and not df1.empty:
                entry_price = float(df1["close"].iloc[-1])
            else:
                entry_price = None

    # --- Лог сигнала (берём M1 как базу) ---
    if overall != "NONE" and expiry and m1 is not None and entry_price is not None:
        indicators = {
            "ema20":           m1.get("ema20"),
            "macd_diff":       m1.get("macd_diff"),
            "macd_vote":       m1.get("macd_vote"),
            "rsi":             m1.get("rsi"),
            "rsi_vote":        m1.get("rsi_vote"),
            "rsi_pro_active":  m1.get("rsi_pro_active"),
            "impulse":         m1.get("impulse"),
            "pattern":         m1.get("pattern"),
            "reversal_up":     m1.get("reversal_up"),
            "reversal_down":   m1.get("reversal_down"),
            "div_buy":         m1.get("div_buy"),
            "div_sell":        m1.get("div_sell"),
            "near_support":    m1.get("near_support"),
            "near_resistance": m1.get("near_resistance"),
        }

        log_signal(
            pair=pair,
            direction=overall,
            prob=prob,
            expiry=expiry,
            entry_price=entry_price if entry_price is not None else 0.0,
            indicators=indicators,
        )

    res = {
        "pair": pair,
        "dir": overall,
        "prob": prob,
        "expiry": expiry,
        "entry_price": entry_price,
    }
    return res, None
