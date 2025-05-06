
import pandas as pd

def calculate_macd(prices, fast=12, slow=26, signal=9, series=False):
    if len(prices) < slow + signal:
        raise ValueError("Not enough data to calculate MACD")

    df = pd.Series(prices)
    ema_fast = df.ewm(span=fast, adjust=False).mean()
    ema_slow = df.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram = macd_line - signal_line

    if series:
        return {
            "macd": macd_line.tolist(),
            "signal": signal_line.tolist(),
            "histogram": histogram.tolist(),
        }
    else:
        return {
            "macd": macd_line.iloc[-1],
            "signal": signal_line.iloc[-1],
            "histogram": histogram.iloc[-1],
        }