import pandas as pd


def get_swing_levels(df: pd.DataFrame, lookback: int = 60):
    if len(df) < lookback + 5:
        return None, None

    swings_high = []
    swings_low = []

    for i in range(2, lookback):
        idx = -i
        if idx - 1 < -len(df) or idx + 1 >= 0:
            continue
        if df["high"].iloc[idx] > df["high"].iloc[idx - 1] and df["high"].iloc[idx] > df["high"].iloc[idx + 1]:
            swings_high.append(df["high"].iloc[idx])
        if df["low"].iloc[idx] < df["low"].iloc[idx - 1] and df["low"].iloc[idx] < df["low"].iloc[idx + 1]:
            swings_low.append(df["low"].iloc[idx])

    resistance = max(swings_high) if swings_high else None
    support = min(swings_low) if swings_low else None

    return support, resistance
