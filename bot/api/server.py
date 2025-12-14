# bot/api/server.py
from fastapi import FastAPI, Query, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from bot.pocket_po_feed import CURRENT_PO_PRICE
import asyncio
import time
import json
import websockets

from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from bot.analyzer import analyze_pair_for_user
from bot.config import PAIRS
from bot.logger import read_signals_log


app = FastAPI(title="TradeBot API")


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class PairRequest(BaseModel):
    pair: str


@app.get("/pairs")
def get_pairs():
    return {"pairs": PAIRS}


@app.post("/analyze")
async def api_analyze(req: PairRequest):
    """
    Анализ валютной пары через REST API для WebApp.
    """
    res, err = await analyze_pair_for_user(0, req.pair)

    if err:
        return JSONResponse({"error": err}, status_code=400)

    return JSONResponse(res)


@app.get("/signals")
def get_signals(symbol: str):
    """
    История сигналов (symbol: EURUSD)
    """
    rows = read_signals_log(symbol)
    return JSONResponse(rows)
   #---------------- Для вывода сигналов в автоскан--------- 
# @app.get("/autoscan")
# def autoscan():
#     return JSONResponse(LATEST_SIGNALS)

@app.get("/get_signal")
async def get_signal(pair: str = Query(...)):
    # Если пришло EURUSD → превращаем в EUR/USD
    if "/" not in pair and len(pair) == 6:
        pair = pair[:3] + "/" + pair[3:]

    res, err = await analyze_pair_for_user(0, pair)

    if err:
        return JSONResponse({"error": err}, status_code=400)

    return JSONResponse(res)
    
@app.websocket("/ws")
async def ws_price_feed(ws: WebSocket):
    await ws.accept()
    print("✅ WS client connected")

    try:
        last_sent = {}

        while True:
            # отправляем только если цена изменилась
            for symbol, data in CURRENT_PO_PRICE.items():
                price = data.get("price")
                ts = data.get("time")

                if not price:
                    continue

                if last_sent.get(symbol) == price:
                    continue

                payload = {
                    "event": "tick",
                    "symbol": symbol,
                    "price": price,
                    "time": ts,
                }

                await ws.send_json(payload)
                last_sent[symbol] = price

            await asyncio.sleep(0.25)

    except WebSocketDisconnect:
        print("❌ WS client disconnected")

    except Exception as e:
        print("❌ WS error:", e)

    finally:
        await safe_close(ws)
        print("🛑 WS session closed")

@app.get("/stats")
def api_stats(symbol: str):
    """
    Возвращает статистику для WebApp:
    total, wins, losses, buy, sell, winrate, avg_prob, last_active
    """
    import pandas as pd
    from bot.config import LOG_FILE

    try:
        df = pd.read_csv(LOG_FILE)
    except:
        return {
            "total": 0, "wins": 0, "losses": 0,
            "buy": 0, "sell": 0,
            "winrate": 0, "avg_prob": 0,
            "last_active": "–"
        }

    # фильтруем по символу
    df["pair"] = df["pair"].astype(str)
    df_sym = df[df["pair"].str.replace("/", "") == symbol]

    if df_sym.empty:
        return {
            "total": 0, "wins": 0, "losses": 0,
            "buy": 0, "sell": 0,
            "winrate": 0, "avg_prob": 0,
            "last_active": "–"
        }

    total = len(df_sym)
    wins = int((df_sym["result"] == "WIN").sum())
    losses = int((df_sym["result"] == "LOSE").sum())
    buy = int((df_sym["direction"] == "BUY").sum())
    sell = int((df_sym["direction"] == "SELL").sum())
    avg_prob = round(df_sym["probability"].astype(float).mean(), 1)
    last = df_sym["timestamp_utc"].iloc[-1]

    winrate = round((wins / (wins + losses)) * 100, 1) if (wins + losses) > 0 else 0

    return {
        "total": total,
        "wins": wins,
        "losses": losses,
        "buy": buy,
        "sell": sell,
        "winrate": winrate,
        "avg_prob": avg_prob,
        "last_active": last,
    }





