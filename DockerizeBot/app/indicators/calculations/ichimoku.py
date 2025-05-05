from typing import List, Dict, Optional

def highest_high(data: List[float], period: int) -> float:
    return max(data[-period:])

def lowest_low(data: List[float], period: int) -> float:
    return min(data[-period:])

def calculate_ichimoku(highs: List[float], lows: List[float], closes: List[float]) -> Dict[str, List[Optional[float]]]:
    if len(highs) != len(lows) or len(lows) != len(closes):
        raise ValueError("Highs, lows, and closes must be of same length.")

    length = len(closes)
    tenkan_period = 9
    kijun_period = 26
    senkou_span_b_period = 52
    displacement = 26

    tenkan_sen = []
    kijun_sen = []
    senkou_span_a = [None] * displacement  # forward shifted
    senkou_span_b = [None] * displacement
    chikou_span = [None] * length

    for i in range(length):
        # Tenkan-sen
        if i >= tenkan_period - 1:
            high = max(highs[i - tenkan_period + 1:i + 1])
            low = min(lows[i - tenkan_period + 1:i + 1])
            tenkan_sen.append((high + low) / 2)
        else:
            tenkan_sen.append(None)

        # Kijun-sen
        if i >= kijun_period - 1:
            high = max(highs[i - kijun_period + 1:i + 1])
            low = min(lows[i - kijun_period + 1:i + 1])
            kijun_sen.append((high + low) / 2)
        else:
            kijun_sen.append(None)

        # Chikou Span
        if i >= displacement:
            chikou_span[i - displacement] = closes[i]

    # Senkou Spans (Shifted forward)
    for i in range(length):
        if i >= kijun_period - 1:
            if tenkan_sen[i] is not None and kijun_sen[i] is not None:
                avg = (tenkan_sen[i] + kijun_sen[i]) / 2
                if i + displacement < length:
                    senkou_span_a.append(avg)
        if i >= senkou_span_b_period - 1:
            high = max(highs[i - senkou_span_b_period + 1:i + 1])
            low = min(lows[i - senkou_span_b_period + 1:i + 1])
            avg = (high + low) / 2
            if i + displacement < length:
                senkou_span_b.append(avg)

    # Pad remaining senkous to match full list
    senkou_span_a += [None] * (length - len(senkou_span_a))
    senkou_span_b += [None] * (length - len(senkou_span_b))

    return {
        "tenkan_sen": tenkan_sen,
        "kijun_sen": kijun_sen,
        "senkou_span_a": senkou_span_a,
        "senkou_span_b": senkou_span_b,
        "chikou_span": chikou_span
    }
