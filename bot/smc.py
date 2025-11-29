import pandas as pd


def detect_reversal(df: pd.DataFrame, swing_lookback: int = 3):
    if df is None or len(df) < swing_lookback * 4:
        return {
            "reversal_up": False,
            "reversal_down": False,
            "type": "NONE",
            "strength": 0.0,
            "last_swing_high": None,
            "last_swing_low": None,
        }

    highs = df["high"].values
    lows = df["low"].values
    close = df["close"].iloc[-1]

    swing_high_idx = None
    swing_low_idx = None

    for i in range(len(df) - swing_lookback * 2, swing_lookback, -1):
        window = df.iloc[i - swing_lookback : i + swing_lookback + 1]
        center = df.iloc[i]
        if float(center["high"]) == float(window["high"].max()):
            swing_high_idx = i
            break

    for i in range(len(df) - swing_lookback * 2, swing_lookback, -1):
        window = df.iloc[i - swing_lookback : i + swing_lookback + 1]
        center = df.iloc[i]
        if float(center["low"]) == float(window["low"].min()):
            swing_low_idx = i
            break

    if swing_high_idx is None or swing_low_idx is None:
        return {
            "reversal_up": False,
            "reversal_down": False,
            "type": "NONE",
            "strength": 0.0,
            "last_swing_high": None,
            "last_swing_low": None,
        }

    last_swing_high = highs[swing_high_idx]
    last_swing_low = lows[swing_low_idx]

    reversal_up = False
    reversal_down = False
    reversal_type = "NONE"
    strength = 0.0

    if close > last_swing_high:
        reversal_up = True
        strength = (close - last_swing_high) / last_swing_high
        reversal_type = "CHoCH_UP"

    if close < last_swing_low:
        reversal_down = True
        strength = (last_swing_low - close) / last_swing_low
        reversal_type = "CHoCH_DOWN"

    if reversal_up and reversal_down:
        if abs(close - last_swing_high) > abs(close - last_swing_low):
            reversal_down = False
            reversal_type = "CHoCH_UP"
        else:
            reversal_up = False
            reversal_type = "CHoCH_DOWN"

    if reversal_up and close > last_swing_high * 1.001:
        reversal_type = "BOS_UP"
    if reversal_down and close < last_swing_low * 0.999:
        reversal_type = "BOS_DOWN"

    return {
        "reversal_up": reversal_up,
        "reversal_down": reversal_down,
        "type": reversal_type,
        "strength": float(strength),
        "last_swing_high": float(last_swing_high),
        "last_swing_low": float(last_swing_low),
    }


def detect_smc_levels(df: pd.DataFrame, swing_lookback: int = 3, tolerance_factor: float = 0.5):
    if df is None or len(df) < swing_lookback * 3:
        return {
            "swing_high": None,
            "swing_low": None,
            "type": "NONE",
            "strength": 0.0,
            "rejection_up": False,
            "rejection_down": False,
        }

    highs = df["high"].values
    lows = df["low"].values
    close = df["close"].iloc[-1]
    last = df.iloc[-1]
    high = last["high"]
    low = last["low"]

    atr = (df["high"].iloc[-1] - df["low"].iloc[-1])
    tolerance = atr * tolerance_factor

    swing_high_idx = swing_low_idx = None

    for i in range(len(df) - 6, swing_lookback, -1):
        w = df.iloc[i - swing_lookback : i + swing_lookback + 1]
        if df.iloc[i]["high"] == w["high"].max():
            swing_high_idx = i
            break

    for i in range(len(df) - 6, swing_lookback, -1):
        w = df.iloc[i - swing_lookback : i + swing_lookback + 1]
        if df.iloc[i]["low"] == w["low"].min():
            swing_low_idx = i
            break

    if swing_high_idx is None or swing_low_idx is None:
        return {
            "swing_high": None,
            "swing_low": None,
            "type": "NONE",
            "strength": 0.0,
            "rejection_up": False,
            "rejection_down": False,
        }

    swing_high = highs[swing_high_idx]
    swing_low = lows[swing_low_idx]

    choch_up = close > swing_high
    choch_down = close < swing_low
    bos_up = close > swing_high * 1.001
    bos_down = close < swing_low * 0.999

    rejection_up = False
    rejection_down = False
    strength = 0.0

    if high >= swing_high - tolerance and close < swing_high:
        rejection_down = True
        strength = (high - close) / (swing_high + 1e-9)
    if low <= swing_low + tolerance and close > swing_low:
        rejection_up = True
        strength = (close - low) / (swing_low + 1e-9)

    if bos_up:
        stype = "BOS_UP"
    elif bos_down:
        stype = "BOS_DOWN"
    elif choch_up:
        stype = "CHoCH_UP"
    elif choch_down:
        stype = "CHoCH_DOWN"
    elif rejection_up:
        stype = "REJECTION_UP"
    elif rejection_down:
        stype = "REJECTION_DOWN"
    else:
        stype = "NONE"

    return {
        "swing_high": float(swing_high),
        "swing_low": float(swing_low),
        "type": stype,
        "strength": float(strength),
        "rejection_up": rejection_up,
        "rejection_down": rejection_down,
    }
