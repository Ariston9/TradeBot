from datetime import datetime, timezone
from typing import Tuple, Optional, Dict, Any, List
import time

import pandas as pd

from .config import TFS, MAX_CANDLES
from .tv_api import get_tv_series
from .indicators import compute_indicators
from .scoring import score_on_tf, calc_overall_probability
from .logger import log_signal
from .pocket_ws import CURRENT_PO_PRICE, po_key


async def analyze_pair_for_user(user_id: int, pair: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    base = pair.replace(" ", "").replace("/", "")
    is_otc = base.startswith("OTC")

    if is_otc:
        asset = po_key(pair)
        po_data = CURRENT_PO_PRICE.get(asset)
        if not po_data:
            return None, "❌ Нет реальных котировок OTC в PocketOption"

        mid = po_data["mid"]
        direction = "BUY" if po_data["mid"] > po_data["bid"] else "SELL"
        prob = 75.0
        expiry = 3

        res = {
            "pair": pair,
            "dir": direction,
            "prob": prob,
            "expiry": expiry,
            "entry_price": mid,
        }
        return res, None

    tf_results: List[Dict[str, Any]] = []
    last_close_1m = None

    for tf_name, tf_int in TFS.items():
        df_tf, err = get_tv_series(pair, tf_int, MAX_CANDLES)
        time.sleep(0.8)
        if df_tf is None:
            print(f"⚠️ Не удалось получить данные {pair} {tf_int}: {err}")
            continue
        df_tf = compute_indicators(df_tf)
        ind = score_on_tf(df_tf, tf_name)
        ind["tf"] = tf_name
        tf_results.append(ind)
        if tf_int == "1min":
            last_close_1m = float(df_tf["close"].iloc[-1])

    if not tf_results:
        return None, f"Нет данных для {pair}. Проверь подключение к TradingView."

    prob = calc_overall_probability(tf_results)

    m1 = next((r for r in tf_results if r.get("tf") == "M1"), None)
    dirs = [r["direction"] for r in tf_results]
    buy_count = dirs.count("BUY")
    sell_count = dirs.count("SELL")

    overall = "NONE"
    if m1 and m1["direction"] in ("BUY", "SELL"):
        overall = m1["direction"]
    elif buy_count > sell_count:
        overall = "BUY"
    elif sell_count > buy_count:
        overall = "SELL"
    else:
        overall = "NONE"

    df_vol, _ = get_tv_series(pair, "1min", 50)
    if df_vol is not None and not df_vol.empty:
        vol_df = df_vol.copy()
        volatility = vol_df["close"].diff().abs().tail(10).mean()
    else:
        volatility = 0.0004

    expiry = None
    if prob >= 85:
        expiry = 3
    elif prob >= 75:
        expiry = 4
    elif prob >= 68:
        expiry = 4

    base_key = pair.replace(" ", "")
    po_asset = base_key.replace("/", "")
    po_data = CURRENT_PO_PRICE.get(po_asset)
    po_mid = po_data["mid"] if po_data else None

    df_1m, _ = get_tv_series(pair, "1min", 3)
    if df_1m is not None and not df_1m.empty:
        last = df_1m.iloc[-1]
        low_tv = float(last["low"])
        high_tv = float(last["high"])
        close_tv = float(last["close"])
    else:
        low_tv = high_tv = close_tv = last_close_1m

    if overall == "BUY":
        desired_entry = low_tv
        if po_mid:
            entry_price = max(desired_entry, po_mid)
        else:
            entry_price = desired_entry
    elif overall == "SELL":
        desired_entry = high_tv
        if po_mid:
            entry_price = min(desired_entry, po_mid)
        else:
            entry_price = desired_entry
    else:
        entry_price = close_tv

    if overall != "NONE" and expiry and m1 is not None and entry_price is not None:
        indicators = {
            "ema20": m1.get("ema20"),
            "macd_diff": m1.get("macd_diff"),
            "macd_vote": m1.get("macd_vote"),
            "rsi": m1.get("rsi"),
            "rsi_vote": m1.get("rsi_vote"),
            "rsi_pro_active": m1.get("rsi_pro_active"),
            "impulse": m1.get("impulse"),
            "pattern": m1.get("pattern"),
            "reversal_up": m1.get("reversal_up"),
            "reversal_down": m1.get("reversal_down"),
            "div_buy": m1.get("div_buy"),
            "div_sell": m1.get("div_sell"),
            "near_support": m1.get("near_support"),
            "near_resistance": m1.get("near_resistance"),
            "smc_type": m1.get("smc_type"),
            "smc_strength": m1.get("smc_strength"),
        }
        log_signal(pair, overall, prob, expiry, entry_price, indicators)

    res = {
        "pair": pair,
        "dir": overall,
        "prob": prob,
        "expiry": expiry,
        "entry_price": entry_price,
    }
    return res, None
