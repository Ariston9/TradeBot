import pandas as pd
import yfinance as yf

INTERVAL_MAP = {
    "1min": "1m",
    "5min": "5m",
    "15min": "15m",
}

def _pair_to_symbol(pair: str) -> str:
    """ EUR/CHF -> EURCHF=X """
    return pair.replace("/", "") + "=X"

def fetch_yahoo(pair: str, interval: str, n_bars: int):
    symbol = _pair_to_symbol(pair)

    yf_tf = INTERVAL_MAP.get(interval, "1m")

    try:
        df = yf.download(
            symbol,
            interval=yf_tf,
            period="7d",
            progress=False,
            auto_adjust=False
        )
        if df.empty:
            return None
        
        df = df.reset_index()

        # Standardize datetime
        dt_col = "Datetime" if "Datetime" in df.columns else "Date"
        df["dt_utc"] = pd.to_datetime(df[dt_col], utc=True)

        # unix timestamp
        df["time"] = df["dt_utc"].astype("int64") // 10**9

        # rename prices
        df.rename(columns={
            "Open":  "open",
            "High":  "high",
            "Low":   "low",
            "Close": "close"
        }, inplace=True)

        df = df[["time", "open", "high", "low", "close", "dt_utc"]]
        return df.tail(n_bars)

    except Exception:
        return None


def get_tv_series(pair: str, interval: str = "1min", n_bars: int = 300):
    """
    Главная функция → возвращает свечи.
    """
    df = fetch_yahoo(pair, interval, n_bars)

    if df is None or df.empty:
        return None, {"error": f"No data for {pair} from Yahoo"}

    return df, None
