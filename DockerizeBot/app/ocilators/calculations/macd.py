def calculate_ema(prices, period):
    k = 2 / (period + 1)
    ema = [sum(prices[:period]) / period]  # EMA ابتدایی = SMA
    for price in prices[period:]:
        ema.append(price * k + ema[-1] * (1 - k))
    return ema

def calculate_macd(prices, slow_period=26, fast_period=12, signal_period=9):
    if len(prices) < slow_period + signal_period:
        raise ValueError("Not enough data to calculate MACD")

    fast_ema = calculate_ema(prices, fast_period)
    slow_ema = calculate_ema(prices, slow_period)

    # EMAها با طول‌های مختلف ساخته شدن، هم‌ترازشون می‌کنیم
    min_len = min(len(fast_ema), len(slow_ema))
    macd_line = [fast - slow for fast, slow in zip(fast_ema[-min_len:], slow_ema[-min_len:])]

    signal_line = calculate_ema(macd_line, signal_period)
    histogram = [macd - signal for macd, signal in zip(macd_line[-len(signal_line):], signal_line)]

    return {
        'macd_line': macd_line[-len(signal_line):],
        'signal_line': signal_line,
        'histogram': histogram
    }
