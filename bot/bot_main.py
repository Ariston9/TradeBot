import asyncio
from datetime import datetime, timezone
import threading
import time as _time

from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo, BufferedInputFile
from aiogram.exceptions import TelegramBadRequest

from .config import BOT_TOKEN, PAIRS
from .analyzer import analyze_pair_for_user
from .logger import stats_last_24h, build_pie, evaluate_pending_signals
from .autoscan import AUTO_SCAN_ENABLED, autoscan_loop
# from .pocket_ws import pocketoption_price_feed

# print("RAW TOKEN:", repr(BOT_TOKEN))
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

SESS: dict[int, dict] = {}

def panel_text_header() -> str:
    return "📊 *Trade Assistant — Анализ рынка*\n\nВыбери валютную пару:"


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
    ])

    return InlineKeyboardMarkup(inline_keyboard=rows)


def panel_text_analysis(pair, direction, prob, expiry, updated_str, price=None):
    if direction == "BUY":
        dir_txt = "🔼 Покупать 🟢"
    elif direction == "SELL":
        dir_txt = "📊 Продавать 🔴"
    else:
        dir_txt = "Ожидание ⚪"

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


def panel_text_stats():
    s = stats_last_24h()
    return (
        f"{panel_text_header()}\n\n"
        f"📈 *Статистика за 24 часа*\n"
        f"Всего сигналов: *{s['total']}*\n"
        f"Плюс: *{s['wins']}*\n"
        f"Минус: *{s['losses']}*\n"
        f"Проходимость: *{s['winrate']}%*"
    )


@dp.message(Command("start"))
async def on_start(m: types.Message):
    SESS[m.from_user.id] = {"pair": None, "panel_msg_id": None}
    text = panel_text_header()
    msg = await m.answer(text, reply_markup=kb_main(None), parse_mode="Markdown")
    SESS[m.from_user.id]["panel_msg_id"] = msg.message_id


@dp.message(Command("autoscan_on"))
async def autoscan_on(message: types.Message):
    from .autoscan import AUTO_SCAN_ENABLED  # local import to modify
    AUTO_SCAN_ENABLED = True
    await message.answer("🟢 Авто-сканер включён\nБот теперь анализирует пары каждые 20–40 секунд.")


@dp.message(Command("autoscan_off"))
async def autoscan_off(message: types.Message):
    from .autoscan import AUTO_SCAN_ENABLED
    AUTO_SCAN_ENABLED = False
    await message.answer("🔴 Авто-сканер остановлен.")


@dp.callback_query(lambda c: c.data.startswith("PAIR|"))
async def on_pick_pair(cb: types.CallbackQuery):
    try:
        await cb.answer()
    except TelegramBadRequest:
        return

    user = cb.from_user.id
    pair = cb.data.split("|", 1)[1]
    SESS.setdefault(user, {"pair": None, "panel_msg_id": cb.message.message_id})
    SESS[user]["pair"] = pair

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
        return

    if not res:
        await cb.message.edit_text(
            f"{panel_text_header()}\n\n⚪ Сигнал не найден или условия не выполнены для {pair}.",
            reply_markup=kb_main(pair),
            parse_mode="Markdown"
        )
        return

    text = panel_text_analysis(
        pair=res["pair"], direction=res["dir"], prob=res["prob"],
        expiry=res["expiry"], updated_str=upd, price=res["entry_price"]
    )
    await cb.message.edit_text(text, reply_markup=kb_main(pair), parse_mode="Markdown")


@dp.callback_query(lambda c: c.data == "ACT|REFRESH")
async def on_refresh(cb: types.CallbackQuery):
    try:
        await cb.answer()
    except TelegramBadRequest:
        return

    user = cb.from_user.id
    pair = SESS.get(user, {}).get("pair")
    if not pair:
        await cb.answer("Сначала выбери пару", show_alert=True)
        return

    upd = datetime.now(timezone.utc).strftime("%H:%M UTC")
    await cb.message.edit_text(
        f"{panel_text_header()}\n\n⏳ Обновляю {pair}...",
        reply_markup=kb_main(pair),
        parse_mode="Markdown"
    )

    res, err = await analyze_pair_for_user(user, pair)
    if err:
        await callback.message.answer(err)
        return

    text = panel_text_analysis(
        pair=res["pair"], direction=res["dir"], prob=res["prob"],
        expiry=res["expiry"], updated_str=upd, price=res["entry_price"]
    )
    await cb.message.edit_text(text, reply_markup=kb_main(pair), parse_mode="Markdown")


@dp.callback_query(lambda c: c.data == "ACT|STATS")
async def on_stats(cb: types.CallbackQuery):
    try:
        await cb.answer()
    except TelegramBadRequest:
        return

    pair = SESS.get(cb.from_user.id, {}).get("pair")
    txt = panel_text_stats()
    await cb.message.edit_text(txt, reply_markup=kb_main(pair), parse_mode="Markdown")

    s = stats_last_24h()
    img = build_pie(s["wins"], s["losses"])
    if img:
        photo = BufferedInputFile(
            img.getvalue(),
            filename="stats_chart.png"
        )
        pic = await bot.send_photo(cb.from_user.id, photo)
        await asyncio.sleep(15)
        try:
            await bot.delete_message(cb.from_user.id, pic.message_id)
        except Exception:
            pass


def background_evaluation():
    while True:
        evaluate_pending_signals()
        _time.sleep(500)


async def main():
    threading.Thread(target=background_evaluation, daemon=True).start()
    asyncio.create_task(autoscan_loop(bot))
    # print("🌐 Starting PocketOption WebSocket...")
    # asyncio.create_task(pocketoption_price_feed())
    print("✅ Бот запущен. Отправь /start в Telegram.")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
