import asyncio
import threading
import time
from datetime import datetime, timezone
from typing import Dict, Any
from .autoscan import autoscan_loop

from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo, CallbackQuery
from aiogram.exceptions import TelegramBadRequest

from .config import BOT_TOKEN, PAIRS, API_URL
from .analyzer import analyze_pair_for_user
from .logger import stats_last_24h, build_pie, evaluate_pending_signals


# ================== ИНИЦИАЛИЗАЦИЯ БОТА ==================

bot = Bot(BOT_TOKEN)
dp = Dispatcher()

# Сессии пользователей: выбранная пара и id сообщения панели
SESS: Dict[int, Dict[str, Any]] = {}


# ================== КЛАВИАТУРА ==================

def kb_main(pair_selected: str | None) -> InlineKeyboardMarkup:
    """
    Основная клавиатура:
    - сетка валютных пар
    - кнопки Обновить / Статистика
    - кнопка WebApp "Открыть панель"
    """
    rows: list[list[InlineKeyboardButton]] = []

    # сетка валютных пар 3xN
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

    # кнопка "Открыть график TradingView", только если выбрана пара
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

    # нижний ряд: обновить / статистика / панель
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


# ================== ТЕКСТ ПАНЕЛИ ==================

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
        "Покупать ✅" if direction == "BUY"
        else ("Продавать 🔻" if direction == "SELL" else "Ожидание ⚪")
    )

    extra_price = f"\nЦена входа: {price:.5f}" if price is not None else ""

    text = (
        f"{panel_text_header()}\n\n"
        f"*Текущий анализ:* {pair}\n"
        f"{dir_txt}\n"
        f"🎯 Вероятность: *{prob:.1f}%*\n"
    )

    if expiry:
        text += f"⏱ Рекомендуемая экспирация: {expiry} мин\n"
    else:
        text += "⏱ Сигнал слабый — сделку не открывать\n"

    text += f"📅 Обновлено: {updated_str}{extra_price}"
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


# ================== BACKGROUND: авто-оценка сигналов ==================

def background_evaluation() -> None:
    """
    Фоновая проверка signals.csv каждые 6 минуты.
    Запускается отдельным потоком при старте.
    """
    while True:
        try:
            evaluate_pending_signals()
        except Exception as e:
            print("background_evaluation error:", e)
        time.sleep(500)


# ================== HANDLERS ==================

@dp.message(Command("autoscan_on"))
async def autoscan_on(msg: types.Message):
    global AUTO_SCAN_ENABLED
    AUTO_SCAN_ENABLED = True
    await msg.answer("🚀 Авто-сканер включён.")
    
@dp.message(Command("autoscan_off"))
async def autoscan_off(msg: types.Message):
    global AUTO_SCAN_ENABLED
    AUTO_SCAN_ENABLED = False
    await msg.answer("⏹ Авто-сканер выключён.")

@dp.message(Command("start"))
async def on_start(m: types.Message) -> None:
    user_id = m.from_user.id
    SESS[user_id] = {"pair": None, "panel_msg_id": None}

    text = panel_text_header()
    msg = await m.answer(text, reply_markup=kb_main(None), parse_mode="Markdown")

    SESS[user_id]["panel_msg_id"] = msg.message_id


@dp.callback_query(lambda c: c.data.startswith("PAIR|"))
async def on_pick_pair(cb: CallbackQuery) -> None:
    # защита от старых callback-ов
    try:
        await cb.answer()
    except TelegramBadRequest:
        return

    user_id = cb.from_user.id
    pair = cb.data.split("|", 1)[1]

    sess = SESS.setdefault(user_id, {"pair": None, "panel_msg_id": cb.message.message_id})
    sess["pair"] = pair

    upd = datetime.now(timezone.utc).strftime("%H:%M UTC")

    # показываем «идёт анализ…»
    await cb.message.edit_text(
        f"{panel_text_header()}\n\n⏳ Идёт анализ {pair} на M1, M5, M15...",
        reply_markup=kb_main(pair),
        parse_mode="Markdown",
    )

    res, err = await analyze_pair_for_user(user_id, pair)

    if err:
        # тут именно человекочитаемая строка, а не dict
        if isinstance(err, dict) and "error" in err:
            err_text = err["error"]
        else:
            err_text = str(err)

        await cb.message.edit_text(
            f"{panel_text_header()}\n\n❌ {err_text}",
            reply_markup=kb_main(pair),
            parse_mode="Markdown",
        )
        return

    if not res:
        await cb.message.edit_text(
            f"{panel_text_header()}\n\n⚪ Сигнал не найден или условия не выполнены для {pair}.",
            reply_markup=kb_main(pair),
            parse_mode="Markdown",
        )
        return

    text = panel_text_analysis(
        pair=res["pair"],
        direction=res["dir"],
        prob=res["prob"],
        expiry=res["expiry"],
        updated_str=upd,
        price=res.get("entry_price"),
    )

    await cb.message.edit_text(text, reply_markup=kb_main(pair), parse_mode="Markdown")


@dp.callback_query(lambda c: c.data == "ACT|REFRESH")
async def on_refresh(cb: CallbackQuery) -> None:
    user_id = cb.from_user.id
    sess = SESS.get(user_id, {})
    pair = sess.get("pair")

    if not pair:
        await cb.answer("Сначала выбери пару", show_alert=True)
        return

    upd = datetime.now(timezone.utc).strftime("%H:%M UTC")

    await cb.message.edit_text(
        f"{panel_text_header()}\n\n⏳ Обновляю анализ {pair}...",
        reply_markup=kb_main(pair),
        parse_mode="Markdown",
    )

    res, err = await analyze_pair_for_user(user_id, pair)

    if err:
        if isinstance(err, dict) and "error" in err:
            err_text = err["error"]
        else:
            err_text = str(err)

        await cb.message.edit_text(
            f"{panel_text_header()}\n\n❌ {err_text}",
            reply_markup=kb_main(pair),
            parse_mode="Markdown",
        )
        return

    if not res:
        await cb.message.edit_text(
            f"{panel_text_header()}\n\n⚪ Сигнал не найден или условия не выполнены для {pair}.",
            reply_markup=kb_main(pair),
            parse_mode="Markdown",
        )
        return

    text = panel_text_analysis(
        pair=res["pair"],
        direction=res["dir"],
        prob=res["prob"],
        expiry=res["expiry"],
        updated_str=upd,
        price=res.get("entry_price"),
    )

    await cb.message.edit_text(text, reply_markup=kb_main(pair), parse_mode="Markdown")


@dp.callback_query(lambda c: c.data == "ACT|STATS")
async def on_stats(cb: CallbackQuery) -> None:
    # простая текстовая статистика + при возможности — картинка-пирог
    text = panel_text_stats()

    stats = stats_last_24h()
    pie_buf = build_pie(stats["wins"], stats["losses"])

    if pie_buf:
        await cb.message.answer_photo(pie_buf, caption=text, parse_mode="Markdown")
    else:
        await cb.message.edit_text(text, reply_markup=kb_main(SESS.get(cb.from_user.id, {}).get("pair")), parse_mode="Markdown")

    await cb.answer()


# ================== ЗАПУСК БОТА ==================

async def main() -> None:
    print("✅ Бот запущен. Отправь /start в Telegram.")

    # фоновая оценка сигналов
    threading.Thread(target=background_evaluation, daemon=True).start()
    # 🔥 вот эта строка запускает autoscan
    asyncio.create_task(autoscan_loop(bot))

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
