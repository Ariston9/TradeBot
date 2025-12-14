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

    import websockets

    async with websockets.connect(ws_url) as ws:
        await ws.send(json.dumps({
            "id": 1,
            "method": "Runtime.enable"
        }))

        await ws.send(json.dumps({
            "id": 2,
            "method": "Runtime.evaluate",
            "params": {
                "expression": """
                (function() {
                    if (window.__PO_HOOKED__) return;
                    window.__PO_HOOKED__ = true;

                    const orig = WebSocket.prototype.send;
                    WebSocket.prototype.send = function(data) {
                        try {
                            if (typeof data === "string" && data.includes("tick")) {
                                window.postMessage({type: "PO_TICK", data}, "*");
                            }
                        } catch(e){}
                        return orig.apply(this, arguments);
                    };
                })();
                """
            }
        }))

        print("⚡ Hook injected, waiting ticks...")

        while True:
            msg = await ws.recv()
            if "PO_TICK" in msg:
                print("RAW:", msg)


if __name__ == "__main__":
    asyncio.run(po_ws_loop())














