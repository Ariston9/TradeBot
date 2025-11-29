from datetime import datetime, timezone
from io import BytesIO
from typing import Dict, Any, Tuple

import matplotlib.pyplot as plt
import pandas as pd

from .config import LOG_FILE
from .tv_api import get_tv_series


def init_log():
    if not LOG_FILE.exists():
        df = pd.DataFrame(
            columns=[
                "timestamp_utc","pair","direction","probability",
                "expiry_min","entry_price","evaluated","result"
            ]
        )
        df.to_csv(LOG_FILE, index=False)


def log_signal(pair: str, direction: str, probability: float, expiry_min: int, entry_price: float, indicators: Dict[str, Any] | None = None):
    init_log()
    try:
        df = pd.read_csv(LOG_FILE, dtype={"result": "string", "evaluated": "bool"})
    except FileNotFoundError:
        df = pd.DataFrame()

    row = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "pair": pair,
        "direction": direction,
        "probability": probability,
        "expiry_min": expiry_min,
        "entry_price": entry_price,
        "evaluated": False,
        "result": ""
    }

    if indicators:
        row.update(indicators)

    row_df = pd.DataFrame([row])
    if not df.empty:
        df = pd.concat([df, row_df], ignore_index=True)
    else:
        df = row_df

    df["result"] = df["result"].astype("string")
    df["evaluated"] = df["evaluated"].astype(bool)

    df.to_csv(LOG_FILE, index=False)


def evaluate_signal_entry(entry_row) -> Tuple[str, float | None, str | None]:
    try:
        t0 = pd.to_datetime(entry_row["timestamp_utc"]).tz_convert("UTC")
    except Exception:
        t0 = pd.to_datetime(entry_row["timestamp_utc"]).tz_localize("UTC")

    expiry = int(entry_row["expiry_min"])
    target = t0 + pd.Timedelta(minutes=expiry)

    df, err = get_tv_series(entry_row["pair"], "1min", 300)
    if df is None or df.empty:
        return "ERROR", None, err

    idx = df["dt_utc"].searchsorted(target)
    if idx >= len(df):
        return "PENDING", None, "no bar yet"

    price_at = float(df["close"].iloc[idx].item())

    if (entry_row["direction"] == "BUY" and price_at > entry_row["entry_price"]) or            (entry_row["direction"] == "SELL" and price_at < entry_row["entry_price"]):
        res = "WIN"
    else:
        res = "LOSE"

    return res, price_at, None


def stats_last_24h():
    init_log()
    try:
        df = pd.read_csv(LOG_FILE)
    except FileNotFoundError:
        return {"total":0, "wins":0, "losses":0, "winrate":0.0}

    if df.empty:
        return {"total":0, "wins":0, "losses":0, "winrate":0.0}

    now = datetime.now(timezone.utc)
    df["timestamp_utc"] = pd.to_datetime(df["timestamp_utc"], utc=True, errors="coerce")

    last24 = df[df["timestamp_utc"] >= (now - pd.Timedelta(hours=24))].copy()
    last24["expiry_min"] = pd.to_numeric(last24["expiry_min"], errors="coerce")
    last24 = last24.dropna(subset=["expiry_min"])
    last24["done"] = last24["timestamp_utc"] + pd.to_timedelta(last24["expiry_min"].astype(int), unit="m")
    mask_done = last24["done"] <= now
    mask_eval = last24.get("evaluated", False).astype(bool) if "evaluated" in last24.columns else True
    subset = last24[mask_done & mask_eval].copy()

    wins = int((subset["result"] == "WIN").sum())
    losses = int((subset["result"] == "LOSE").sum())
    total_eval = wins + losses
    winrate = round((wins / total_eval) * 100, 2) if total_eval > 0 else 0.0

    return {"total": total_eval, "wins": wins, "losses": losses, "winrate": winrate}


def build_pie(wins: int, losses: int):
    if wins + losses == 0:
        return None
    fig, ax = plt.subplots(figsize=(4, 4))
    ax.pie(
        [wins, losses],
        labels=["Плюс", "Минус"],
        autopct="%1.0f%%",
        startangle=90,
        colors=["#4CAF50", "#F44336"],
    )
    ax.axis("equal")
    buf = BytesIO()
    plt.savefig(buf, format="png", bbox_inches="tight")
    buf.seek(0)
    plt.close(fig)
    return buf


def evaluate_pending_signals():
    init_log()
    try:
        df = pd.read_csv(LOG_FILE, dtype={"result": "string", "evaluated": "bool"})
    except FileNotFoundError:
        print("⚠️ signals.csv не найден")
        return

    if df.empty:
        return

    now = datetime.now(timezone.utc)
    updated = wins = losses = 0

    for i, row in df.iterrows():
        if str(row.get("evaluated", False)) == "True":
            continue

        ts = pd.to_datetime(row["timestamp_utc"], utc=True, errors="coerce")
        expiry = int(row.get("expiry_min", 0) or 0)
        if pd.isna(ts) or expiry <= 0:
            continue
        if ts + pd.Timedelta(minutes=expiry) > now:
            continue

        res, price_at, err = evaluate_signal_entry(row)
        if res in ("WIN", "LOSE"):
            df.at[i, "result"] = res
            df.at[i, "evaluated"] = True
            if price_at is not None:
                df.at[i, "price_at_expiry"] = price_at
            updated += 1
            wins += (res == "WIN")
            losses += (res == "LOSE")

    if updated > 0:
        df.to_csv(LOG_FILE, index=False)
        print(f"✅ Оценено: {updated} (WIN: {wins}, LOSE: {losses})")
    else:
        print("ℹ️ Новых завершённых сигналов нет.")
        
def read_signals_log(symbol: str):
    """
    Читает signals.csv и возвращает сигналы по символу.
    symbol приходит без слэша: EURUSD
    """
    try:
        rows = []
        with open("signals.csv", "r", encoding="utf-8") as f:
            for line in f.readlines()[1:]:  # пропускаем заголовок
                parts = line.strip().split(",")
                if len(parts) < 6:
                    continue

                t, pair, direction, prob, expiry, reason = parts

                # Приводим EUR/USD → EURUSD для сравнения
                if pair.replace("/", "") == symbol:
                    rows.append({
                        "time": t,
                        "symbol": pair,
                        "direction": direction,
                        "prob": prob,
                        "expiry": expiry,
                        "reason": reason,
                    })
        return rows
    except FileNotFoundError:
        return []
