import asyncio

from aiogram import Bot

from .config import PAIRS, SIGNAL_CHAT_ID
from .analyzer import analyze_pair_for_user

AUTO_SCAN_ENABLED = False
AUTO_SCAN_DELAY = 5.0
AUTO_SCAN_CYCLE = 20.0


async def autoscan_loop(bot: Bot):
    global AUTO_SCAN_ENABLED
    print("🔁 Авто-сканер загружен. Ожидает активации /autoscan_on")

    while True:
        if AUTO_SCAN_ENABLED:
            print("▶️ Сканирую пары...")
            for pair in PAIRS:
                try:
                    res, err = await analyze_pair_for_user(SIGNAL_CHAT_ID, pair)
                    if err:
                        print(f"[{pair}] Ошибка TV:", err)
                        await asyncio.sleep(AUTO_SCAN_DELAY)
                        continue
                    if res and res["dir"] in ("BUY", "SELL") and res["prob"] >= 70:
                        msg = (
                            f"📡 *Авто-сигнал*\n"
                            f"Пара: {pair}\n"
                            f"Направление: *{res['dir']}*\n"
                            f"Вероятность: *{res['prob']}%*\n"
                            f"Цена входа: {res['entry_price']}"
                        )
                        await bot.send_message(SIGNAL_CHAT_ID, msg, parse_mode="Markdown")
                except Exception as e:
                    print("❌ AUTOSCAN ERROR:", e)
                await asyncio.sleep(AUTO_SCAN_DELAY)
            print(f"⏳ Цикл завершён. Пауза {AUTO_SCAN_CYCLE} сек.")
            await asyncio.sleep(AUTO_SCAN_CYCLE)
        else:
            await asyncio.sleep(1)
