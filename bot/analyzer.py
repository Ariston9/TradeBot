# bot/analyzer.py (версия с мягкой интеграцией PO Streaming v10)
import time
from datetime import datetime, timezone
from typing import Optional, Tuple

import pandas as pd
import requests

from bot.config import TFS, MAX_CANDLES, REQUEST_DELAY
from .tv_api import get_tv_series
from .indicators import compute_indicators
from .scoring import score_on_tf, calc_overall_probability
from .logger import log_signal


# --- опциональные объекты для PO Streaming Engine ---------------------

# Маппинг пар WOG -> символы PO Engine, и базовый HTTP-URL
try:
    # ОЖИДАЕТСЯ, что ты добавишь это в config.py, например:
    # PO_SYMBOL_MAP = {
    #     "EUR/USD": "EURUSD",
    #     "GBP/USD": "GBPUSD",
    #     "OTC_EURUSD": "EURUSD_otc",
    #     ...
    # }
    # PO_ENGINE_HTTP = "http://127.0.0.1:9001"
    from .config import PO_SYMBOL_MAP, PO_ENGINE_HTTP  # type: ignore
except Exception:
    PO_SYMBOL_MAP = {}
    PO_ENGINE_HTTP = None

# Живая цена от PO Streaming v10 (заполняется в pocket_po_feed.py)
try:
    from .pocket_po_feed import CURRENT_PO_PRICE  # type: ignore
except Exception:
    CURRENT_PO_PRICE = {}


# -------------------- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ -------------------------


def is_otc_pair(pair: str) -> bool:
    """
    Простая эвристика: OTC-пары начинаются с 'OTC' (например 'OTC_EURUSD').
    """
    return pair.upper().startswith("OTC")


def map_pair_to_po_symbol(pair: str) -> str:
    """
    Преобразование пары WOG -> символ в PO Streaming Engine.

    Порядок:
    1) если есть в PO_SYMBOL_MAP — используем его
    2) иначе:
       - 'EUR/USD' -> 'EURUSD'
       - 'OTC_EURUSD' -> 'EURUSD_otc'
    """
    if PO_SYMBOL_MAP and pair in PO_SYMBOL_MAP:
        return PO_SYMBOL_MAP[pair]

    p = pair.replace("/", "")  # 'EUR/USD' -> 'EURUSD', 'OTC_EURUSD' -> 'OTC_EURUSD'
    up = p.upper()

    # OTC_EURUSD / OTC-EURUSD / OTCEURUSD → EURUSD_otc
    if up.startswith("OTC_"):
        core = p[4:]
        return core + "_otc"
    if up.startswith("OTC"):
        core = p[3:]
        return core + "_otc"

    return p  # обычная биржевая пара, типа EURUSD


def fetch_po_candles(pair: str, tf_name: str, limit: int) -> Tuple[Optional[pd.DataFrame], Optional[str]]:
    """
    Получение свечей из PO Streaming Engine для пары (в т.ч. OTC).
    Ожидается эндпоинт:  GET {PO_ENGINE_HTTP}/candles?symbol=...&tf=M1&limit=...
    """
    if not PO_ENGINE_HTTP:
        return None, "PO Streaming Engine не настроен (PO_ENGINE_HTTP = None)"

    symbol = map_pair_to_po_symbol(pair)
    tf_param = tf_name.upper()  # 'M1', 'M5', 'M15', 'M30'

    try:
        r = requests.get(
            f"{PO_ENGINE_HTTP}/candles",
            params={"symbol": symbol, "tf": tf_param, "limit": limit},
            timeout=2.5,
        )
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        return None, f"Ошибка запроса к PO Streaming Engine: {e}"

    if not data:
        return None, f"Нет свечей PO для {pair}"

    df = pd.DataFrame(data)
    if "time" not in df.columns:
        return None, "Неверный формат свечей PO (нет поля 'time')"

    df["datetime"] = pd.to_datetime(df["time"], utc=True, errors="coerce")
    df = df.dropna(subset=["datetime"])

    for col in ("open", "high", "low", "close"):
        if col not in df.columns:
            return None, f"Неверный формат свечей PO (нет '{col}')"
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.dropna(subset=["open", "high", "low", "close"])
    if df.empty:
        return None, "Нет валидных свечей PO"

    # Приводим формат к такому же, как у get_tv_series
    df["dt_utc"] = df["datetime"]
    df["time"] = df["datetime"].astype("int64") // 10**9

    return df.tail(limit), None


def get_live_po_price(pair: str) -> Optional[float]:
    """
    Возвращает живую цену пары из CURRENT_PO_PRICE, если она есть.
    Поддерживает как формат {'price': ..}, так и {'mid': .., 'bid': .., 'ask': ..}.
    """
    if not CURRENT_PO_PRICE:
        return None

    symbol = map_pair_to_po_symbol(pair)
    tick = CURRENT_PO_PRICE.get(symbol)
    if not tick:
        return None

    # словарь разных форматов
    if isinstance(tick, dict):
        if "price" in tick:
            try:
                return float(tick["price"])
            except Exception:
                pass
        if "mid" in tick:
            try:
                return float(tick["mid"])
            except Exception:
                pass
        bid = tick.get("bid")
        ask = tick.get("ask")
        if bid is not None and ask is not None:
            try:
                return (float(bid) + float(ask)) / 2.0
            except Exception:
                pass

    # крайний случай
    try:
        return float(tick)
    except Exception:
        return None


def check_market_open(df: pd.DataFrame):
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
    except Exception:
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


# -------------------- ОСНОВНОЙ АНАЛИЗ --------------------


async def analyze_pair_for_user(user_id: int, pair: str):
    """
    Основной анализ одной пары для панели.

    ВАЖНО:
    - Для биржевых пар по умолчанию используем данные Yahoo (get_tv_series).
    - Для OTC-пар (начинаются с 'OTC') при наличии PO_ENGINE_HTTP —
      берём свечи из PO Streaming Engine (PO Streaming v10).
    - WICK ENTRY дополнен живой ценой от PO Streaming Engine (CURRENT_PO_PRICE).
    """

    tf_results: list[dict] = []
    last_close_1m: float | None = None

    # --------- Сбор индикаторов по всем TF ---------
    for tf_name, tf_int in TFS.items():  # {"M1":"1min","M5":"5min",...}
        # OTC → попытка взять свечи из PO Streaming Engine
        if is_otc_pair(pair):
            df_tf, err = fetch_po_candles(pair, tf_name, MAX_CANDLES)
            # для PO нет смысла спамить time.sleep
        else:
            df_tf, err = get_tv_series(pair, tf_int, MAX_CANDLES)
            time.sleep(REQUEST_DELAY)

        if df_tf is None:
            # Если ошибка "рынок закрыт" / "нет котировок" и т.п. — сразу отдаём её наверх
            if isinstance(err, dict) and "error" in err:
                return None, err["error"]
            if isinstance(err, str):
                return None, err
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

        # запоминаем последний close на M1 (fallback для entry_price)
        if tf_int == "1min":
            last_close_1m = float(df_tf["close"].iloc[-1])

    if not tf_results:
        return None, f"Нет данных для {pair}. Проверь подключение к источнику котировок."

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
    if is_otc_pair(pair):
        df_vol, err_vol = fetch_po_candles(pair, "M1", 50)
    else:
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

    # --------- WICK ENTRY + живая цена PO ---------
    entry_price: float | None = None
    live_po_price = get_live_po_price(pair)

    try:
        # берём последние 3 свечи M1 для точного входа
        if is_otc_pair(pair):
            df_1m, _ = fetch_po_candles(pair, "M1", 3)
        else:
            df_1m, _ = get_tv_series(pair, "1min", 3)

        if df_1m is not None and not df_1m.empty and overall in ("BUY", "SELL"):
            df_1m = df_1m.sort_values("datetime")
            last = df_1m.iloc[-1]
            high = float(last["high"])
            low = float(last["low"])
            close = float(last["close"])

            # m1-индикаторы (развороты / rejection) уже посчитаны в score_on_tf
            if m1 is None:
                base_price = close
            else:
                if overall == "BUY":
                    # Если хвост снизу (разворот/отбой) — приоритет low
                    if m1.get("reversal_up", False) or m1.get("rejection_up", False):
                        base_price = low
                    else:
                        base_price = (low + close) / 2.0
                else:  # SELL
                    if m1.get("reversal_down", False) or m1.get("rejection_down", False):
                        base_price = high
                    else:
                        base_price = (high + close) / 2.0

            # Смешиваем wick-entry и живую цену PO:
            # BUY → хотим более выгодный вход ниже
            # SELL → хотим вход выше
            if overall == "BUY":
                if live_po_price is not None:
                    entry_price = min(base_price, live_po_price)
                else:
                    entry_price = base_price
            elif overall == "SELL":
                if live_po_price is not None:
                    entry_price = max(base_price, live_po_price)
                else:
                    entry_price = base_price

        else:
            # если свечей мало или нет направления
            if live_po_price is not None:
                entry_price = live_po_price
            else:
                entry_price = last_close_1m

    except Exception:
        # если что-то пошло не так в блоке выше
        if live_po_price is not None:
            entry_price = live_po_price
        else:
            entry_price = last_close_1m

    # Дополнительный fallback — если всё равно None
    if entry_price is None:
        if live_po_price is not None:
            entry_price = live_po_price
        else:
            df1, _ = (fetch_po_candles(pair, "M1", 5) if is_otc_pair(pair)
                      else get_tv_series(pair, "1min", 5))
            if df1 is not None and not df1.empty:
                df1 = df1.sort_values("datetime")
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
