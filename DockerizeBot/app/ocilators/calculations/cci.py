import pandas as pd

def cci(high_prices, low_prices, close_prices, period=20):
    high = pd.Series(high_prices)
    low = pd.Series(low_prices)
    close = pd.Series(close_prices)

    tp = (high + low + close) / 3
    sma = tp.rolling(window=period).mean()

    def mean_absolute_deviation(x):
        return (abs(x - x.mean())).mean()

    mad = tp.rolling(window=period).apply(mean_absolute_deviation, raw=False)

    cci = (tp - sma) / (0.015 * mad)
    return cci.tolist()
