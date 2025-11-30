from fastapi import FastAPI
from pydantic import BaseModel

from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from bot.analyzer import analyze_pair_for_user
from bot.config import PAIRS
from bot.logger import read_signals_log

api = FastAPI(title="TradeBot API")


class PairRequest(BaseModel):
    pair: str


@api.get("/status")
def status():
    return {"status": "ok", "pairs": PAIRS}


@api.post("/analyze")
async def api_analyze(req: PairRequest):
    """
    Анализ валютной пары через REST API для WebApp.
    """
    res, err = await analyze_pair_for_user(0, req.pair)

    if err:
        return {"error": err}

    return res


@api.get("/last_signal")
def last_signal():
    """
    Возвращает последний сигнал из logs/signals.csv
    """
    sig = read_signals_log()
    if sig is None:
        return {"signal": None}
    return {"signal": sig}

