def moving_average(data, period):
    if len(data) < period or period <= 0:
        raise ValueError("Invalid period or insufficient data")

    result = []
    for i in range(len(data) - period + 1):
        window = data[i:i+period]
        avg = sum(window) / period
        result.append(avg)

    return result
