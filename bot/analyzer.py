# bot/analyzer.py
import time
from datetime import datetime, timezone

from .config import TFS, MAX_CANDLES, REQUEST_DELAY
from .tv_api import get_tv_series
from .indicators import compute_indicators
from .scoring import score_on_tf, calc_overall_probability
from .logger import log_signal

def check_market_open(df):
    """
    Проверка свежести свечей — как в Colab.
    Возвращает dict({"error": "..."}) если рынок закрыт.
    Иначе — None.
    """
    if df is None or df.empty:
        return {"error": "⚠️ Рынок закрыт.\nНет котировок."}

    if "datetime" not in df.columns:
        return {"error": "⚠️ Рынок закрыт.\nНет timestamp у свечей."}

    ts = df["datetime"].iloc[-1]

    try:
        if ts.tzinfo is None:
            ts = ts.tzlocalize("UTC")
    except:
        return {"error": "⚠️ Рынок закрыт.\nНеверная метка времени."}

    age_sec = (datetime.now(timezone.utc) - ts).total_seconds()

    # старше 60 минут → рынок закрыт
    if age_sec > 3600:
        return {
            "error": (
                "⚠️ Рынок закрыт.\n"
                f"Последняя свеча была: {ts.strftime('%Y-%m-%d %H:%M UTC')}"
            )
        }

    return None

# -------------------- core analysis (как в Colab) --------------------
async def analyze_pair_for_user(user_id: int, pair: str):
    """
    Основной анализ одной пары для панели.

    ВАЖНО:
    - Используем только TradingView/Yahoo данные через get_tv_series.
    - Логика полностью соответствует версии в
      kopie_von_stabil_v_averaging_tradebot_tradingview.py
      (M1/M5/M15, Probability v7.1, WICK ENTRY).
    - OTC/PO логика здесь не активна (как в текущем GitHub-проекте).
    """

    # --------- Сбор индикаторов по всем TF ---------
    tf_results: list[dict] = []
    last_close_1m: float | None = None

    for tf_name, tf_int in TFS.items():  # например: {"M1": "1min", "M5": "5min", ...}
        df_tf, err = get_tv_series(pair, tf_int, MAX_CANDLES)
        time.sleep(REQUEST_DELAY)

        if df_tf is None:
            # Если ошибка "рынок закрыт" / "нет котировок" и т.п. — сразу отдаём её наверх
            if isinstance(err, dict) and "error" in err:
                return None, err["error"]
            print(f"⚠️ Не удалось получить данные {pair} {tf_int}: {err}")
            continue

        # ---- Проверка рынка (как в Colab) ----
        market_state = check_market_open(df_tf)
        if market_state:
            return None, market_state["error"]
        # --------------------------------------

        # Индикаторы, как в Colab
        df_tf = compute_indicators(df_tf)
        ind = score_on_tf(df_tf, tf_name)
        ind["tf"] = tf_name
        tf_results.append(ind)

        if tf_int == "1min":
            # запоминаем последний close на M1 (fallback для entry_price)
            last_close_1m = float(df_tf["close"].iloc[-1])

    if not tf_results:
        return None, f"Нет данных для {pair}. Проверь подключение к TradingView."

    # --------- Общая вероятность по всем TF (Probability v7.1) ---------
    prob = calc_overall_probability(tf_results)

    # Разбор по TF
    m1 = next((r for r in tf_results if r.get("tf") == "M1"), None)
    m5 = next((r for r in tf_results if r.get("tf") == "M5"), None)
    m15 = next((r for r in tf_results if r.get("tf") == "M15"), None)

    dirs = [r["direction"] for r in tf_results]
    buy_count = dirs.count("BUY")
    sell_count = dirs.count("SELL")

    overall = "NONE"

    # 1) Для частых сигналов — главное направление М1
    if m1 and m1["direction"] in ("BUY", "SELL"):
        overall = m1["direction"]
    # 2) Если М1 дал NONE — голосование TF
    elif buy_count > sell_count:
        overall = "BUY"
    elif sell_count > buy_count:
        overall = "SELL"
    else:
        overall = "NONE"

    # --------- Волатильность по M1 (как в Colab) ---------
    df_vol, err_vol = get_tv_series(pair, "1min", 50)
    if df_vol is not None and not df_vol.empty:
        vol_df = df_vol.copy()
        volatility = vol_df["close"].diff().abs().tail(10).mean()
    else:
        # дефолт, как в ноутбуке
        volatility = 0.0004

    # --------- Экспирация (как в Colab) ---------
    expiry: int | None = None
    if prob >= 85:
        if volatility > 0.0007:
            expiry = 3
        elif volatility > 0.0004:
            expiry = 3
        else:
            expiry = 3
    elif prob >= 75:
        if volatility > 0.0007:
            expiry = 4
        elif volatility > 0.0004:
            expiry = 4
        else:
            expiry = 4
    elif prob >= 68:
        if volatility > 0.0007:
            expiry = 4
        else:
            expiry = 4
    else:
        # слабый сигнал — лучше не входить
        expiry = None

    # --------- WICK ENTRY (точный вход по хвосту свечи) ---------
    entry_price: float | None = None
    try:
        # берём последние 3 свечи M1 для точного входа
        df_1m, _ = get_tv_series(pair, "1min", 3)

        if df_1m is not None and not df_1m.empty and overall in ("BUY", "SELL"):
            last = df_1m.iloc[-1]
            high = float(last["high"])
            low = float(last["low"])
            close = float(last["close"])

            # m1-индикаторы (развороты / rejection) уже посчитаны в score_on_tf
            # и лежат в dict m1 (ровно как в Colab)
            if m1 is None:
                # если по какой-то причине M1-индикатор не найден – fallback
                entry_price = close
            else:
                # Используем хвост в зависимости от направления
                if overall == "BUY":
                    # Если хвост длинный (разворот снизу)
                    if m1.get("reversal_up", False) or m1.get("rejection_up", False):
                        # вход на low (нижний фитиль)
                        entry_price = low
                    else:
                        # обычный сигнал — среднее между low и close
                        entry_price = (low + close) / 2.0

                elif overall == "SELL":
                    if m1.get("reversal_down", False) or m1.get("rejection_down", False):
                        # вход на high (верхний фитиль)
                        entry_price = high
                    else:
                        entry_price = (high + close) / 2.0
        else:
            # если свечей мало или нет направления
            entry_price = last_close_1m

    except Exception:
        entry_price = last_close_1m

    # Дополнительный fallback — если всё равно None
    if entry_price is None:
        df1, _ = get_tv_series(pair, "1min", 5)
        if df1 is not None and not df1.empty:
            entry_price = float(df1["close"].iloc[-1])

    # --------- Логирование сигнала (как в Colab) ---------
    if overall != "NONE" and expiry and m1 is not None:
        indicators = {
            "ema20": m1.get("ema20"),
            "macd_diff": m1.get("macd_diff"),
            "macd_vote": m1.get("macd_vote"),
            "rsi": m1.get("rsi"),
            "rsi_vote": m1.get("rsi_vote"),
            "rsi_pro_active": m1.get("rsi_pro_active"),
            "impulse": m1.get("impulse"),
            "pattern": m1.get("pattern"),
            "reversal_up": m1.get("reversal_up"),
            "reversal_down": m1.get("reversal_down"),
            "div_buy": m1.get("div_buy"),
            "div_sell": m1.get("div_sell"),
            "near_support": m1.get("near_support"),
            "near_resistance": m1.get("near_resistance"),
            # SMC-поля — тоже есть в score_on_tf и логере
            "smc_type": m1.get("smc_type"),
            "smc_strength": m1.get("smc_strength"),
        }

        log_signal(
            pair,
            overall,
            prob,
            expiry,
            entry_price if entry_price else 0.0,
            indicators,
        )
        
    res = {
        "pair": pair,
        "dir": overall,
        "prob": prob,
        "expiry": expiry,
        "entry_price": entry_price,
    }
    return res, None


# --------- helper для времени в заголовке панели (как в Colab) ---------
def current_utc_str() -> str:
    return datetime.now(timezone.utc).strftime("%H:%M UTC")
