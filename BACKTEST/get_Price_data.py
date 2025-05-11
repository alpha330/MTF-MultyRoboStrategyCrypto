import ccxt
import pandas as pd
import datetime
from time import sleep

# صرافی Bybit
exchange = ccxt.bybit({'enableRateLimit': True})

# تایم‌فریم‌ها و مدت زمان
timeframes = {"1m":"1m"}
symbol = 'BTC/USDT:USDT'
days = 720  # ۶ ماه (۱۸۰ روز)

# تاریخ شروع و پایان
end_date = datetime.datetime(2025, 5, 1)  # ۱ مه ۲۰۲۵
start_date = end_date - datetime.timedelta(days=days)  # ۱ نوامبر ۲۰۲۴
since = int(start_date.timestamp() * 1000)
end_timestamp = int(end_date.timestamp() * 1000)

# تابع برای گرفتن داده‌ها و ذخیره تو CSV
def fetch_and_save_historical_data():
    for tf_name, tf_value in timeframes.items():
        all_ohlcv = []
        current_since = since
        total_candles = 0
        max_retries = 3  # تعداد تلاش‌ها در صورت خطا

        # محاسبه تعداد کندل‌های مورد انتظار
        if tf_name == '1m':
            expected_candles = days * 24 * 60 // 1  
        elif tf_name == '5m':
            expected_candles = days * 24 * 60 // 5  
        elif tf_name == '15m':
            expected_candles = days * 24 * 60 // 15 
        elif tf_name == '30m':
            expected_candles = days * 24 * 60 // 30 
        elif tf_name == '1h':
            expected_candles = days * 24 * 60 // 60  
        elif tf_name == '4h':
            expected_candles = days * 24 * 60 // 240 

        while current_since < end_timestamp:
            retries = 0
            while retries < max_retries:
                try:
                    ohlcv = exchange.fetch_ohlcv(symbol, tf_value, since=current_since, limit=1000)
                    if not ohlcv:
                        print(f"No more data for {tf_name} at {datetime.datetime.fromtimestamp(current_since/1000)}")
                        break

                    all_ohlcv.extend(ohlcv)
                    total_candles += len(ohlcv)
                    current_since = ohlcv[-1][0] + 1
                    print(f"Fetched {len(ohlcv)} candles for {tf_name}, Total: {total_candles}, at {datetime.datetime.fromtimestamp(current_since/1000)}")
                    sleep(2)  # برای رعایت rate limit
                    break  # اگر موفق بود، از حلقه retries خارج شو

                except Exception as e:
                    retries += 1
                    print(f"Error fetching data for {tf_name}: {e}, Retry {retries}/{max_retries}")
                    if retries == max_retries:
                        print(f"Max retries reached for {tf_name}, stopping fetch.")
                        break
                    sleep(5)

            if not ohlcv:  # اگر داده‌ای نبود، از حلقه اصلی هم خارج شو
                break

        # ذخیره تو DataFrame و CSV
        if all_ohlcv:
            df = pd.DataFrame(all_ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            df.to_csv(f'BTCUSDT_{tf_name}_historical.csv', index=False)
            print(f"Saved {len(df)} candles for {tf_name} to CSV (Expected: {expected_candles})")
        else:
            print(f"No data fetched for {tf_name}")

# اجرای تابع
fetch_and_save_historical_data()