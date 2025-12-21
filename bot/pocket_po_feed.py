# bot/pocket_po_feed.py
# ==========================================
# Pocket Option price feed (CLIENT)
# Reads data from po_tick_server
# ==========================================

import time
import threading
import requests
from typing import Optional, Dict

# ================= CONFIG =================

PO_TICK_SERVER_HTTP = "http://127.0.0.1:9001"
TICK_TTL_SEC = 2.5          # сколько секунд тик считается живым
POLL_INTERVAL = 0.4         # частота опроса сервера
DEFAULT_ACCOUNT = "REAL"

# ================= STORAGE =================

CURRENT_PO_PRICE: Dict[str, Dict] = {}
_LAST_UPDATE_TS = 0.0
_LOCK = threading.Lock()


# ================= INTERNAL =================

def _poll_last_ticks():
    """
    Фоновый опрос po_tick_server (/last_tick)
    """
    global _LAST_UPDATE_TS

    while True:
        try:
            r = requests.get(
                f"{PO_TICK_SERVER_HTTP}/last_tick",
                timeout=2
            )

            if r.status_code == 200:
                data = r.json()

                # ожидаемый формат:
                # {
                #   "symbol": "AUDNZD_otc",
                #   "price": 1.28857,
                #   "time": 1730000000.123,
                #   "account": "REAL"
                # }

                symbol = data.get("symbol")
                if symbol:
                    with _LOCK:
                        CURRENT_PO_PRICE[symbol] = {
                            "price": float(data["price"]),
                            "ts": float(data["time"]),
                            "account": data.get("account", DEFAULT_ACCOUNT),
                        }
                        _LAST_UPDATE_TS = time.time()

        except Exception:
            pass

        time.sleep(POLL_INTERVAL)


# ================= PUBLIC API =================

def start_po_price_feed():
    """
    Запуск фонового потока получения цен
    """
    t = threading.Thread(target=_poll_last_ticks, daemon=True)
    t.start()
    return t


def get_po_price(pair: str, account: str = DEFAULT_ACCOUNT) -> Optional[float]:
    """
    Получить последнюю цену Pocket Option
    pair: "AUDNZD", "EURUSD"
    account: REAL / DEMO
    """
    asset = pair.replace("/", "")
    t = CURRENT_PO_PRICE.get(asset)

    if not t:
        return None

    if t["account"] != account:
        return None

    if time.time() - t["ts"] > TICK_TTL_SEC:
        return None

    return t["price"]


def get_po_tick_raw(pair: str) -> Optional[Dict]:
    """
    Вернуть полный raw-тик (для логов / отладки)
    """
    asset = pair.replace("/", "")
    return CURRENT_PO_PRICE.get(asset)
