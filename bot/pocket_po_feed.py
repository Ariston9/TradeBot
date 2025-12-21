# bot/pocket_po_feed.py
import asyncio
import json
import time
import websockets
import requests

DEBUG_URL = "http://127.0.0.1:9222/json"

CURRENT_PO_PRICE = {}

def get_all_targets():
    return requests.get(DEBUG_URL, timeout=2).json()

async def listen_target(ws_url):
    async with websockets.connect(ws_url, ping_interval=None) as ws:
        await ws.send(json.dumps({
            "id": 1,
            "method": "Network.enable"
        }))

        async for msg in ws:
            data = json.loads(msg)

            if data.get("method") != "Network.webSocketFrameReceived":
                continue

            payload = data["params"]["response"]["payloadData"]

            # 🔎 фильтр тиков (как у тебя локально)
            if '"price"' not in payload:
                continue

            try:
                j = json.loads(payload)
            except:
                continue

            symbol = j.get("symbol")
            price = j.get("price")

            if symbol and price:
                CURRENT_PO_PRICE[symbol] = {
                    "price": float(price),
                    "time": time.time()
                }
                print("TICK:", symbol, price)

async def main():
    targets = get_all_targets()

    tasks = []
    for t in targets:
        ws_url = t.get("webSocketDebuggerUrl")
        if not ws_url:
            continue

        print("🔌 Attach:", t["type"], t.get("url"))
        tasks.append(asyncio.create_task(listen_target(ws_url)))

    await asyncio.gather(*tasks)

if __name__ == "__main__":
    asyncio.run(main())
