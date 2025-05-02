import ccxt
import pandas as pd
import datetime
from time import sleep

# صرافی Bybit برای گرفتن داده‌ها
exchange = ccxt.bybit({'enableRateLimit': True})

# تایم‌فریم‌ها و مدت زمان
timeframes = {'5m': '5m', '15m': '15m', '1h': '1h'}
symbol = 'BTC/USDT:USDT'
days = 180  # 6 ماه (180 روز)

# تاریخ شروع (۶ ماه قبل از امروز)
end_date = datetime.datetime(2025, 5, 1)  # ۱ مه ۲۰۲۵
start_date = end_date - datetime.timedelta(days=days)  # ۱ نوامبر ۲۰۲۴
since = int(start_date.timestamp() * 1000)

# تابع برای گرفتن داده‌ها و ذخیره تو CSV
def fetch_and_save_historical_data():
    for tf_name, tf_value in timeframes.items():
        all_ohlcv = []
        current_since = since
        while current_since < int(end_date.timestamp() * 1000):
            try:
                ohlcv = exchange.fetch_ohlcv(symbol, tf_value, since=current_since, limit=1000)
                if not ohlcv:
                    break
                all_ohlcv.extend(ohlcv)
                current_since = ohlcv[-1][0] + 1
                print(f"Fetched {len(ohlcv)} candles for {tf_name} at {datetime.datetime.fromtimestamp(current_since/1000)}")
                sleep(2)  # برای رعایت rate limit
            except Exception as e:
                print(f"Error fetching data for {tf_name}: {e}")
                sleep(5)

        # ذخیره تو DataFrame و CSV
        df = pd.DataFrame(all_ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df.to_csv(f'BTCUSDT_{tf_name}_historical.csv', index=False)
        print(f"Saved {len(df)} candles for {tf_name} to CSV")

# اجرای تابع
fetch_and_save_historical_data()