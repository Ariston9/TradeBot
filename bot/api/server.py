# bot/api/server.py
from fastapi import FastAPI
from pydantic import BaseModel

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
