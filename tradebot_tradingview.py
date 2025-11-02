# -*- coding: utf-8 -*-

# ================== Trade Assistant v5.0 (Single-Message UI) ==================
from tvDatafeed import TvDatafeed, Interval
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
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from fastapi import FastAPI
from fastapi.responses import JSONResponse
import uvicorn, threading
# ---------- ВСТАВЬ СВОИ КЛЮЧИ ----------
import os

BOT_TOKEN = os.getenv("BOT_TOKEN")
API_KEY = os.getenv("API_KEY")
TV_USER = os.getenv("TV_USER")
TV_PASS = os.getenv("TV_PASS")
API_URL = os.getenv("API_URL")

# ---------------------------------------

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


# -------------------- data & indicators --------------------
# ---- загрузка истории из TradingView через tvDatafeed ----
INTERVAL_MAP = {
    "1min":  Interval.in_1_minute,
    "5min":  Interval.in_5_minute,
    "15min": Interval.in_15_minute,
}

def get_tv_series(pair: str, interval: str = "5min", n_bars: int = 300):
    """
    pair: как в PAIRS (например 'EUR/USD')
    interval: '1min' | '5min' | '15min'
    n_bars: сколько баров
    return: pandas.DataFrame с колонками: ['open','high','low','close','datetime'] (UTC)
    """
    if pair not in TV_MAP:
        return None, {"error": f"Пара {pair} не найдена в TV_MAP"}
    sym, ex = TV_MAP[pair]
    try:
        df = tv.get_hist(symbol=sym, exchange=ex, interval=INTERVAL_MAP[interval], n_bars=n_bars)
        if df is None or df.empty:
            return None, {"error": "Пустой ответ от TradingView"}
        # tvDatafeed возвращает DatetimeIndex (UTC)
        df = df.reset_index().rename(columns={"datetime":"datetime"})
        # приведение типов
        for c in ["open","high","low","close"]:
            df[c] = df[c].astype(float)
        df["dt_utc"] = pd.to_datetime(df["datetime"], utc=True)

        # --- Проверка свежести данных ---
        last_candle_time = df["dt_utc"].iloc[-1]
        age_sec = (datetime.now(timezone.utc) - last_candle_time).total_seconds()

        # если последняя свеча старше 1 часа — рынок, вероятно, закрыт
        if age_sec > 3600:
            last_time_str = last_candle_time.strftime("%Y-%m-%d %H:%M UTC")
            return None, {"error": f"⚠️ Нет свежих котировок ({last_time_str}). Рынок, возможно, закрыт."}

        return df, None
    except Exception as e:
        return None, {"error": str(e)}

def compute_indicators(df: pd.DataFrame):
    # EMA20
    df["EMA20"] = df["close"].ewm(span=20, adjust=False).mean()
    # MACD 12/26/9
    df["EMA12"] = df["close"].ewm(span=12, adjust=False).mean()
    df["EMA26"] = df["close"].ewm(span=26, adjust=False).mean()
    df["MACD"] = df["EMA12"] - df["EMA26"]
    df["MACD_sig"] = df["MACD"].ewm(span=9, adjust=False).mean()

    # RSI14
    delta = df["close"].diff()
    up = delta.clip(lower=0)
    down = -delta.clip(upper=0)
    ma_up = up.ewm(com=14-1, adjust=False).mean()
    ma_down = down.ewm(com=14-1, adjust=False).mean()
    rs = ma_up / ma_down
    df["RSI14"] = 100 - (100/(1+rs))
    return df

def score_on_tf(df: pd.DataFrame):
    # --- Последние две свечи ---
    last = df.iloc[-1]
    prev = df.iloc[-2]

    # --- Базовые сигналы ---
    ema_vote = 1 if last["close"] > last["EMA20"] else -1
    macd_vote = 1 if last["MACD"] > last["MACD_sig"] else -1
    rsi_vote = 1 if last["RSI14"] >= 70 else (-1 if last["RSI14"] <= 30 else 0)

    # ==========================
    #   АНАЛИЗ MACD-ДИВЕРГЕНЦИЙ
    # ==========================
    if "MACD_hist" not in df.columns:
        df["MACD_hist"] = df["MACD"] - df["MACD_sig"]

    # Определяем локальные минимумы и максимумы гистограммы
    df["hist_min"] = (df["MACD_hist"] < df["MACD_hist"].shift(1)) & (df["MACD_hist"] < df["MACD_hist"].shift(-1))
    df["hist_max"] = (df["MACD_hist"] > df["MACD_hist"].shift(1)) & (df["MACD_hist"] > df["MACD_hist"].shift(-1))

    # Берём последние два минимума и максимума
    last_mins = df.loc[df["hist_min"], "MACD_hist"].tail(2)
    last_maxs = df.loc[df["hist_max"], "MACD_hist"].tail(2)

    divergence_buy = False
    divergence_sell = False

    # BUY — второе дно выше предыдущего
    if len(last_mins) == 2 and last_mins.iloc[-1] > last_mins.iloc[-2]:
        divergence_buy = True

    # SELL — вторая вершина ниже предыдущей
    if len(last_maxs) == 2 and last_maxs.iloc[-1] < last_maxs.iloc[-2]:
        divergence_sell = True

    # --- ВЕСА ---
    # Можно задать вес каждому индикатору, например:
    # EMA — важнее (вес 2), MACD — чуть меньше (вес 1.5), RSI — лёгкий фильтр (вес 1), гистограмма MACD — лёгкий фильтр (вес 1)
    w_ema, w_macd, w_rsi = 1.5, 1.5, 0.5

    total = (ema_vote * w_ema +
             macd_vote * w_macd +
             rsi_vote * w_rsi)

    # --- Добавляем влияние дивергенций ---
    if divergence_buy:
        total += 1.5
    elif divergence_sell:
        total -= 1.5

    # --- Итог ---
    direction = "BUY" if total > 0 else ("SELL" if total < 0 else "NONE")
    macd_diff = abs(last["MACD"] - last["MACD_sig"])

    return {
        "direction": direction,
        "score": total,
        "macd_diff": macd_diff,
        "div_buy": divergence_buy,
        "div_sell": divergence_sell
    }
    # Расчёт общей силы сигнала (по всем TF)
def calc_overall_probability(tf_results):
    # Базовая сила сигнала от всех ТФ
    abs_sum = sum(abs(r["score"]) for r in tf_results)
    base_prob = (abs_sum / (len(tf_results) * 4.0)) * 100.0  # нормируем сильнее (4.0 = макс. score на ТФ)

    # Средний разброс направлений
    dirs = [r["direction"] for r in tf_results]
    agree = max(dirs.count("BUY"), dirs.count("SELL"))
    consistency = (agree / len(tf_results)) * 100.0  # согласованность таймфреймов

    # MACD амплитуда
    macd_avg = sum(r["macd_diff"] for r in tf_results) / len(tf_results)
    macd_strength = min(20.0, macd_avg * 1000.0)

    # RSI-фильтр (наказание за нейтральность)
    neutral_penalty = 10.0 * dirs.count("NONE")

    # Итоговая вероятность
    prob = base_prob * 0.6 + consistency * 0.3 + macd_strength * 0.1 - neutral_penalty
    prob = max(0.0, min(prob, 99.0))  # теперь 100% никогда не выдаётся просто так
    return round(prob, 1)


def log_signal(pair, direction, probability, expiry_min, entry_price):
    row = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "pair": pair, "direction": direction, "probability": probability,
        "expiry_min": expiry_min, "entry_price": entry_price,
        "evaluated": False, "result": ""
    }
    df = pd.read_csv(LOG_FILE)
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

# -------------------- core analysis --------------------
async def analyze_pair_for_user(user_id: int, pair: str):
    tf_results = []
    last_close_1m = None

    # Сбор сигналов по M1/M5/M15
    for tf_name, tf_int in TFS.items():
        df_tf, err = get_tv_series(pair, tf_int, MAX_CANDLES)
        time.sleep(REQUEST_DELAY)
        if df_tf is None:
            return None, f"Ошибка данных {pair} {tf_int}: {err}"
        df_tf = compute_indicators(df_tf)
        tf_results.append(score_on_tf(df_tf))
        if tf_int == "1min":
            last_close_1m = float(df_tf["close"].iloc[-1])

    # Направление по согласованности ТФ (жёсткий фильтр: все 3 совпадают)
    dirs = [r["direction"] for r in tf_results]
    # Подсчёт количества сигналов
    buy_count = dirs.count("BUY")
    sell_count = dirs.count("SELL")

    # Вероятность (сначала нужно посчитать, иначе переменная не определена)
    prob = calc_overall_probability(tf_results)
    # Решение по большинству (2 из 3 достаточно)
    if buy_count >= 2 and prob >= 70:
      overall = "BUY"
    elif sell_count >= 2 and prob >= 70:
      overall = "SELL"
    else:
      overall = "NONE"

    # --- Волатильность по M1 (отдельная выборка) ---
    df_vol, _ = get_tv_series(pair, "1min", 50)
    if df_vol is not None:
        vol_df = df_vol.copy()
        volatility = vol_df["close"].diff().abs().tail(10).mean()
    else:
        # запасной вариант, если вдруг M1 не пришёл
        volatility = 0.0004

    # --- Экспирация: по prob + волатильности ---
    expiry = None
    if prob >= 90:
        if volatility > 0.0007:
            expiry = 3
        elif volatility > 0.0003:
            expiry = 4
        else:
            expiry = 4
    elif prob >= 75:
        if volatility > 0.0007:
            expiry = 5
        elif volatility > 0.0003:
            expiry = 5
        else:
            expiry = 5
    elif prob >= 60:
        if volatility > 0.0007:
            expiry = 7
        elif volatility > 0.0003:
            expiry = 10
        else:
            expiry = 12
    else:
        expiry = None  # сигнал слабый — не советуем вход

    # Цена входа по M1
    entry_price = last_close_1m
    if entry_price is None:
        df1, _ = get_tv_series(pair, "1min", 5)
        if df1 is not None:
            entry_price = float(df1["close"].iloc[-1])

    # Лог сигнала (только если есть направление и экспирация)
    if overall != "NONE" and expiry:
        log_signal(pair, overall, prob, expiry, entry_price if entry_price else 0.0)

    return {
        "pair": pair,
        "dir": overall,
        "prob": prob,
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
    pair = cb.data.split("|",1)[1]
    SESS.setdefault(user, {"pair":None,"panel_msg_id":cb.message.message_id})
    SESS[user]["pair"] = pair

    # show “analyzing…”
    upd = datetime.now(timezone.utc).strftime("%H:%M UTC")
    await cb.message.edit_text(
        f"{panel_text_header()}\n\n⏳ Идёт анализ {pair} на M1, M5, M15...",
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
        await cb.answer()
        return

    text = panel_text_analysis(
        pair=res["pair"], direction=res["dir"], prob=res["prob"],
        expiry=res["expiry"], updated_str=upd, price=res["entry_price"]
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

API_URL = "https://your-app-name.onrender.com"
# функция запуска uvicorn в отдельном потоке
def start_api():
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="error")

api_thread = threading.Thread(target=start_api, daemon=True)
api_thread.start()

# Дадим серверу 2–3 секунды, чтобы подняться
time.sleep(3)

print(f"🌐 API_URL установлено: {API_URL}")
