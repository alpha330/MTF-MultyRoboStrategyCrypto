import ccxt
import datetime
from dotenv import load_dotenv
import os

load_dotenv()
API_KEY = os.getenv('BYBIT_TESTNET_API_KEY')
API_SECRET = os.getenv('BYBIT_TESTNET_API_SECRET')

def get_utc_timestamp():
    utc_now = datetime.datetime.now(datetime.timezone.utc)
    return int(utc_now.timestamp() * 1000)

exchange = ccxt.bybit({
    'apiKey': API_KEY,
    'secret': API_SECRET,
    'enableRateLimit': True,
    'test': True,
    'recv_window': 20000
})
exchange.nonce = get_utc_timestamp

symbol = 'BTC/USDT:USDT'  # Linear Perpetual Futures
timeframe = '5m'

# تست لوریج
try:
    exchange.set_leverage(5, symbol, params={'category': 'linear'})
    print(f"لوریج 5x برای {symbol} تنظیم شد")
except Exception as e:
    print(f"خطا در تنظیم لوریج: {e}")

# تست گرفتن داده‌ها
try:
    ohlcv = exchange.fetch_ohlcv(symbol, timeframe, limit=10)
    print("داده‌های OHLCV:")
    for candle in ohlcv:
        print(candle)
except Exception as e:
    print(f"خطا در گرفتن داده‌ها: {e}")