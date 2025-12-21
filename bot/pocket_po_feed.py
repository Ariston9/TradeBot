# bot/pocket_po_feed.py
import asyncio
import json
import websockets
import requests

# Структура:
# CURRENT_PO_PRICE = {
#     "EURUSD": {"price": 1.07852, "time": 1733591221.51},
#     "EURUSD_otc": {"price": 1.07810, "time": 1733591220.12},
# }
CURRENT_PO_PRICE = {}

# Укажи свой VPS или локальный хост где работает PO Engine
DEVTOOLS_URL = "http://127.0.0.1:9222/json"


def get_po_tab():
    tabs = requests.get(DEVTOOLS_URL).json()
    for t in tabs:
        if "pocketoption.com" in t.get("url", ""):
            return t["webSocketDebuggerUrl"]
    return None


async def po_ws_loop():
    ws_url = get_po_tab()
    if not ws_url:
        print("❌ PocketOption tab not found")
        return

    print("✅ Found PO tab:", ws_url)

    async with websockets.connect(ws_url, max_size=None) as ws:
        # включаем Network
        await ws.send(json.dumps({
            "id": 1,
            "method": "Network.enable"
        }))

        print("⚡ Listening WebSocket frames...")

        while True:
            raw = await ws.recv()
            if not isinstance(raw, str):
                continue

            data = json.loads(raw)

            if data.get("method") != "Network.webSocketFrameReceived":
                continue

            payload = data["params"]["response"]["payloadData"]

            # В payload лежит цена (без ключей)
            # if isinstance(payload, str) and "." in payload:
            #     for part in payload.replace(",", " ").split():
            #         try:
            #             price = float(part)
            #             ts = asyncio.get_event_loop().time()

            #             CURRENT_PO_PRICE["PO"] = {
            #                 "price": price,
            #                 "time": ts
            #             }

                        # print("TICK:", price)
                        print("RAW PAYLOAD:")
                        print(payload)
                        print("=" * 80)


                        break
                    except:
                        pass



if __name__ == "__main__":
    asyncio.run(po_ws_loop())

















