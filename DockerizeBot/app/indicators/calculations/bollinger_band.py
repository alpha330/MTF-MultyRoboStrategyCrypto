from typing import List, Tuple
import statistics

def calculate_bollinger_bands(prices: List[float], period: int, k: float = 2.0) -> Tuple[List[float], List[float], List[float]]:
    if period <= 0:
        raise ValueError("Period must be a positive integer.")
    if len(prices) < period:
        raise ValueError("Not enough data points to calculate Bollinger Bands.")

    sma = []
    upper_band = []
    lower_band = []

    for i in range(len(prices)):
        if i + 1 < period:
            sma.append(None)
            upper_band.append(None)
            lower_band.append(None)
            continue

        window = prices[i + 1 - period:i + 1]
        mean = sum(window) / period
        std_dev = statistics.stdev(window)

        sma.append(mean)
        upper_band.append(mean + k * std_dev)
        lower_band.append(mean - k * std_dev)

    return sma, upper_band, lower_band