import json
import time
import base64
import threading
import traceback

import requests
import websocket

"""
po_cdp_hook v10

1. Подключается к Chrome DevTools (порт 9222).
2. Находит вкладку PocketOption /demo-quick-high-low/.
3. Включает Network → ловит WebSocket фреймы.
4. Для бинарных фреймов:
   - тип 1: ["EURUSD_otc", timestamp, price] → шлёт тип "tick" на сервер.
   - тип 2: ["EURUSD_otc", period, [[ts, price], ...]] → шлёт тип "history".
"""

CDP_URL = "http://localhost:9222/json"
TICK_SERVER_URL = "http://127.0.0.1:9001/tick"


# ========= ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ =========================================

def _send(ws, msg_id, method, params=None):
    """Отправить команду DevTools в WebSocket."""
    payload = {"id": msg_id, "method": method}
    if params:
        payload["params"] = params
    ws.send(json.dumps(payload))
    return msg_id + 1


def _pretty_try_decode_binary(payload_b64: str) -> str:
    """base64 → bytes → utf8 (если можно), иначе короткий hex-дамп."""
    try:
        raw = base64.b64decode(payload_b64)
    except Exception:
        return f"<bin len={len(payload_b64)} b64, decode_error>"

    try:
        txt = raw.decode("utf-8")
        if len(txt) > 500:
            txt = txt[:500] + " …"
        return txt
    except UnicodeDecodeError:
        hex_part = raw[:32].hex()
        return f"<bin bytes={len(raw)}, head_hex={hex_part}>"


def push_tick_to_server_tick(symbol: str, ts: float, price: float):
    """Отправляем одиночный тик на tick-server."""
    payload = {
        "type": "tick",
        "symbol": symbol,
        "time": ts,
        "price": price,
    }
    try:
        requests.post(TICK_SERVER_URL, json=payload, timeout=0.3)
    except Exception as e:
        print("Push tick error:", e)


def push_tick_to_server_history(symbol: str, period: int, candles):
    """Отправляем пачку истории (список (ts, price)) на tick-server."""
    payload = {
        "type": "history",
        "symbol": symbol,
        "period": period,
        "candles": candles,
    }
    try:
        requests.post(TICK_SERVER_URL, json=payload, timeout=0.5)
    except Exception as e:
        print("Push history error:", e)


# ========= ОБРАБОТКА СОБЫТИЙ DEVTOOLS ======================================

def handle_event(message: dict):
    method = message.get("method")
    if not method:
        return

    params = message.get("params", {})

    # Создание WebSocket
    if method == "Network.webSocketCreated":
        url = params.get("url", "")
        request_id = params.get("requestId")
        print(f"🛰  WS CREATED: id={request_id} url={url}")
        return

    # Полученный WebSocket-фрейм
    if method == "Network.webSocketFrameReceived":
        resp = params.get("response", {})
        opcode = resp.get("opcode")        # 1 = text, 2 = binary
        data = resp.get("payloadData", "")
        ws_id = params.get("requestId", "?")

        # ----- ТЕКСТ -----
        if opcode == 1:
            if "updateStream" in data or "updateAssets" in data or "indicator/load" in data:
                print(f"💬 WS TEXT [{ws_id}]: {data}")
            return

        # ----- БИНАРКА -----
        if opcode == 2:
            decoded = _pretty_try_decode_binary(data)
            print(f"📦 WS BIN  [{ws_id}]: {decoded}")

            try:
                obj = json.loads(decoded)

                # если внутри ещё один список: [[...]]
                if isinstance(obj, list) and len(obj) == 1 and isinstance(obj[0], list):
                    obj = obj[0]

                # ===== BIN TYPE 1 — одиночный тик: ["EURUSD_otc", timestamp, price]
                if (
                    isinstance(obj, list)
                    and len(obj) == 3
                    and isinstance(obj[1], (int, float))
                    and isinstance(obj[2], (int, float))
                ):
                    symbol = obj[0]
                    ts = float(obj[1])
                    price = float(obj[2])

                    print(f"[TICK] {symbol} {price} @ {ts}")
                    push_tick_to_server_tick(symbol, ts, price)

                # ===== BIN TYPE 2 — история: ["EURUSD_otc", 60, [[ts, price], ...]]
                elif (
                    isinstance(obj, list)
                    and len(obj) == 3
                    and isinstance(obj[1], int)
                    and isinstance(obj[2], list)
                ):
                    asset = obj[0]
                    period = int(obj[1])
                    history = obj[2]

                    candles = []
                    for item in history:
                        ts, price = item
                        candles.append((float(ts), float(price)))

                    if candles:
                        print(f"[HISTORY {period}] {asset} len={len(candles)}")
                        push_tick_to_server_history(asset, period, candles)

            except Exception as e:
                print("Tick parse error:", e)
                traceback.print_exc()

            return


# ========= ПОДКЛЮЧЕНИЕ К DEVTOOLS =========================================

def connect_devtools_ws(ws_url: str):
    print(f"🔌 Подключаемся к DevTools: {ws_url}")
    ws = websocket.create_connection(ws_url)
    print("✅ DevTools WS open")

    msg_id = 1
    msg_id = _send(ws, msg_id, "Network.enable", {})
    msg_id = _send(ws, msg_id, "Runtime.enable", {})
    print("🛰  Network.enable отправлен, ждём события WebSocket...")

    def receiver():
        while True:
            try:
                raw = ws.recv()
            except Exception as e:
                print("❌ DevTools WS recv error:", e)
                break

            try:
                msg = json.loads(raw)
            except Exception:
                continue

            try:
                handle_event(msg)
            except Exception:
                print("⚠️ handle_event error:")
                traceback.print_exc()

    threading.Thread(target=receiver, daemon=True).start()
    return ws


# ========= ТОЧКА ВХОДА =====================================================

def main():
    # 1) Получаем список DevTools-таргетов
    try:
        tabs = requests.get(CDP_URL).json()
    except Exception as e:
        print("❌ Не удалось получить список вкладок DevTools:", e)
        print("   Проверь, что Chrome запущен с --remote-debugging-port=9222")
        return

    print("Найдены вкладки:")
    for i, t in enumerate(tabs):
        print(f"  {i}: {t.get('url')}")

    # 2) Ищем PocketOption /demo-quick-high-low/
    po_tab = None
    for t in tabs:
        url = t.get("url", "")
        if "pocketoption.com" in url and "demo-quick-high-low" in url:
            po_tab = t
            break

    if not po_tab:
        print("❌ Не найдено активной вкладки PocketOption /demo-quick-high-low/")
        print("   Открой эту страницу в том же Chrome, что запущен с портом 9222.")
        return

    print("🌐 Используем вкладку:", po_tab["url"])
    ws_url = po_tab["webSocketDebuggerUrl"]

    connect_devtools_ws(ws_url)

    print("👌 Waiting for WS messages...")
    while True:
        time.sleep(1)


if __name__ == "__main__":
    main()
