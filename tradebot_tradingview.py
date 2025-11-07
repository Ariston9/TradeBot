# -*- coding: utf-8 -*-

# ================== Trade Assistant v6.1 (Single-Message UI) ==================
import nest_asyncio
nest_asyncio.apply()

import asyncio, time, os, math
from io import BytesIO
from datetime import datetime, timedelta, timezone

import requests
import pandas as pd
import matplotlib.pyplot as plt
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from tvDatafeed import TvDatafeed, Interval
import getpass
import numpy as np


# ---------- ВСТАВЬ СВОИ КЛЮЧИ ----------
BOT_TOKEN = "8211755249:AAGoETITOWaFowqh1AQXjzRqwsiFrV4bBb0"
API_KEY   = "24e4b8641e37437a80c42cb7c0949fe1"
# --- логин TradingView (лучше руками вводить, чтобы не хранить в коде) ---
tv = TvDatafeed(username='bugona10@gmail.com', password='abGY3vAW2t1012')

# TV_USER = input("bugona10@gmail.com ")
# TV_PASS = getpass.getpass()

PAIRS = ["EUR/USD","EUR/GBP","EUR/AUD","EUR/JPY","EUR/CHF","EUR/CAD","GBP/USD","GBP/CAD","GBP/AUD","GBP/CHF","USD/JPY","USD/CAD","USD/CHF","AUD/USD","AUD/JPY","AUD/CAD","AUD/CHF","CAD/JPY","CAD/CHF","NZD/USD"]
TFS = {"M1":"1min","M5":"5min","M15":"15min"}
MAX_CANDLES = 120
REQUEST_DELAY = 0.9
LOG_FILE = "signals.csv"
CLEAN_DAYS = 3
# Для форекса в TradingView чаще всего подходит обмен FX_IDC
# (если у тебя другой провайдер — замени 'FX_IDC' на нужный).
TV_MAP = {
    "EUR/USD": ("EURUSD","OANDA"),
    "EUR/GBP": ("EURGBP","OANDA"),
    "EUR/AUD": ("EURAUD","OANDA"),
    "EUR/JPY": ("EURJPY","OANDA"),
    "EUR/CHF": ("EURCHF","OANDA"),
    "EUR/CAD": ("EURCAD","OANDA"),

    "GBP/USD": ("GBPUSD","FX_IDC"),
    "GBP/CAD": ("GBPCAD","FX_IDC"),
    "GBP/AUD": ("GBPAUD","FX_IDC"),
    "GBP/CHF": ("GBPCHF","FX_IDC"),

    "USD/JPY": ("USDJPY","FX_IDC"),
    "USD/CAD": ("USDCAD","FX_IDC"),
    "USD/CHF": ("USDCHF","FX_IDC"),

    "AUD/USD": ("AUDUSD","FX_IDC"),
    "AUD/JPY": ("AUDJPY","FX_IDC"),
    "AUD/CAD": ("AUDCAD","FX_IDC"),
    "AUD/CHF": ("AUDCHF","FX_IDC"),

    "CAD/JPY": ("CADJPY","FX_IDC"),
    "CAD/CHF": ("CADCHF","FX_IDC"),

    "NZD/USD": ("NZDUSD","FX_IDC"),
}

def tv_chart_url(pair:str) -> str:
    sym, ex = TV_MAP[pair]
    # формат TradingView: /chart/?symbol=EXCHANGE:SYMBOL
    return f"https://www.tradingview.com/chart/?symbol={ex}:{sym}"

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# one-panel state per user
SESS = {}  # user_id: {"pair": str, "panel_msg_id": int}

# init log
if not os.path.exists(LOG_FILE):
    pd.DataFrame(columns=["timestamp_utc","pair","direction","probability",
                          "expiry_min","entry_price","evaluated","result"]
                ).to_csv(LOG_FILE, index=False)

API_URL = "https://example.com"  # временная заглушка, чтобы избежать NameError

# ===== Strategy V2: tuning =====
EMA_PERIOD        = 14     # EMA для направления (быстрее 20)
RSI_BUY           = 55     # мягкие границы, но решение по "выходу из зоны"
RSI_SELL          = 45
RSI_MID           = 50     # порог выхода из зоны
RSI_PERIOD        = 9      # чувствительность RSI

MACD_FAST         = 8      # быстрая EMA
MACD_SLOW         = 21     # медленная EMA
MACD_SIGNAL        = 5     # сигнальная EMA

IMPULSE_N         = 3     # длина окна импульса (свечей), чем больше тем меньше шумов
ATR_K             = 0.4    # чувствительность импульса: порог = ATR * ATR_K

FLAT_WINDOW       = 14     # окно оценки флэта (ATR/close)
FLAT_TR_PCT       = 0.0006 # если ATR/close < этого порога → флэт

SR_LOOKBACK       = 120    # сколько свечей для S/R на старшем ТФ
SR_PIVOT_WIN      = 2      # ширина локальных экстремумов для уровней
SR_MERGE_TOL_PCT  = 0.0008 # слияние близких уровней (0.08%)
SR_NEAR_PCT       = 0.0006 # близость цены к уровню (+/- 0.06%)

PROB_THRESHOLD    = 70     # минимум вероятности для сигнала
M5_CONFIRM_REQ    = True   # требовать подтверждение M5
M15_TREND_FILTER  = False  # фильтровать против тренда M15


# -------------------- data & indicators --------------------
INTERVAL_MAP = {
    "1min":  Interval.in_1_minute,
    "5min":  Interval.in_5_minute,
    "15min": Interval.in_15_minute,
}

def get_tv_series(pair: str, interval: str = "5min", n_bars: int = 300):
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


# ---- RSI helper ----
def compute_rsi(series: pd.Series, period: int = 14):
    delta = series.diff()
    up = delta.clip(lower=0)
    down = -delta.clip(upper=0)
    ma_up = up.ewm(com=period - 1, adjust=False).mean()
    ma_down = down.ewm(com=period - 1, adjust=False).mean()
    rs = ma_up / ma_down
    return 100 - (100 / (1 + rs))


def compute_indicators(df: pd.DataFrame):
    df["EMA20"] = df["close"].ewm(span=EMA_PERIOD, adjust=False).mean()
    df["EMA12"] = df["close"].ewm(span=MACD_FAST, adjust=False).mean()
    df["EMA26"] = df["close"].ewm(span=MACD_SLOW, adjust=False).mean()
    df["MACD"] = df["EMA12"] - df["EMA26"]
    df["MACD_sig"] = df["MACD"].ewm(span=MACD_SIGNAL, adjust=False).mean()
    return df


# ===================== SCORE + ADAPTIVE INDICATORS + SR-детектор (поддержка/сопротивление)=====================

def rsi_exit_signal(prev_rsi: float, last_rsi: float) -> int:
    # 1 при пересечении вверх 50, -1 при пересечении вниз 50, иначе 0
    if last_rsi > RSI_MID and prev_rsi <= RSI_MID:
        return 1
    if last_rsi < RSI_MID and prev_rsi >= RSI_MID:
        return -1
    return 0

def impulse_vote_v2(df: pd.DataFrame, n: int = IMPULSE_N, atr_k: float = ATR_K) -> tuple[int, float]:
    # momentum = среднее dClose за N свечей; порог = ATR * atr_k
    if len(df) < max(20, n+1):
        return 0, 0.0
    mom = df["close"].diff().tail(n).mean()
    atr = (df["high"] - df["low"]).rolling(14).mean().iloc[-1]
    thr = max(1e-12, atr * atr_k)
    if mom > thr:  return 1, mom
    if mom < -thr: return -1, mom
    return 0, mom

def is_flat_v2(df: pd.DataFrame) -> bool:
    # Флэт, если относительный ATR мал
    if len(df) < FLAT_WINDOW + 1:
        return False
    rng = (df["high"] - df["low"]).rolling(FLAT_WINDOW).mean().iloc[-1]
    price = float(df["close"].iloc[-1])
    return (rng / price) < FLAT_TR_PCT

def detect_sr_levels(df: pd.DataFrame, pivot_win: int = SR_PIVOT_WIN,
                     merge_tol_pct: float = SR_MERGE_TOL_PCT) -> list[float]:
    # Простые уровни: локальные экстремумы с слиянием близких
    if len(df) < 2*pivot_win+3:
        return []
    highs = df["high"].values
    lows  = df["low"].values
    lvls = []

    # swing highs
    for i in range(pivot_win, len(df)-pivot_win):
        if highs[i] == max(highs[i-pivot_win:i+pivot_win+1]):
            lvls.append(highs[i])
    # swing lows
    for i in range(pivot_win, len(df)-pivot_win):
        if lows[i] == min(lows[i-pivot_win:i+pivot_win+1]):
            lvls.append(lows[i])

    lvls.sort()
    merged = []
    for x in lvls:
        if not merged:
            merged.append(x)
        else:
            if abs(x - merged[-1]) / merged[-1] <= merge_tol_pct:
                merged[-1] = (merged[-1] + x) / 2.0
            else:
                merged.append(x)
    return merged

def sr_conflict(signal_dir: str, price: float, levels: list[float], near_pct: float = SR_NEAR_PCT) -> bool:
    """Возвращает True, если сигнал конфликтует с близким уровнем:
       BUY в упор к сопротивлению или SELL в упор к поддержке."""
    if not levels:
        return False
    for L in levels:
        if abs(price - L)/price <= near_pct:
            if signal_dir == "BUY"  and L < price:  # над ценой? (сопротивление) → конфликт если очень близко сверху
                continue
            if signal_dir == "BUY"  and L >= price: # сопротивление над ценой
                return True
            if signal_dir == "SELL" and L > price:  # под ценой? (поддержка) → конфликт если очень близко снизу
                continue
            if signal_dir == "SELL" and L <= price: # поддержка под ценой
                return True
    return False

def score_on_tf(df: pd.DataFrame):
    if df is None or df.empty or len(df) < 20:
        return {
            "direction": "NONE", "score": 0.0, "macd_diff": 0.0,
            "reversal_up": False, "reversal_down": False,
            "div_buy": False, "div_sell": False,
            "impulse": 0.0, "pattern": None,
            "ema20": None, "rsi": None
        }

    # Индикаторы (RSI_PERIOD уже задан выше)
    if "MACD" not in df.columns or "MACD_sig" not in df.columns:
       df = compute_indicators(df)
    df["RSI14"]    = compute_rsi(df["close"], RSI_PERIOD)

    last = df.iloc[-1]
    prev = df.iloc[-2]

    # # --- Развороты ---
    # local_min = df["low"].iloc[-3] < df["low"].iloc[-2] and df["low"].iloc[-3] < df["low"].iloc[-4]
    # local_max = df["high"].iloc[-3] > df["high"].iloc[-2] and df["high"].iloc[-3] > df["high"].iloc[-4]
    # reversal_up = local_min and df["close"].iloc[-1] > df["high"].iloc[-2]
    # reversal_down = local_max and df["close"].iloc[-1] < df["low"].iloc[-2]

    # # ✅ Подтверждение разворота — пробой + размер свечи > средней амплитуды
    # df["range"] = df["high"] - df["low"]
    # avg_range = df["range"].tail(10).mean()
    # reversal_confirm = False
    # if reversal_up and (last["close"] > df["high"].iloc[-2]) and ((last["high"] - last["low"]) > avg_range * 1.2):
    #     reversal_confirm = True
    # elif reversal_down and (last["close"] < df["low"].iloc[-2]) and ((last["high"] - last["low"]) > avg_range * 1.2):
    #     reversal_confirm = True
    # # --- MACD дивергенции ---
    # df["hist_min"] = (df["MACD_hist"] < df["MACD_hist"].shift(1)) & (df["MACD_hist"] < df["MACD_hist"].shift(-1))
    # df["hist_max"] = (df["MACD_hist"] > df["MACD_hist"].shift(1)) & (df["MACD_hist"] > df["MACD_hist"].shift(-1))
    # last_mins = df.loc[df["hist_min"], "MACD_hist"].tail(2)
    # last_maxs = df.loc[df["hist_max"], "MACD_hist"].tail(2)
    # divergence_buy = len(last_mins) == 2 and last_mins.iloc[-1] > last_mins.iloc[-2]
    # divergence_sell = len(last_maxs) == 2 and last_maxs.iloc[-1] < last_maxs.iloc[-2]

    # # --- Паттерн ---
    # pattern = detect_candlestick_pattern(df)

    # Голоса
    ema_vote   =  1 if last["close"] > last["EMA20"] else -1
    macd_vote  =  1 if last["MACD"]  > last["MACD_sig"] else -1
    rsi_vote   = rsi_exit_signal(prev["RSI14"], last["RSI14"])  # выход из зоны
    imp_vote, momentum = impulse_vote_v2(df, IMPULSE_N, ATR_K)
    macd_diff = float(last["MACD"] - last["MACD_sig"])

    #----------MACD-наклон. Это убирает сигналы, когда MACD колеблется почти по горизонтали.

    macd_slope = df["MACD"].iloc[-1] - df["MACD"].iloc[-3]
    if abs(macd_slope) < 0.00003:  # слишком плоский MACD
       macd_vote = 0
    else:
       macd_vote = 1 if macd_diff > 0 else -1

    # RSI: покупка при выходе из перепроданности (а не просто выше порога)
    if last["RSI14"] < RSI_SELL:
       rsi_vote = -1
    elif last["RSI14"] > RSI_BUY:
       rsi_vote = 1
    else:
       rsi_vote = 0

    # Веса (сбалансированные)
    w_ema, w_macd, w_rsi, w_imp = 0, 0.8, 1.2, 2.4

    # Итоговый балл
    total = (ema_vote*w_ema) + (macd_vote*w_macd) + (rsi_vote*w_rsi) + (imp_vote*w_imp)
    direction = "BUY" if total > 0 else ("SELL" if total < 0 else "NONE")

    return {
        "direction": direction,
        "score": float(total),
        "macd_diff": macd_diff,
        "reversal_up": False, "reversal_down": False,  # (упростили в V2)
        "div_buy": False, "div_sell": False,          # (можно вернуть позже)
        "impulse": float(momentum),
        "pattern": None,
        "ema20": float(last["EMA20"]),
        "rsi": float(last["RSI14"])
    }

def calc_overall_probability(tf_results: list[dict]) -> float:
    if not tf_results:
        return 0.0
    # Нормируем по сумме модулей score (мягкая шкала)
    abs_sum = sum(abs(r.get("score", 0.0)) for r in tf_results)
    prob = 12.0 * abs_sum  # 1.0 очко ≈ 12%
    macd_avg = sum(abs(r.get("macd_diff", 0)) for r in tf_results) / max(1, len(tf_results))
    macd_strength = min(20.0, macd_avg * 1000.0)

    # Бонус за согласованность направлений
    dirs = [r.get("direction", "NONE") for r in tf_results]
    agree = max(dirs.count("BUY"), dirs.count("SELL"))
    if agree >= 2:
        prob += 8.0
    return round(max(0.0, min(prob, 99.0)), 1)

def log_signal(pair, direction, probability, expiry_min, entry_price, indicators=None):
    """
    Логирует сигнал с расширенными данными (для будущего обучения модели AI)
    """
    # Загружаем старый лог или создаём пустой
    try:
        df = pd.read_csv(LOG_FILE)
    except FileNotFoundError:
        df = pd.DataFrame()

    row = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "pair": pair,
        "direction": direction,
        "probability": probability,
        "expiry_min": expiry_min,
        "entry_price": entry_price,
        "evaluated": False,
        "result": ""
    }

    # --- Добавляем технические признаки (для обучения) ---
    if indicators:
        row.update({
            "ema20": indicators.get("ema20"),
            "macd": indicators.get("macd"),
            "rsi": indicators.get("rsi"),
            "impulse": indicators.get("impulse"),
            "pattern": indicators.get("pattern")
        })

    df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
    df.to_csv(LOG_FILE, index=False)

# -------------------- stats & chart --------------------
def evaluate_signal_entry(entry_row):
    try:
        t0 = pd.to_datetime(entry_row["timestamp_utc"]).tz_convert("UTC")
    except Exception:
        t0 = pd.to_datetime(entry_row["timestamp_utc"]).tz_localize("UTC")
    expiry = int(entry_row["expiry_min"])
    target = t0 + pd.Timedelta(minutes=expiry)
    df, err = get_tv_series(entry_row["pair"], "1min", 200)
    if df is None:
        return "ERROR", None, err
    times = df["dt_utc"]
    idx = times.searchsorted(target)
    price_at = df["close"].iloc[-1] if idx >= len(df) else df["close"].iloc[idx]
    res = "WIN" if (entry_row["direction"]=="BUY" and price_at>entry_row["entry_price"]) or \
                  (entry_row["direction"]=="SELL" and price_at<entry_row["entry_price"]) else "LOSE"
    return res, float(price_at), None

def stats_last_24h():
    df = pd.read_csv(LOG_FILE)
    if df.empty:
        return {"total":0,"wins":0,"losses":0,"winrate":0.0}
    now = datetime.now(timezone.utc)
    df["timestamp_utc"] = pd.to_datetime(df["timestamp_utc"])
    last24 = df[df["timestamp_utc"] >= (now - pd.Timedelta(hours=24))]
    wins = losses = evaluated = 0
    for _, row in last24.iterrows():
        if pd.isna(row["expiry_min"]): continue
        if row["timestamp_utc"] + pd.Timedelta(minutes=int(row["expiry_min"])) > now:
            continue
        res, _, _ = evaluate_signal_entry(row)
        if res=="WIN": wins+=1; evaluated+=1
        elif res=="LOSE": losses+=1; evaluated+=1
    winrate = round((wins/evaluated)*100,2) if evaluated>0 else 0.0
    return {"total": len(last24), "wins": wins, "losses": losses, "winrate": winrate}

def build_pie(wins, losses):
    if wins+losses==0: return None
    fig, ax = plt.subplots(figsize=(4,4))
    ax.pie([wins, losses], labels=["Плюс","Минус"], autopct='%1.0f%%',
           startangle=90, colors=['#4CAF50','#F44336'])
    ax.axis('equal')
    buf = BytesIO(); plt.savefig(buf, format='png', bbox_inches='tight'); buf.seek(0)
    plt.close(fig)
    return buf

# -------------------- keyboards --------------------
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

def kb_main(pair_selected: str | None):
    rows = []
    for i in range(0, len(PAIRS), 3):
        row = []
        for p in PAIRS[i:i + 3]:
            mark = "▪️" if p != pair_selected else "🔹"
            row.append(InlineKeyboardButton(text=f"{mark} {p}", callback_data=f"PAIR|{p}"))
        rows.append(row)

    if pair_selected:
        tv_symbol = pair_selected.replace("/", "")
        web_link = f"https://ariston9.github.io/TradeBot/chart.html?symbol={tv_symbol}"
        rows.append([
            InlineKeyboardButton(
                text="📈 Открыть график TradingView",
                web_app=WebAppInfo(url=web_link)
            )
        ])

    rows.append([
        InlineKeyboardButton(text="🔄 Обновить", callback_data="ACT|REFRESH"),
        InlineKeyboardButton(text="📊 Статистика", callback_data="ACT|STATS"),
        InlineKeyboardButton(
    text="📱 Открыть панель",
    web_app=WebAppInfo(
        url=f"https://ariston9.github.io/TradeBot/app.html?api={API_URL}")
      )
    ])

    return InlineKeyboardMarkup(inline_keyboard=rows)

# -------------------- panel text builders --------------------
def panel_text_header():
    return "📊 *Trade Assistant — Анализ рынка*\n\nВыбери валютную пару:"

def panel_text_analysis(pair, direction, prob, expiry, updated_str, price=None):
    dir_txt = (
        "Покупать ✅" if direction == "BUY"
        else ("Продавать 🔻" if direction == "SELL" else "Ожидание ⚪")
    )
    extra = f"\nЦена входа: {price:.5f}" if price is not None else ""

    text = (
        f"{panel_text_header()}\n\n"
        f"*Текущий анализ:* {pair}\n"
        f"{dir_txt}\n"
        f"🎯 Вероятность: *{prob}%*\n"
    )

    if expiry:
        text += f"⏱ Рекомендуемая экспирация: {expiry} мин\n"
    else:
        text += "⏱ Сигнал слабый — сделку не открывать\n"

    text += f"📅 Обновлено: {updated_str}{extra}"
    return text

def panel_text_stats():
    s = stats_last_24h()
    return (f"{panel_text_header()}\n\n"
            f"📈 *Статистика за 24 часа*\n"
            f"Всего сигналов: *{s['total']}*\n"
            f"Плюс: *{s['wins']}*\n"
            f"Минус: *{s['losses']}*\n"
            f"Проходимость: *{s['winrate']}%*")

# -------------------- core analysis (обновлённая мультифрейм-логика) --------------------
async def analyze_pair_for_user(user_id: int, pair: str):
    tf_data = {}
    last_close_1m = None

    # грузим M1/M5/M15
    for _, tf_int in TFS.items():
        df_tf, err = get_tv_series(pair, tf_int, MAX_CANDLES)
        time.sleep(REQUEST_DELAY)
        if df_tf is None or df_tf.empty:
            print(f"⚠️ Нет данных {pair} {tf_int}: {err}")
            continue
        df_tf = compute_indicators(df_tf)
        tf_data[tf_int] = score_on_tf(df_tf)
        if tf_int == "1min":
            last_close_1m = float(df_tf["close"].iloc[-1])

    if "1min" not in tf_data:
        return None, f"Нет данных M1 — невозможно анализировать {pair}."

    # Основной сигнал M1
    signal_m1 = tf_data["1min"]["direction"]

    # Подтверждение M5 и тренд-фильтр M15
    confirm_m5 = tf_data.get("5min", {}).get("direction", "NONE")
    filter_m15 = tf_data.get("15min", {}).get("direction", "NONE")

        # --- Основная вероятность только по M1 ---
    m1 = tf_data.get("1min")
    if not m1:
        return None, "Нет данных по M1."

    prob = min(99.9, abs(m1["score"]) * 22)  # сила сигнала по M1
    signal_m1 = m1["direction"]

    # --- Контекст старших ТФ ---
    confirm_m5 = tf_data.get("5min", {}).get("direction", "NONE")
    filter_m15 = tf_data.get("15min", {}).get("direction", "NONE")

    # --- Мягкая корректировка вероятности по старшим ТФ ---
    if confirm_m5 == signal_m1:
        prob += 8   # M5 подтверждает импульс
    elif confirm_m5 != "NONE" and confirm_m5 != signal_m1:
        prob -= 8  # M5 против — уменьшаем уверенность

    if filter_m15 != "NONE" and filter_m15 != signal_m1:
        prob -= 6  # M15 против тренда — фильтр

    prob = round(max(0, min(prob, 99.9)), 1)

    # --- Импульс 3–5 свечей на M1 ---
    df_imp, _ = get_tv_series(pair, "1min", 5)
    if df_imp is not None and len(df_imp) >= 5:
        price_change = (df_imp["close"].iloc[-1] - df_imp["close"].iloc[0]) / df_imp["close"].iloc[0]
        if abs(price_change) > 0.0006:  # импульс > 6 пунктов
            if price_change > 0 and signal_m1 == "BUY":
                prob += 6  # усиливаем BUY
            elif price_change < 0 and signal_m1 == "SELL":
                prob += 6  # усиливаем SELL
            else:
                prob *= 0.8  # против импульса — ослабляем

    prob = round(max(0, min(prob, 99.9)), 1)

    # --- Итоговое направление ---
    if signal_m1 != "NONE":
        overall = signal_m1
    elif confirm_m5 == filter_m15 != "NONE":
        overall = confirm_m5
    else:
        overall = "NONE"

    # Флэт-фильтр по M1
    df_m1, _ = get_tv_series(pair, "1min", 120)
    if df_m1 is not None and not df_m1.empty and is_flat_v2(df_m1):
        prob = max(0.0, prob - 15.0)
        if prob < PROB_THRESHOLD:
            overall = "NONE"

    # S/R-фильтр: уровни с М5 (если есть), иначе с М15
    price_now = last_close_1m if last_close_1m is not None else None
    if price_now is not None:
        df_sr_src, _ = get_tv_series(pair, "5min", SR_LOOKBACK)
        if df_sr_src is None or df_sr_src.empty:
            df_sr_src, _ = get_tv_series(pair, "15min", SR_LOOKBACK)
        levels = detect_sr_levels(df_sr_src) if (df_sr_src is not None and not df_sr_src.empty) else []
        if overall in ("BUY", "SELL") and sr_conflict(overall, price_now, levels):
            prob = max(0.0, prob - 12.0)
            if prob < PROB_THRESHOLD:
                overall = "NONE"

      # --- Экспирация по вероятности и волатильности ---
        vol = 0.0004
        if df_m1 is not None and not df_m1.empty:
           vol = float(df_m1["close"].diff().abs().tail(10).mean())

      # 1️⃣ Нет сигнала, если ниже порога
        if overall == "NONE" or prob < PROB_THRESHOLD:
           expiry = None
           overall = "NONE"

      # 2️⃣ Если сигнал валиден — адаптируем время
        else:
           if prob >= 85:
              expiry = 3 if vol > 0.0005 else 4
           elif prob >= 70:
              expiry = 5
           else:
              expiry = 7

    # Цена входа
    entry_price = price_now
    if entry_price is None:
        df1, _ = get_tv_series(pair, "1min", 5)
        if df1 is not None and not df1.empty:
            entry_price = float(df1["close"].iloc[-1])

    # Лог
    if overall != "NONE" and expiry:
        ind = tf_data["1min"]
        indicators = {
            "ema20": ind.get("ema20"),
            "macd": ind.get("macd_diff"),
            "rsi": ind.get("rsi"),
            "impulse": ind.get("impulse"),
            "pattern": ind.get("pattern")
            # "reversal_up": ind.get("reversal_up"),
            # "reversal_down": ind.get("reversal_down"),
            # "div_buy": ind.get("div_buy"),
            # "div_sell": ind.get("div_sell")
        }
        log_signal(pair, overall, prob, expiry, entry_price or 0.0, indicators)

    return {
        "pair": pair,
        "dir": overall,
        "prob": round(prob, 1),
        "expiry": expiry,
        "entry_price": entry_price
    }, None
# -------------------- handlers --------------------
@dp.message(Command("start"))
async def on_start(m: types.Message):
    SESS[m.from_user.id] = {"pair": None, "panel_msg_id": None}
    text = panel_text_header()
    msg = await m.answer(text, reply_markup=kb_main(None), parse_mode="Markdown")
    SESS[m.from_user.id]["panel_msg_id"] = msg.message_id

@dp.callback_query(lambda c: c.data.startswith("PAIR|"))
async def on_pick_pair(cb: types.CallbackQuery):
    user = cb.from_user.id
    pair = cb.data.split("|", 1)[1]
    SESS.setdefault(user, {"pair": None, "panel_msg_id": cb.message.message_id})
    SESS[user]["pair"] = pair

    # Показываем статус анализа
    upd = datetime.now(timezone.utc).strftime("%H:%M UTC")
    await cb.message.edit_text(
        f"{panel_text_header()}\n\n⏳ Идёт анализ {pair} на M1, M5, M15...",
        reply_markup=kb_main(pair),
        parse_mode="Markdown"
    )

    res, err = await analyze_pair_for_user(user, pair)

    # ✅ Проверяем, вернулись ли данные
    if err:
        await cb.message.edit_text(
            f"{panel_text_header()}\n\n❌ {err}",
            reply_markup=kb_main(pair),
            parse_mode="Markdown"
        )
        await cb.answer()
        return

    if not res:
        await cb.message.edit_text(
            f"{panel_text_header()}\n\n⚪ Нет сигнала или данных для {pair}.",
            reply_markup=kb_main(pair),
            parse_mode="Markdown"
        )
        await cb.answer()
        return

    # ✅ Если результат получен — показываем его
    text = panel_text_analysis(
        pair=res.get("pair", pair),
        direction=res.get("dir", "NONE"),
        prob=res.get("prob", 0),
        expiry=res.get("expiry", None),
        updated_str=upd,
        price=res.get("entry_price", 0)
    )

    await cb.message.edit_text(text, reply_markup=kb_main(pair), parse_mode="Markdown")
    await cb.answer()

@dp.callback_query(lambda c: c.data=="ACT|REFRESH")
async def on_refresh(cb: types.CallbackQuery):
    user = cb.from_user.id
    pair = SESS.get(user,{}).get("pair")
    if not pair:
        await cb.answer("Сначала выбери пару", show_alert=True)
        return


    await cb.answer("Обновляю…")
    upd = datetime.now(timezone.utc).strftime("%H:%M UTC")
    await cb.message.edit_text(
        f"{panel_text_header()}\n\n⏳ Обновляю {pair}...",
        reply_markup=kb_main(pair),
        parse_mode="Markdown"
    )

    res, err = await analyze_pair_for_user(user, pair)
    if err:
        await cb.message.edit_text(
            f"{panel_text_header()}\n\n❌ {err}",
            reply_markup=kb_main(pair),
            parse_mode="Markdown"
        )
        return

    text = panel_text_analysis(
        pair=res["pair"], direction=res["dir"], prob=res["prob"],
        expiry=res["expiry"], updated_str=upd, price=res["entry_price"]
    )

    await cb.message.edit_text(text, reply_markup=kb_main(pair), parse_mode="Markdown")

@dp.callback_query(lambda c: c.data=="ACT|STATS")
async def on_stats(cb: types.CallbackQuery):
    pair = SESS.get(cb.from_user.id,{}).get("pair")
    txt = panel_text_stats()
    await cb.message.edit_text(txt, reply_markup=kb_main(pair), parse_mode="Markdown")
    # отправим временную круговую диаграмму и удалим через 15 сек, чтобы не засорять чат
    s = stats_last_24h()
    img = build_pie(s["wins"], s["losses"])
    if img:
        pic = await bot.send_photo(cb.from_user.id, img)
        await asyncio.sleep(15)
        try: await bot.delete_message(cb.from_user.id, pic.message_id)
        except: pass
    await cb.answer()

# фоновая очистка лога старше CLEAN_DAYS
def clean_logs_job():
    while True:
        try:
            df = pd.read_csv(LOG_FILE)
            if not df.empty:
                df["timestamp_utc"] = pd.to_datetime(df["timestamp_utc"])
                cutoff = datetime.now(timezone.utc) - pd.Timedelta(days=CLEAN_DAYS)
                df[df["timestamp_utc"] >= cutoff].to_csv(LOG_FILE, index=False)
        except Exception as e:
            print("clean_logs_job:", e)
        time.sleep(24*3600)


# =================================================================

from flask import Flask, jsonify, request

app = Flask(__name__)

# Храним последние сигналы
LATEST_SIGNALS = []

def register_signal(pair, direction, reason):
    LATEST_SIGNALS.append({
        "time": datetime.utcnow().strftime("%H:%M:%S"),
        "symbol": pair.replace("/", ""),
        "direction": direction,
        "reason": reason
    })
    if len(LATEST_SIGNALS) > 20:
        LATEST_SIGNALS.pop(0)

@app.route("/signals")
def signals():
    symbol = request.args.get("symbol")
    if symbol:
        data = [s for s in LATEST_SIGNALS if s["symbol"] == symbol]
    else:
        data = LATEST_SIGNALS
    return jsonify(data)

# ================== 🌐 FASTAPI + NGROK Автозапуск ==================
!pip install fastapi uvicorn pyngrok nest_asyncio -q

import nest_asyncio, threading, time
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pyngrok import ngrok, conf
import uvicorn

# 🪪 ВСТАВЬ СВОЙ ТОКЕН СЮДА 👇 (получить: https://dashboard.ngrok.com/get-started/your-authtoken)
conf.get_default().auth_token = "34y0MN8Z1isnPOTCJt2Lie6bRmU_4jWMt3YUo44DcgwwHgdFx"

nest_asyncio.apply()
app = FastAPI(title="TradeBot WebAPI")

# Разрешаем доступ из браузера Telegram WebApp / GitHub Pages
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ===== Пример API для WebApp =====
@app.get("/get_signal")
async def get_signal(pair: str = "EUR/USD"):
    try:
        # Здесь можно подставить твою функцию анализа:
        # res, err = await analyze_pair_for_user(0, pair)
        res = {"pair": pair, "dir": "BUY", "prob": 82.5, "expiry": 5, "entry_price": 1.0743}
        return JSONResponse(res)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

# Убиваем старые туннели
try:
    ngrok.kill()
except:
    pass

# Создаём новый туннель
print("🔄 Подключаю ngrok-туннель...")
public_url = ngrok.connect(8000).public_url
API_URL = public_url
print("✅ API запущен по адресу:")
print(public_url + "/get_signal?pair=EUR/USD")
print("🌐 API_URL установлено:", API_URL)

# Запускаем uvicorn в фоне
def start_server():
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="error")

thread = threading.Thread(target=start_server, daemon=True)
thread.start()

time.sleep(3)
print("🚀 Готово! Можно открывать WebApp:")
print(f"https://ariston9.github.io/TradeBot/app.html?api={API_URL}")

# ================== ▶️ СТАБИЛЬНЫЙ ЗАПУСК ДЛЯ COLAB ==================
import nest_asyncio, asyncio

nest_asyncio.apply()

async def main():
    print("✅ Бот запущен. Отправь /start в Telegram.")
    await dp.start_polling(bot)

# 🔄 Безопасный перезапуск event loop
try:
    loop = asyncio.get_event_loop()
    if loop.is_running():
        print("⚠️ Обнаружен активный цикл asyncio. Завершаем старый и создаём новый...")
        loop.stop()
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
except RuntimeError:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

# 🚀 Запуск
try:
    loop.run_until_complete(main())
except KeyboardInterrupt:
    print("🛑 Бот остановлен вручную.")
except Exception as e:
    print(f"⚠️ Ошибка запуска: {e}")
