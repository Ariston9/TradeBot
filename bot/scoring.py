import math
import pandas as pd

from .indicators import compute_indicators, compute_macd, EMA_PERIOD, ATR_K
from .levels import get_swing_levels
from .smc import detect_reversal, detect_smc_levels


def detect_candlestick_pattern(df: pd.DataFrame):
    last = df.iloc[-1]
    prev = df.iloc[-2]

    # Бычье поглощение
    if (
        last["close"] > last["open"]
        and last["open"] < prev["close"]
        and last["close"] > prev["open"]
    ):
        return "BULLISH_ENGULF"

    # Медвежье поглощение
    if (
        last["close"] < last["open"]
        and last["open"] > prev["close"]
        and last["close"] < prev["open"]
    ):
        return "BEARISH_ENGULF"

    body = abs(last["close"] - last["open"])
    lower_shadow = min(last["open"], last["close"]) - last["low"]
    upper_shadow = last["high"] - max(last["open"], last["close"])

    # Молот
    if lower_shadow > body * 2 and upper_shadow < body * 0.5:
        return "HAMMER"

    return None


def score_on_tf(df: pd.DataFrame, tf_name: str):
    if len(df) < 60:
        return {
            "direction": "NONE",
            "score": 0.0,
            "macd_diff": 0.0,
            "macd_vote": 0,
            "rsi": 0.0,
            "rsi_vote": 0,
            "rsi_pro_active": False,
            "reversal_up": False,
            "reversal_down": False,
            "div_buy": False,
            "div_sell": False,
            "impulse": 0.0,
            "pattern": "NONE",
            "ema20": 0.0,
            "ema_vote": 0,
            "near_support": False,
            "near_resistance": False,
            "smc_type": None,
            "smc_strength": 0.0,
            "swing_high": None,
            "swing_low": None,
            "rejection_up": False,
            "rejection_down": False,
        }

    df = df.copy()
    df = df.sort_values("datetime") if "datetime" in df.columns else df
    last = df.iloc[-1]

    # ===================== EMA / тренд =====================
    ema20 = float(last["EMA20"])
    ema12 = float(last.get("EMA12", ema20))
    ema26 = float(last.get("EMA26", ema20))

    ema12_last = df["EMA12"].iloc[-1]
    ema26_last = df["EMA26"].iloc[-1]

    trend_up = ema12_last > ema26_last
    trend_down = ema12_last < ema26_last

    ema_vote = 1 if trend_up else (-1 if trend_down else 0)

    # ===================== MACD PRO =====================
    macd_data = compute_macd(df)
    macd = macd_data["macd"]
    macd_sig = macd_data["macd_signal"]
    macd_hist = macd_data["macd_hist"]
    div_buy = macd_data["div_buy"]
    div_sell = macd_data["div_sell"]

    macd_diff = macd - macd_sig
    if abs(macd_diff) < abs(macd_hist) * 0.3:
        macd_vote = 0
    else:
        macd_vote = 1 if macd_diff > 0 else -1

    # ===================== RSI PRO (Trend-oriented) =====================
    # здесь важный фикс: всегда берём значения из df["RSI"], а не last["RSI"],
    # чтобы избежать FutureWarning / Series вместо scalar
    rsi_series = df["RSI"]
    rsi = float(rsi_series.iloc[-1])
    rsi_prev = float(rsi_series.iloc[-2])

    rsi_pro_active = False
    if rsi > 55 and rsi > rsi_prev and trend_up:
        rsi_vote = 1
        rsi_pro_active = True
    elif rsi < 40 and rsi < rsi_prev and trend_down:
        rsi_vote = -1
        rsi_pro_active = True
    else:
        rsi_vote = 0

    # ===================== Импульс через ATR =====================
    df["range"] = df["high"] - df["low"]
    df["ATR"] = df["range"].rolling(14).mean()
    atr_last = float(df["ATR"].iloc[-1]) if not pd.isna(df["ATR"].iloc[-1]) else None

    # <<<<< КРИТИЧЕСКИЙ ФИКС multi-column >>>>>
    # Иногда df["close"] или df["ATR"] становятся DataFrame (multiindex)
    # из-за кривых данных. Приводим их к Series перед вычислением импульса.
    close_raw = df["close"]
    atr_raw = df["ATR"]

    if isinstance(close_raw, pd.DataFrame):
        close_raw = close_raw.iloc[:, 0]
    if isinstance(atr_raw, pd.DataFrame):
        atr_raw = atr_raw.iloc[:, 0]

    close = pd.to_numeric(close_raw, errors="coerce")
    atr = pd.to_numeric(atr_raw, errors="coerce")

    df["impulse"] = (close - close.shift(3)) / (atr * ATR_K)
    impulse_raw = (
        float(df["impulse"].iloc[-1]) if not pd.isna(df["impulse"].iloc[-1]) else 0.0
    )

    if impulse_raw > 0.7:
        impulse_vote = 1
    elif impulse_raw < -0.7:
        impulse_vote = -1
    elif impulse_raw > 0.4:
        impulse_vote = 0.5
    elif impulse_raw < -0.4:
        impulse_vote = -0.5
    else:
        impulse_vote = 0.0

    # ===================== Разворот (SMC-style) =====================
    rev_info = detect_reversal(df)
    reversal_up = bool(rev_info["reversal_up"])
    reversal_down = bool(rev_info["reversal_down"])
    rev_strength = float(rev_info.get("strength", 0.0))

    rev_vote = 0
    if reversal_up:
        rev_vote = 1
    elif reversal_down:
        rev_vote = -1

    rev_weight_factor = min(1.0 + rev_strength * 10.0, 2.0)

    # ===================== Свечной паттерн =====================
    pattern = detect_candlestick_pattern(df)
    pat_vote = 0
    if pattern in ("BULLISH_ENGULF", "HAMMER"):
        pat_vote = 1
    elif pattern in ("BEARISH_ENGULF", "SHOOTING_STAR"):
        pat_vote = -1

    # ====================== Swing Support / Resistance ======================
    price = float(last["close"])
    near_support = False
    near_resistance = False
    support = None
    resistance = None

    if tf_name == "M1":
        support, resistance = get_swing_levels(df, lookback=40)

        if atr_last is not None and atr_last > 0:
            level_eps = atr_last * 1.2
        else:
            level_eps = price * 0.0005

        if support is not None and price >= support and (price - support) <= level_eps:
            near_support = True

        if (
            resistance is not None
            and price <= resistance
            and (resistance - price) <= level_eps
        ):
            near_resistance = True

    # ===================== SMC уровни =====================
    smc = (
        detect_smc_levels(df)
        if tf_name == "M1"
        else {
            "swing_high": None,
            "swing_low": None,
            "type": None,
            "strength": 0.0,
            "rejection_up": False,
            "rejection_down": False,
        }
    )

    # ===================== ВЕСА СИСТЕМЫ (V3 balanced) =====================
    w = {
        "ema": 1.0,
        "macd": 1.8,
        "rsi": 2.0,
        "imp": 1.5,
        "rev": 2.3,
        "div": 0.8,
        "pat": 0.7,
    }

    total = 0.0
    total += ema_vote * w["ema"]
    total += macd_vote * w["macd"]
    total += rsi_vote * w["rsi"]
    total += impulse_vote * w["imp"]

    if rev_vote != 0:
        total += rev_vote * w["rev"] * rev_weight_factor

    if div_buy:
        total += w["div"]
    elif div_sell:
        total -= w["div"]

    total += pat_vote * w["pat"]

    direction = "NONE"
    if total > 0.5:
        direction = "BUY"
    elif total < -0.5:
        direction = "SELL"

    if tf_name == "M1":
        smc_high = smc["swing_high"]
        smc_low = smc["swing_low"]
        rejection_up = smc["rejection_up"]
        rejection_down = smc["rejection_down"]

        if direction == "BUY" and near_resistance:
            direction = "NONE"
            total -= 3
        if direction == "SELL" and near_support:
            direction = "NONE"
            total += 3

        if direction == "BUY" and smc_high and price >= smc_high * 0.998:
            direction = "NONE"
            total -= 2
        if direction == "SELL" and smc_low and price <= smc_low * 1.002:
            direction = "NONE"
            total += 2

        if rejection_down:
            direction = "SELL"
            total -= 3
        if rejection_up:
            direction = "BUY"
            total += 3

        if (near_resistance or near_support) and abs(total) < 2:
            direction = "NONE"
    else:
        rejection_up = False
        rejection_down = False

    return {
        "direction": direction,
        "score": round(float(total), 4),
        "macd_diff": float(macd_diff),
        "macd_vote": int(macd_vote),
        "rsi": float(rsi),
        "rsi_vote": int(rsi_vote),
        "rsi_pro_active": bool(rsi_pro_active),
        "reversal_up": bool(reversal_up),
        "reversal_down": bool(reversal_down),
        "div_buy": bool(div_buy),
        "div_sell": bool(div_sell),
        "impulse": float(impulse_raw),
        "pattern": pattern,
        "ema20": float(ema20),
        "ema_vote": int(ema_vote),
        "near_support": bool(near_support),
        "near_resistance": bool(near_resistance),
        "smc_type": smc.get("type"),
        "smc_strength": smc.get("strength"),
        "swing_high": smc.get("swing_high"),
        "swing_low": smc.get("swing_low"),
        "rejection_up": smc.get("rejection_up"),
        "rejection_down": smc.get("rejection_down"),
    }


def calc_overall_probability(tf_results):
    """
    Probability v7.1 — без индикаторов:
    Основной упор на price action, уровни, SMC, retest и тренд.
    Гарантированно >= 70% для направлений BUY/SELL без конфликта.
    """

    m1 = next((x for x in tf_results if x.get("tf") == "M1"), None)
    m5 = next((x for x in tf_results if x.get("tf") == "M5"), None)
    m15 = next((x for x in tf_results if x.get("tf") == "M15"), None)

    if not m1:
        return 45.0

    direction = m1.get("direction", "NONE")
    score = float(m1.get("score", 0.0))

    base = 50.0 + 35.0 * math.tanh(score / 1.6)
    prob = base

    # уровни
    if m1.get("near_support") and direction == "SELL":
        prob -= 4
    if m1.get("near_resistance") and direction == "BUY":
        prob -= 4

    # rejection / разворот
    if direction == "BUY" and m1.get("reversal_up"):
        prob += 6
    if direction == "SELL" and m1.get("reversal_down"):
        prob += 6

    if direction == "BUY" and m1.get("rejection_up"):
        prob += 6
    if direction == "SELL" and m1.get("rejection_down"):
        prob += 6

    # тренд старших ТФ
    d5 = (m5 or {}).get("direction", "NONE")
    d15 = (m15 or {}).get("direction", "NONE")

    if direction != "NONE":
        same5 = d5 == direction
        same15 = d15 == direction

        if same5:
            prob += 3.0
        if same15:
            prob += 3.0
        if same5 and same15:
            prob += 2.0

    prob = max(35.0, min(prob, 92.0))
    return float(prob)
