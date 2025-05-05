import numpy as np
import pandas as pd

def stochastic_oscillator(close_prices, high_prices, low_prices, lookback_period=14, sma_period=3):
    close_prices = pd.Series(close_prices)
    high_prices = pd.Series(high_prices)
    low_prices = pd.Series(low_prices)

    lowest_low = low_prices.rolling(window=lookback_period).min()
    highest_high = high_prices.rolling(window=lookback_period).max()

    percent_k = 100 * ((close_prices - lowest_low) / (highest_high - lowest_low))
    percent_d = percent_k.rolling(window=sma_period).mean()

    return percent_k.tolist(), percent_d.tolist()
