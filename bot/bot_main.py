# bot/bot_main.py
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
from .autoscan import autoscan_loop

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

SESS = {}


# ----------------------- UI ----------------------
def panel_text_header():
    return "📊 *Trade Assistant — Анализ рынка*\n\nВыбери валютную пару:"


def kb_main(pair_selected):
    rows = []
    for i in range(0, len(PAIRS), 3):
        row = []
        for p in PAIRS[i:i + 3]:
            mark = "▪️" if p != pair_selected else "🔹"
            row.append(InlineKeyboardButton(text=f"{mark} {p}", callback_data=f"PAIR|{p}"))
        rows.append(row)

    if pair_selected:
        symbol = pair_selected.replace("/", "")
        link = f"https://ariston9.github.io/TradeBot/chart.html?symbol={symbol}"
        rows.append([
            InlineKeyboardButton(
                text="📈 Открыть график TradingView",
                web_app=WebAppInfo(url=link)
            )
        ])

    rows.append([
        InlineKeyboardButton(text="🔄 Обновить", callback_data="ACT|REFRESH"),
        InlineKeyboardButton(text="📊 Статистика", callback_data="ACT|STATS"),
        InlineKeyboardButton(
            text="📱 Открыть панель",
            web_app=WebAppInfo(url="https://ariston9.github.io/TradeBot/app.html")
        )
    ])

    return InlineKeyboardMarkup(inline_keyboard=rows)


# ----------------------- START ----------------------
@dp.message(Command("start"))
async def on_start(m: types.Message):
    SESS[m.from_user.id] = {"pair": None}
    msg = await m.answer(panel_text_header(), reply_markup=kb_main(None), parse_mode="Markdown")


# ---------------------- Выбор пары -----------------------
@dp.callback_query(lambda c: c.data.startswith("PAIR|"))
async def on_pick_pair(cb: types.CallbackQuery):
    await cb.answer()

    user = cb.from_user.id
    pair = cb.data.split("|")[1]
    SESS[user]["pair"] = pair

    upd = datetime.now(timezone.utc).strftime("%H:%M UTC")

    await cb.message.edit_text(
        f"{panel_text_header()}\n\n⏳ Анализирую {pair}...",
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

    text = (
        f"{panel_text_header()}\n\n"
        f"*Текущий анализ:* {res['pair']}\n"
        f"📊 Направление: `{res['dir']}`\n"
        f"🎯 Вероятность: *{res['prob']:.1f}%*\n"
        f"⏱ Экспирация: {res['expiry']} мин\n"
        f"Цена входа: {res['entry_price']:.5f}\n"
        f"📅 Обновлено: {upd}"
    )

    await cb.message.edit_text(text, reply_markup=kb_main(pair), parse_mode="Markdown")


# ---------------------- REFRESH ----------------------
@dp.callback_query(lambda c: c.data == "ACT|REFRESH"))
async def on_refresh(cb: types.CallbackQuery):
    await cb.answer()

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
        await cb.message.edit_text(
            f"{panel_text_header()}\n\n❌ {err}",
            reply_markup=kb_main(pair),
            parse_mode="Markdown"
        )
        return

    text = (
        f"{panel_text_header()}\n\n"
        f"*Текущий анализ:* {res['pair']}\n"
        f"📊 Направление: `{res['dir']}`\n"
        f"🎯 Вероятность: *{res['prob']:.1f}%*\n"
        f"⏱ Экспирация: {res['expiry']} мин\n"
        f"Цена входа: {res['entry_price']:.5f}\n"
        f"📅 Обновлено: {upd}"
    )

    await cb.message.edit_text(text, reply_markup=kb_main(pair), parse_mode="Markdown")


# ---------------------- STATISTICS ----------------------
@dp.callback_query(lambda c: c.data == "ACT|STATS"))
async def on_stats(cb: types.CallbackQuery):
    await cb.answer()

    pair = SESS.get(cb.from_user.id, {}).get("pair")
    txt = (
        f"{panel_text_header()}\n\n"
        f"📈 Статистика за 24 часа\n"
    )

    s = stats_last_24h()
    txt += (
        f"Всего сигналов: {s['total']}\n"
        f"Плюс: {s['wins']}\n"
        f"Минус: {s['losses']}\n"
        f"Проходимость: {s['winrate']}%"
    )

    await cb.message.edit_text(txt, reply_markup=kb_main(pair), parse_mode="Markdown")


# ---------------------- AUTOSCAN ----------------------
def background_evaluation():
    while True:
        evaluate_pending_signals()
        _time.sleep(500)


async def main():
    threading.Thread(target=background_evaluation, daemon=True).start()
    asyncio.create_task(autoscan_loop(bot))
    print("✅ Бот запущен. Отправь /start в Telegram.")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
