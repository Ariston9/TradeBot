# po_tick_server.py v10

import asyncio
import json
import threading
from typing import Dict, Set

from flask import Flask, request, jsonify

from po_candles import CandleBuilder  # из твоего po_candles.py
import websockets

# ====== НАСТРОЙКИ =====================================================

HTTP_HOST = "0.0.0.0"
HTTP_PORT = 9001          # REST /tick /ohlc /candles

WS_HOST = "0.0.0.0"
WS_PORT = 9002            # WebSocket ws://host:9002/ws

# Поддерживаемые таймфреймы
TF_MAP = {
    "M1": 60,
    "M5": 300,
    "M15": 900,
    "M30": 1800,
}

# ====== Flask-приложение (REST API) ==================================

app = Flask(__name__)

# Глобальные CandleBuilder-ы по таймфреймам
BUILDERS: Dict[int, CandleBuilder] = {
    sec: CandleBuilder(timeframe_sec=sec, max_candles=3000) for sec in TF_MAP.values()
}

# Последние тики по символу
LAST_TICK: Dict[str, dict] = {}

# ====== WebSocket сервер ==============================================

WS_CLIENTS: Set["websockets.WebSocketServerProtocol"] = set()
WS_LOOP = asyncio.new_event_loop()


async def ws_handler(ws, path):
    """Обработчик WebSocket-подключений (простой broadcast-сервер)."""
    if path != "/ws":
        await ws.close()
        return

    WS_CLIENTS.add(ws)
    try:
        # Можно отправить приветствие
        await ws.send(json.dumps({"event": "hello", "msg": "PO Streaming v10"}))
        async for _ in ws:  # просто держим соединение
            pass
    finally:
        WS_CLIENTS.discard(ws)


async def _ws_broadcast(message: str):
    """Асинхронная отправка сообщения всем клиентам."""
    if not WS_CLIENTS:
        return
    dead = []
    for ws in WS_CLIENTS:
        try:
            await ws.send(message)
        except Exception:
            dead.append(ws)
    for d in dead:
        WS_CLIENTS.discard(d)


def ws_broadcast_safe(payload: dict):
    """
    Потокобезопасная обёртка для старта coroutine _ws_broadcast из любого потока.
    Используется из Flask-хендлеров.
    """
    if not WS_CLIENTS:
        return
    msg = json.dumps(payload)
    asyncio.run_coroutine_threadsafe(_ws_broadcast(msg), WS_LOOP)


def start_ws_server():
    """Запуск WebSocket-сервера в отдельном потоке."""
    asyncio.set_event_loop(WS_LOOP)
    server_coro = websockets.serve(ws_handler, WS_HOST, WS_PORT, ping_interval=20, ping_timeout=20)
    WS_LOOP.run_until_complete(server_coro)
    print(f"🌐 WebSocket server started at ws://{WS_HOST}:{WS_PORT}/ws")
    WS_LOOP.run_forever()


# ====== Вспомогательные функции для свечей =============================

def on_po_tick(symbol: str, ts: float, price: float):
    """
    Обработка одного тика от PocketOption:
    - обновляем все таймфреймы
    - обновляем LAST_TICK
    - пушим событие в WebSocket
    """
    LAST_TICK[symbol] = {
        "symbol": symbol,
        "time": ts,
        "price": price,
    }

    # Обновляем свечи по всем таймфреймам
    for sec, builder in BUILDERS.items():
        builder.on_tick(symbol, int(ts * 1000), price)  # CandleBuilder сам разберет ms/sec

    # WebSocket-событие
    ws_broadcast_safe({
        "event": "tick",
        "symbol": symbol,
        "time": ts,
        "price": price,
    })


def on_po_history(symbol: str, period_sec: int, candles_raw):
    """
    Обработка истории:
    - пробегаемся по (ts, price) и прокармливаем CandleBuilder соответствующего tf
    - пушим событие 'history' в WebSocket
    """
    builder = BUILDERS.get(period_sec)
    if not builder:
        # Этот таймфрейм нам не нужен – просто проигнорируем или можно логировать
        return

    for ts, price in candles_raw:
        builder.on_tick(symbol, int(ts), float(price))

    ws_broadcast_safe({
        "event": "history",
        "symbol": symbol,
        "tf_sec": period_sec,
        "count": len(candles_raw),
    })


def get_tf_seconds(tf_param: str) -> int:
    """
    Преобразование tf строки в секунды.
    Поддерживает: M1/M5/M15/M30 или просто число (секунды).
    """
    tf_param = (tf_param or "").upper()
    if tf_param in TF_MAP:
        return TF_MAP[tf_param]

    # Попытка интерпретировать как число секунд
    try:
        sec = int(tf_param)
        if sec in BUILDERS:
            return sec
    except Exception:
        pass

    # по умолчанию M1
    return TF_MAP["M1"]


# ====== REST: получение свечей ========================================

@app.get("/ohlc")
def api_get_ohlc():
    """
    GET /ohlc?symbol=EURUSD_otc&tf=M1
    Возвращает последнюю свечу по символу и tf.
    """
    symbol = request.args.get("symbol")
    tf_param = request.args.get("tf", "M1")

    if not symbol:
        return jsonify({"error": "symbol required"}), 400

    sec = get_tf_seconds(tf_param)
    builder = BUILDERS.get(sec)
    if not builder:
        return jsonify({"error": f"unsupported tf: {tf_param}"}), 400

    df = builder.get_candles_df(symbol, limit=1)
    if df.empty:
        return jsonify({"error": "no data yet"}), 404

    row = df.iloc[-1]
    return jsonify({
        "symbol": symbol,
        "tf": tf_param,
        "time": row["datetime"].isoformat(),
        "open": float(row["open"]),
        "high": float(row["high"]),
        "low": float(row["low"]),
        "close": float(row["close"]),
    })


@app.get("/candles")
def api_get_candles():
    """
    GET /candles?symbol=EURUSD_otc&tf=M5&limit=200
    Возвращает массив свечей.
    """
    symbol = request.args.get("symbol")
    tf_param = request.args.get("tf", "M1")
    limit = int(request.args.get("limit", "200"))

    if not symbol:
        return jsonify({"error": "symbol required"}), 400

    sec = get_tf_seconds(tf_param)
    builder = BUILDERS.get(sec)
    if not builder:
        return jsonify({"error": f"unsupported tf: {tf_param}"}), 400

    df = builder.get_candles_df(symbol, limit=limit)
    if df.empty:
        return jsonify([])

    out = []
    for _, row in df.iterrows():
        out.append({
            "time": row["datetime"].isoformat(),
            "open": float(row["open"]),
            "high": float(row["high"]),
            "low": float(row["low"]),
            "close": float(row["close"]),
        })
    return jsonify(out)


@app.get("/last_tick")
def api_last_tick():
    """
    GET /last_tick?symbol=EURUSD_otc
    Возвращает последний тик по символу.
    """
    symbol = request.args.get("symbol")
    if not symbol:
        return jsonify({"error": "symbol required"}), 400

    data = LAST_TICK.get(symbol)
    if not data:
        return jsonify({"error": "no tick yet"}), 404
    return jsonify(data)


# ====== REST: приём данных от po_cdp_hook ===============================

@app.post("/tick")
def api_receive_tick():
    """
    po_cdp_hook шлёт сюда 2 типа сообщений:

    1) Тик:
       {
         "type": "tick",
         "symbol": "EURUSD_otc",
         "time":  1766501234.567,
         "price": 1.23456
       }

    2) История:
       {
         "type":   "history",
         "symbol": "EURUSD_otc",
         "period": 60,  # секунды -> M1
         "candles": [
            [ts1, price1],
            [ts2, price2],
            ...
         ]
       }
    """
    data = request.get_json(force=True)
    msg_type = data.get("type", "tick")

    if msg_type == "tick":
        symbol = str(data["symbol"])
        ts = float(data["time"])
        price = float(data["price"])
        on_po_tick(symbol, ts, price)

    elif msg_type == "history":
        symbol = str(data["symbol"])
        period = int(data.get("period", 60))
        raw_candles = data.get("candles", [])
        candles = []
        for item in raw_candles:
            ts, price = item
            candles.append((float(ts), float(price)))
        on_po_history(symbol, period, candles)

    else:
        return jsonify({"status": "ignored", "reason": "unknown type"}), 400

    return jsonify({"status": "ok"})


# ====== Запуск =========================================================

def start_http():
    print(f"🚀 HTTP tick-server at http://{HTTP_HOST}:{HTTP_PORT}")
    app.run(host=HTTP_HOST, port=HTTP_PORT)


if __name__ == "__main__":
    # WebSocket-сервер в отдельном потоке
    t_ws = threading.Thread(target=start_ws_server, daemon=True)
    t_ws.start()

    # HTTP (Flask) в главном потоке
    start_http()
