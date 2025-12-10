from pathlib import Path
import os
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
TV_USERNAME = os.getenv("TV_USERNAME")
TV_PASSWORD = os.getenv("TV_PASSWORD")
PO_ENGINE_HTTP = "http://34.79.192.92:8000"  # свой VPS
SIGNAL_CHAT_ID = int(os.getenv("SIGNAL_CHAT_ID", "0"))
API_URL = "https://philologic-resentfully-kimberlee.ngrok-free.dev" # "https://tradebot-production-74c0.up.railway.app/"

DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)
LOG_FILE = DATA_DIR / "signals.csv"

PAIRS = [
    "EUR/USD","EUR/GBP","EUR/AUD","EUR/JPY","EUR/CHF","EUR/CAD",
    "GBP/USD","GBP/JPY","GBP/CAD","GBP/AUD","GBP/CHF",
    "USD/JPY","USD/CAD","USD/CHF",
    "AUD/USD","AUD/JPY","AUD/CAD","AUD/CHF",
    "CAD/JPY","CAD/CHF",
    # OTC (доступно только через PocketOption)
    "OTC_EURUSD","OTC_GBPUSD","OTC_USDCAD","OTC_USDJPY"
]

TFS = {"M1":"1min","M5":"5min","M15":"15min"}
MAX_CANDLES = 120
REQUEST_DELAY = 0.8
CLEAN_DAYS = 300

TV_MAP = {
    "EUR/USD": ("EURUSD","OANDA"),
    "EUR/GBP": ("EURGBP","OANDA"),
    "EUR/AUD": ("EURAUD","OANDA"),
    "EUR/JPY": ("EURJPY","OANDA"),
    "EUR/CHF": ("EURCHF","OANDA"),
    "EUR/CAD": ("EURCAD","OANDA"),
    "GBP/USD": ("GBPUSD","OANDA"),
    "GBP/CAD": ("GBPCAD","OANDA"),
    "GBP/AUD": ("GBPAUD","OANDA"),
    "GBP/CHF": ("GBPCHF","OANDA"),
    "GBP/JPY": ("GBPJPY","OANDA"),
    "USD/JPY": ("USDJPY","OANDA"),
    "USD/CAD": ("USDCAD","OANDA"),
    "USD/CHF": ("USDCHF","OANDA"),
    "AUD/USD": ("AUDUSD","OANDA"),
    "AUD/JPY": ("AUDJPY","OANDA"),
    "AUD/CAD": ("AUDCAD","OANDA"),
    "AUD/CHF": ("AUDCHF","OANDA"),
    "CAD/JPY": ("CADJPY","OANDA"),
    "CAD/CHF": ("CADCHF","OANDA"),
}

# соответствие WOG → POEngine
PO_SYMBOL_MAP = {
    "EUR/USD": "EURUSD",
    "GBP/USD": "GBPUSD",
    "USD/JPY": "USDJPY",
    "USD/CAD": "USDCAD",

    "OTC_EURUSD": "EURUSD_otc",
    "OTC_GBPUSD": "GBPUSD_otc",
    "OTC_USDCAD": "USDCAD_otc",
    "OTC_USDJPY": "USDJPY_otc",
}


def tv_chart_url(pair: str) -> str:
    sym, ex = TV_MAP[pair]
    return f"https://www.tradingview.com/chart/?symbol={ex}:{sym}"
