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
        InlineKeyboardButton(
            text="📱 Открыть панель",
            web_app=WebAppInfo(url="https://ariston9.github.io/TradeBot/app.html")
        )
    ])

    return InlineKeyboardMarkup(inline_keyboard=rows)


@dp.message(Command("start"))
async def on_start(m: types.Message):
    SESS[m.from_user.id] = {"pair": None, "panel_msg_id": None}
    text = panel_text_header()
    msg = await m.answer(text, reply_markup=kb_main(None), parse_mode="Markdown")


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
        f"🎯 Вероятность: *{res['prob']:.1f}%*\n"
        f"Направление: `{res['dir']}`\n"
        f"⏱ Экспирация: {res['expiry']} мин\n"
        f"Цена входа: {res['entry_price']:.5f}\n"
        f"📅 Обновлено: {upd}"
    )

    await cb.message.edit_text(text, reply_markup=kb_main(pair), parse_mode="Markdown")
