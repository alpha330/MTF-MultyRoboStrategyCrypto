import numpy as np

def sma(data: list[float], period: int) -> list[float]:
    if len(data) < period:
        return []
    return [np.mean(data[i - period:i]) for i in range(period, len(data) + 1)]