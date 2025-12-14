# bot/pocket_po_feed.py
import asyncio
import json
import websockets

# Структура:
# CURRENT_PO_PRICE = {
#     "EURUSD": {"price": 1.07852, "time": 1733591221.51},
#     "EURUSD_otc": {"price": 1.07810, "time": 1733591220.12},
# }
CURRENT_PO_PRICE = {}

# Укажи свой VPS или локальный хост где работает PO Engine
PO_WS_URL = "ws://127.0.0.1:9222/devtools/page/6016D1D2538C4A2C36412BCDDE0936C4"


async def po_ws_loop():
    """Подключение к PO Streaming Engine v10."""
    global CURRENT_PO_PRICE

    while True:
        try:
            print("⏳ Connecting to PO Engine WS:", PO_WS_URL)
            async with websockets.connect(
                PO_WS_URL, ping_interval=20, ping_timeout=20
            ) as ws:

                print("⚡ Connected to PO Streaming Engine v10")

                async for raw in ws:
                    try:
                        data = json.loads(raw)
                    except:
                        continue

                    if data.get("event") != "tick":
                        continue

                    symbol = data.get("symbol")
                    price = data.get("price")
                    ts = data.get("time")

                    if not symbol or price is None:
                        continue

                    # Сохраняем последний тик
                    CURRENT_PO_PRICE[symbol] = {
                        "price": float(price),
                        "time": float(ts)
                    }

        except Exception as e:
            print("❌ PO WS error:", e)
            await asyncio.sleep(3)




