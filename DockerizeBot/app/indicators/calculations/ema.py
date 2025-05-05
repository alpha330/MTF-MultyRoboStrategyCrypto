from typing import List

def calculate_ema(prices: List[float], period: int) -> List[float]:
    if period <= 0:
        raise ValueError("Period must be a positive integer.")
    if len(prices) < period:
        raise ValueError("Not enough data points to calculate EMA.")
    
    ema = []
    k = 2 / (period + 1)

    # SMA for the first EMA point
    sma = sum(prices[:period]) / period
    ema.append(sma)

    for price in prices[period:]:
        prev_ema = ema[-1]
        current_ema = (price - prev_ema) * k + prev_ema
        ema.append(current_ema)

    # Fill the beginning with None to keep same length as prices
    prefix = [None] * (period - 1)
    return prefix + ema
