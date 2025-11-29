from fastapi import FastAPI
from pydantic import BaseModel
from .analyzer import analyze_pair_for_user
from .config import PAIRS
from .logger import get_last_signal

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
    sig = get_last_signal()
    if sig is None:
        return {"signal": None}
    return {"signal": sig}

