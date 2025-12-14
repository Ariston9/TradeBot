# bot/pocket_po_feed.py
import asyncio
import json
import websockets

# Структура:
# CURRENT_PO_PRICE = {
#     "EURUSD": {"price": 1.07852, "time": 1733591221.51},
#     "EURUSD_otc": {"price": 1.07810, "time": 1733591220.12},
# }
# CURRENT_PO_PRICE = {}

# Укажи свой VPS или локальный хост где работает PO Engine
PO_REAL_WS = "wss://ws.pocketoption.com/socket.io/?EIO=3&transport=websocket"

HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Origin": "https://pocketoption.com",
}

async def po_ws_loop():
    print("⏳ Connecting to PocketOption real WS")

    async with websockets.connect(
        PO_REAL_WS,
        extra_headers=HEADERS,
        ping_interval=None
    ) as ws:
        print("⚡ Connected to PocketOption WS")

        async for msg in ws:
            if not msg.startswith("42"):
                continue

            try:
                payload = json.loads(msg[2:])
            except:
                continue

            event, data = payload

            if event != "tick":
                continue

            symbol = data.get("symbol")
            price = data.get("price")

            if not symbol or price is None:
                continue

            CURRENT_PO_PRICE[symbol] = {
                "price": float(price),
                "time": time.time()
            }

            print("TICK:", symbol, price)


if __name__ == "__main__":
    asyncio.run(po_ws_loop())












