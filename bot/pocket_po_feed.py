# bot/pocket_po_feed.py
import asyncio
import json
import base64
import time
import websockets
import requests

CDP_URL = "ws://127.0.0.1:9222/devtools/page/"
TICK_SERVER = "http://127.0.0.1:9001/tick"


async def connect_to_po_tab():
    import subprocess, json

    data = subprocess.check_output(
        ["curl", "-s", "http://127.0.0.1:9222/json"]
    )
    tabs = json.loads(data)

    for tab in tabs:
        if "pocketoption.com" in tab.get("url", ""):
            return tab["webSocketDebuggerUrl"]

    raise RuntimeError("PocketOption tab not found")


def send_tick(symbol, price, ts):
    requests.post(
        TICK_SERVER,
        json={
            "symbol": symbol,
            "price": price,
            "time": ts
        },
        timeout=1
    )


async def po_cdp_loop(ws_url):
    async with websockets.connect(ws_url, max_size=None) as ws:
        await ws.send(json.dumps({
            "id": 1,
            "method": "Network.enable"
        }))

        print("🟢 CDP connected, listening WS frames")

        async for msg in ws:
            data = json.loads(msg)

            if data.get("method") != "Network.webSocketFrameReceived":
                continue

            payload = data["params"]["response"]["payloadData"]

            try:
                raw = base64.b64decode(payload)
            except:
                continue

            # PO sends binary arrays
            if not raw.startswith(b"["):
                continue

            try:
                arr = json.loads(raw.decode("utf-8"))
            except:
                continue

            # example: ["EURUSD_otc", 1733591234.12, 1.07852]
            if (
                isinstance(arr, list)
                and len(arr) >= 3
                and isinstance(arr[0], str)
                and isinstance(arr[2], (int, float))
            ):
                symbol = arr[0]
                ts = float(arr[1])
                price = float(arr[2])

                print(f"TICK {symbol} {price}")
                send_tick(symbol, price, ts)


async def main():
    ws_url = await connect_to_po_tab()
    print("🔗 Found PO tab:", ws_url)
    await po_cdp_loop(ws_url)


if __name__ == "__main__":
    asyncio.run(main())
