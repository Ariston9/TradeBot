import pandas as pd

EMA_PERIOD        = 14
RSI_PERIOD        = 8
ATR_K             = 0.5
API_URL = "https://example.com"


def compute_rsi(series: pd.Series, period: int = RSI_PERIOD):
    delta = series.diff()
    up = delta.clip(lower=0)
    down = -delta.clip(upper=0)
    ma_up = up.ewm(com=period - 1, adjust=False).mean()
    ma_down = down.ewm(com=period - 1, adjust=False).mean()
    rs = ma_up / ma_down
    return 100 - (100 / (1 + rs))


def compute_macd(df, fast=12, slow=26, signal=9):
    df["ema_fast"] = df["close"].ewm(span=fast, adjust=False).mean()
    df["ema_slow"] = df["close"].ewm(span=slow, adjust=False).mean()
    df["macd"] = df["ema_fast"] - df["ema_slow"]
    df["macd_signal"] = df["macd"].ewm(span=signal, adjust=False).mean()
    df["macd_hist"] = df["macd"] - df["macd_signal"]
    df["macd_slope"] = df["macd_hist"].diff()
    df["macd_expansion"] = df["macd_hist"] - df["macd_hist"].shift(1)

    df["min_local"] = (df["macd_hist"] < df["macd_hist"].shift(1)) & (df["macd_hist"] < df["macd_hist"].shift(-1))
    df["max_local"] = (df["macd_hist"] > df["macd_hist"].shift(1)) & (df["macd_hist"] > df["macd_hist"].shift(-1))

    div_buy = False
    div_sell = False

    try:
        macd_lows = df.loc[df["min_local"], "macd_hist"].tail(2)
        price_lows = df["low"].tail(4)
        if len(macd_lows) == 2:
            div_buy = macd_lows.iloc[-1] > macd_lows.iloc[-2] and price_lows.iloc[-1] < price_lows.iloc[-2]

        macd_highs = df.loc[df["max_local"], "macd_hist"].tail(2)
        price_highs = df["high"].tail(4)
        if len(macd_highs) == 2:
            div_sell = macd_highs.iloc[-1] < macd_highs.iloc[-2] and price_highs.iloc[-1] > price_highs.iloc[-2]
    except Exception:
        pass

    return {
        "macd": float(df["macd"].iloc[-1]),
        "macd_signal": float(df["macd_signal"].iloc[-1]),
        "macd_hist": float(df["macd_hist"].iloc[-1]),
        "macd_slope": float(df["macd_slope"].iloc[-1]),
        "macd_expansion": float(df["macd_expansion"].iloc[-1]),
        "div_buy": div_buy,
        "div_sell": div_sell,
    }


def compute_indicators(df: pd.DataFrame):
    df = df.copy()
    df["EMA20"] = df["close"].ewm(span=EMA_PERIOD, adjust=False).mean()
    df["EMA12"] = df["close"].ewm(span=12, adjust=False).mean()
    df["EMA26"] = df["close"].ewm(span=26, adjust=False).mean()
    df["MACD"] = df["EMA12"] - df["EMA26"]
    df["MACD_sig"] = df["MACD"].ewm(span=9, adjust=False).mean()
    df["RSI"] = compute_rsi(df["close"], RSI_PERIOD)
    return df
