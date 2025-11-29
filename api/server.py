# bot/api/server.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from bot.analyzer import analyze_pair_for_user
from bot.logger import read_signals_log
from bot.config import PAIRS  # теперь API знает доступные пары

app = FastAPI(title="TradeBot WebAPI")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/pairs")
def get_pairs():
    """
    Возвращает все пары, которые доступны боту (из config.py)
    """
    return {"pairs": PAIRS}


@app.get("/get_signal")
async def get_signal(pair: str):
    """
    Возвращает анализ для ЛЮБОЙ пары, которая есть в config.PAIRS
    """
    # проверяем существование пары
    if pair not in PAIRS:
        return JSONResponse(
            {"error": f"Пара {pair} не найдена в списке доступных."},
            status_code=400
        )

    try:
        res, err = await analyze_pair_for_user(user_id=0, pair=pair)
        if err:
            return JSONResponse({"error": err}, status_code=400)
        return JSONResponse(res)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/signals")
def get_signals(symbol: str):
    """
    История сигналов: symbol = EURUSD (без слэша)
    """
    try:
        hist = read_signals_log(symbol)
        return JSONResponse(hist)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)
