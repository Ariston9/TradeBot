# bot/pocket_po_feed.py
# One-file PocketOption tick -> candles server via Chrome DevTools (CDP)
# Runs:
#  - Flask API on http://127.0.0.1:9001 (health, candles)
#  - CDP listener подключается к уже открытому Chrome (9222) и ловит WebSocket фреймы PO

import json
import time
import threading
from dataclasses import dataclass
from typing import Dict, Optional, List, Any

from flask import Flask, request, jsonify
import websocket  # websocket-client
import urllib.request


# ---------------------------
# Candle aggregation
# ---------------------------

@dataclass
class Candle:
    t: int            # candle open timestamp (sec)
    o: float
    h: float
    l: float
    c: float
    v: int = 0


class CandleStore:
    def __init__(self, tf_sec: int = 60, max_candles: int = 500):
        self.tf = tf_sec
        self.max_candles = max_candles
        self._data: Dict[str, List[Candle]] = {}
        self._lock = threading.Lock()

    def on_tick(self, symbol: str, price: float, ts: Optional[float] = None):
        if ts is None:
            ts = time.time()
        ts_i = int(ts)
        bucket = ts_i - (ts_i % self.tf)

        with self._lock:
            arr = self._data.setdefault(symbol, [])
            if not arr or arr[-1].t != bucket:
                # start new candle
                c = Candle(t=bucket, o=price, h=price, l=price, c=price, v=1)
                arr.append(c)
                if len(arr) > self.max_candles:
                    del arr[: len(arr) - self.max_candles]
            else:
                c = arr[-1]
                c.c = price
                if price > c.h:
                    c.h = price
                if price < c.l:
                    c.l = price
                c.v += 1

    def get_candles(self, symbol: str, limit: int = 200) -> List[Dict[str, Any]]:
        with self._lock:
            arr = self._data.get(symbol, [])
            arr = arr[-max(1, min(limit, self.max_candles)) :]
            return [{"t": c.t, "o": c.o, "h": c.h, "l": c.l, "c": c.c, "v": c.v} for c in arr]


STORE = CandleStore(tf_sec=60, max_candles=1000)


# ---------------------------
# Flask API
# ---------------------------

app = Flask(__name__)

@app.get("/health")
def health():
    return jsonify({"ok": True, "ts": time.time()})

@app.get("/candles")
def candles():
    symbol = request.args.get("symbol") or request.args.get("sym") or ""
    symbol = symbol.strip()
    limit = int(request.args.get("limit", "200"))
    if not symbol:
        return jsonify({"ok": False, "error": "symbol required, e.g. ?symbol=OTC_EURUSD"}), 400
    return jsonify({"ok": True, "symbol": symbol, "tf": STORE.tf, "candles": STORE.get_candles(symbol, limit=limit)})


# ---------------------------
# CDP (Chrome DevTools) listener
# ---------------------------

CDP_HTTP = "http://127.0.0.1:9222"
PO_DOMAIN_HINT = "pocketoption.com"  # ищем вкладку по домену

def _http_get_json(url: str):
    with urllib.request.urlopen(url, timeout=3) as r:
        return json.loads(r.read().decode("utf-8", errors="ignore"))

def find_pocketoption_target_ws() -> str:
    targets = _http_get_json(f"{CDP_HTTP}/json")
    # выбираем самую “жирную” вкладку pocketoption (page)
    for t in targets:
        url = (t.get("url") or "").lower()
        typ = (t.get("type") or "").lower()
        if typ == "page" and PO_DOMAIN_HINT in url:
            ws = t.get("webSocketDebuggerUrl")
            if ws:
                return ws
    # fallback: иногда pocketoption внутри iframe, но page url остаётся pocketoption
    raise RuntimeError("PocketOption tab not found in /json. Open PO in Chrome and refresh the page.")

def _socketio_extract(payload: str):
    """
    PocketOption часто использует socket.io.
    Типично: '42["event", {...}]'
    Иногда приходят и другие префиксы — их просто игнорим.
    """
    if not isinstance(payload, str):
        return None, None

    # socket.io event
    if payload.startswith("42"):
        try:
            arr = json.loads(payload[2:])
            if isinstance(arr, list) and len(arr) >= 2:
                return arr[0], arr[1]
        except Exception:
            return None, None

    return None, None


def run_cdp_loop():
    ws_url = find_pocketoption_target_ws()
    print(f"✅ Found PO tab: {ws_url}")

    ws = websocket.WebSocket()
    ws.connect(ws_url, timeout=5)

    # enable Network domain to receive ws frames
    msg_id = 0
    def send(method, params=None):
        nonlocal msg_id
        msg_id += 1
        payload = {"id": msg_id, "method": method}
        if params:
            payload["params"] = params
        ws.send(json.dumps(payload))

    send("Network.enable")
    send("Page.enable")

    print("🟢 CDP connected, listening WS frames...")

    last_print = 0.0

    while True:
        raw = ws.recv()
        if not raw:
            continue

        try:
            data = json.loads(raw)
        except Exception:
            continue

        method = data.get("method")
        params = data.get("params") or {}

        # incoming websocket frame
        if method == "Network.webSocketFrameReceived":
            payload = (((params.get("response") or {}).get("payloadData")) or "")
            event, body = _socketio_extract(payload)

            # ВАЖНО: названия событий у PO могут отличаться.
            # Поэтому:
            # 1) если увидим явный tick — парсим
            # 2) иначе иногда печатаем “сырьё”, чтобы понять событие
            if event in ("tick", "ticks", "quote", "quotes") and isinstance(body, dict):
                symbol = body.get("symbol") or body.get("asset") or body.get("pair")
                price = body.get("price") or body.get("p") or body.get("value")
                ts = body.get("time") or body.get("ts")

                if symbol and price is not None:
                    try:
                        STORE.on_tick(str(symbol), float(price), float(ts) if ts else None)
                        print(f"TICK: {symbol} {price}")
                    except Exception:
                        pass
            else:
                # раз в ~5 секунд показываем “что вообще летит” (не спамим каждое сообщение)
                now = time.time()
                if now - last_print > 5:
                    last_print = now
                    if isinstance(payload, str) and payload.startswith("42"):
                        # покажем только первые ~200 символов
                        print("WS sample:", payload[:200])

        # closed
        if method == "Inspector.detached":
            raise RuntimeError("CDP detached (tab closed / chrome restarted).")


def main():
    # CDP в фоне, API в главном потоке
    t = threading.Thread(target=run_cdp_loop, daemon=True)
    t.start()

    print("🚀 Tick/Candles server: http://127.0.0.1:9001")
    app.run(host="0.0.0.0", port=9001, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()
