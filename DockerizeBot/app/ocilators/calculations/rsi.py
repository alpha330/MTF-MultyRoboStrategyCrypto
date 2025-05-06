import pandas as pd

def calculate_rsi_series(prices, period=14):
    prices = pd.Series(prices)
    delta = prices.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.rolling(window=period).mean()
    avg_loss = loss.rolling(window=period).mean()

    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))

    return rsi


def calculate_rsi(prices, period=14):
    if len(prices) < period + 1:
        raise ValueError("Not enough data to calculate RSI")

    gains = []
    losses = []

    for i in range(1, period + 1):
        delta = prices[i] - prices[i - 1]
        if delta >= 0:
            gains.append(delta)
            losses.append(0)
        else:
            gains.append(0)
            losses.append(-delta)

    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period

    if avg_loss == 0:
        return 100.0  # RSI بالاترین مقدار ممکنه

    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi
