# bot/analyzer.py
import time
from datetime import datetime, timezone

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

from .config import (
    PAIRS,
    TFS,
    MAX_CANDLES,
    REQUEST_DELAY,
    API_URL,
)
from .tv_api import get_tv_series
from .indicators import compute_indicators
from .scoring import score_on_tf, calc_overall_probability
from .logger import log_signal, stats_last_24h


# -------------------- keyboards --------------------
def kb_main(pair_selected: str | None) -> InlineKeyboardMarkup:
    """
    Главная inline-клавиатура:
    - выбор пары
    - кнопка "Открыть график TradingView"
    - Обновить / Статистика / Открыть панель (WebApp)
    """
    rows: list[list[InlineKeyboardButton]] = []

    # Кнопки валютных пар (по 3 в ряд)
    for i in range(0, len(PAIRS), 3):
        row: list[InlineKeyboardButton] = []
        for p in PAIRS[i:i + 3]:
            mark = "▪️" if p != pair_selected else "🔹"
            row.append(
                InlineKeyboardButton(
                    text=f"{mark} {p}",
                    callback_data=f"PAIR|{p}",
                )
            )
        rows.append(row)

    # Кнопка "Открыть график TradingView" (github-страница с WebApp)
    if pair_selected:
        tv_symbol = pair_selected.replace("/", "")
        web_link = f"https://ariston9.github.io/TradeBot/chart.html?symbol={tv_symbol}"
        rows.append(
            [
                InlineKeyboardButton(
                    text="📈 Открыть график TradingView",
                    web_app=WebAppInfo(url=web_link),
                )
            ]
        )

    # Нижний ряд: обновить / статистика / WebApp-панель
    rows.append(
        [
            InlineKeyboardButton(text="🔄 Обновить", callback_data="ACT|REFRESH"),
            InlineKeyboardButton(text="📊 Статистика", callback_data="ACT|STATS"),
            InlineKeyboardButton(
                text="📱 Открыть панель",
                web_app=WebAppInfo(
                    url=f"https://ariston9.github.io/TradeBot/app.html?api={API_URL}"
                ),
            ),
        ]
    )

    return InlineKeyboardMarkup(inline_keyboard=rows)


# -------------------- panel text builders --------------------
def panel_text_header() -> str:
    return "📊 *Trade Assistant — Анализ рынка*\n\nВыбери валютную пару:"


def panel_text_analysis(
    pair: str,
    direction: str,
    prob: float,
    expiry: int | None,
    updated_str: str,
    price: float | None = None,
) -> str:
    dir_txt = (
        "🔼 Покупать 🟢"
        if direction == "BUY"
        else ("📊 Продавать 🔴" if direction == "SELL" else "Ожидание ⚪")
    )
    extra = f"\nЦена входа: {price:.5f}" if price is not None else ""

    text = (
        f"{panel_text_header()}\n\n"
        f"*Текущий анализ:* {pair}\n"
        f"{dir_txt}\n"
        f"🎯 Вероятность: *{prob:.1f}%*\n"
    )

    if expiry:
        text += f"⏱ Экспирация: {expiry} мин\n"
    else:
        text += "⏱ Сигнал слабый — сделку не открывать\n"

    text += f"📅 Обновлено: {updated_str}{extra}"
    return text


def panel_text_stats() -> str:
    s = stats_last_24h()
    return (
        f"{panel_text_header()}\n\n"
        f"📈 *Статистика за 24 часа*\n"
        f"Всего сигналов: *{s['total']}*\n"
        f"Плюс: *{s['wins']}*\n"
        f"Минус: *{s['losses']}*\n"
        f"Проходимость: *{s['winrate']}%*"
    )


# -------------------- core analysis (Yahoo / TV-like) --------------------
async def analyze_pair_for_user(user_id: int, pair: str):
    """
    Основной анализ одной пары для панели.
    Версия: без PocketOption / OTC, только данные из get_tv_series (Yahoo).
    Логика = как в Colab-версии, включая WICK-ENTRY.
    """

    # --------- Сбор индикаторов по всем TF ---------
    tf_results: list[dict] = []
    last_close_1m: float | None = None

    for tf_name, tf_int in TFS.items():  # например: {"M1": "1min", "M5": "5min", ...}
        df_tf, err = get_tv_series(pair, tf_int, MAX_CANDLES)
        time.sleep(REQUEST_DELAY)

        if df_tf is None:
            print(f"⚠️ Не удалось получить данные {pair} {tf_int}: {err}")
            continue

        df_tf = compute_indicators(df_tf)
        # ---- ПРОВЕРКА СВЕЖЕСТИ СВЕЧЕЙ (как в Colab) ----
        def check_market_open(df):
        from datetime import datetime, timezone
    
        # Если данных нет вообще → точно рынок закрыт
        if df is None or df.empty:
            return {
                "error": "⚠️ Рынок закрыт.\nНет свежих котировок."
            }
    
        # Если нет timestamp — считаем что данные устаревшие
        if "datetime" not in df.columns:
            return {
                "error": "⚠️ Рынок закрыт.\nОтсутствует время последней свечи."
            }
    
        ts = df["datetime"].iloc[-1]
    
        # Приводим к UTC
        try:
            if ts.tzinfo is None:
                ts = ts.tz_localize("UTC")
        except:
            # если timestamp битый
            return {
                "error": "⚠️ Рынок закрыт.\nНекорректная метка времени."
            }
    
        now_utc = datetime.now(timezone.utc)
        age_sec = (now_utc - ts).total_seconds()
    
        # Свеча старее 60 минут
        if age_sec > 3600:
            return {
                "error": (
                    "⚠️ Рынок закрыт.\n"
                    f"Последняя свеча была: {ts.strftime('%Y-%m-%d %H:%M UTC')}"
                )
            }
    
        # Всё ок
        return None

        
        # Проверяем рынок
        market_state = check_market_open(df_tf)
        if market_state:
            return None, market_state
        # -------------------------------------------------

        ind = score_on_tf(df_tf, tf_name)
        ind["tf"] = tf_name
        tf_results.append(ind)

        if tf_int == "1min":
            # запомним последний close на M1
            last_close_1m = float(df_tf["close"].iloc[-1])

    if not tf_results:
        return None, f"Нет данных для {pair}. Проверь подключение к источнику котировок."

    # --------- Общая вероятность по всем TF ---------
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

    # --------- Волатильность по M1 ---------
    df_vol, _ = get_tv_series(pair, "1min", 50)
    if df_vol is not None and not df_vol.empty:
        vol_df = df_vol.copy()
        volatility = vol_df["close"].diff().abs().tail(10).mean()
    else:
        volatility = 0.0004  # дефолт

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
        expiry = None  # слабый сигнал — лучше не входить

    # --------- WICK ENTRY по хвостам свечей ---------
    entry_price: float | None = None
    try:
        df_1m, _ = get_tv_series(pair, "1min", 3)

        if df_1m is not None and not df_1m.empty and overall in ("BUY", "SELL"):
            last = df_1m.iloc[-1]
            high = float(last["high"])
            low = float(last["low"])
            close = float(last["close"])

            # m1-индикаторы (развороты / rejection) уже посчитаны в score_on_tf
            # и попали в dict m1
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


# --------- helper для времени в заголовке панели ---------
def current_utc_str() -> str:
    return datetime.now(timezone.utc).strftime("%H:%M UTC")
