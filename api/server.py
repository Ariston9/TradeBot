from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

import asyncio

from bot.analyzer import analyze_pair_for_user

app = FastAPI(title="TradeBot WebAPI")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/get_signal")
async def get_signal(pair: str = "EUR/USD"):
    try:
        res, err = await analyze_pair_for_user(user_id=0, pair=pair)
        if err:
            return JSONResponse({"error": err}, status_code=400)
        return JSONResponse(res)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)
