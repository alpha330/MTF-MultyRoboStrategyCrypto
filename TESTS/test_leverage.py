import ccxt
from dotenv import load_dotenv
import os
import datetime

load_dotenv("./env/.env")  # مسیر فایل .env نسبت به TESTS
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
})
exchange.set_sandbox_mode(True)
exchange.nonce = get_utc_timestamp

symbol = 'BTC/USDT:USDT'
desired_leverage = 5

# چک کردن لوریج فعلی
try:
    position_info = exchange.fetch_positions([symbol], params={'category': 'linear'})
    current_leverage = None
    for pos in position_info:
        if pos['symbol'] == symbol:
            current_leverage = pos.get('leverage', None)
            break
    print(f"لوریج فعلی برای {symbol}: {current_leverage}")

    # تنظیم لوریج اگه نیاز بود
    if current_leverage != desired_leverage:
        response = exchange.set_leverage(desired_leverage, symbol, params={'category': 'linear', 'recv_window': 60000})
        print(f"لوریج {desired_leverage}x برای {symbol} تنظیم شد: {response}")
    else:
        print(f"لوریج {desired_leverage}x برای {symbol} قبلاً تنظیم شده است.")
except Exception as e:
    print(f"خطا در تنظیم لوریج: {e}")

# تست دسترسی‌های API Key
try:
    balance = exchange.fetch_balance(params={'recv_window': 60000, 'type': 'linear'})
    print(f"بالانس USDT: {balance.get('USDT', {}).get('free', 'ناموجود')}")
    print(f"بالانس کامل: {balance}")
except Exception as e:
    print(f"خطا در گرفتن بالانس: {e}")