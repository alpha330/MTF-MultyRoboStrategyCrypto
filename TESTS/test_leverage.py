import ccxt
from dotenv import load_dotenv
import os
import datetime

load_dotenv("./env/.env")
API_KEY = os.getenv('BYBIT_TESTNET_API_KEY')
API_SECRET = os.getenv('BYBIT_TESTNET_API_SECRET')
print(f"API_KEY: {API_KEY}  --- API_SECRET: {API_SECRET}")

def get_utc_timestamp():
    utc_now = datetime.datetime.now(datetime.timezone.utc)
    return int(utc_now.timestamp() * 1000)

exchange = ccxt.bybit({
    'apiKey': API_KEY,
    'secret': API_SECRET,
    'enableRateLimit': True,
    'test': True,
    'recv_window': 60000  # افزایش به ۶۰ ثانیه
})
exchange.nonce = get_utc_timestamp

symbol = 'BTC/USDT:USDT'

# تست تنظیم لوریج
try:
    response = exchange.set_leverage(5, symbol, params={'category': 'linear'})
    print(f"لوریج 5x برای {symbol} تنظیم شد: {response}")
except Exception as e:
    print(f"خطا در تنظیم لوریج: {e}")

# تست دسترسی‌های API Key
try:
    balance = exchange.fetch_balance()
    print(f"بالانس: {balance['USDT']['free']}")
except Exception as e:
    print(f"خطا در گرفتن بالانس: {e}")