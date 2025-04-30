import ccxt
from dotenv import load_dotenv
import os
import datetime

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

try:
    markets = exchange.load_markets()
    print("بازارهای موجود:")
    for symbol in markets:
        if 'BTC' in symbol and 'USDT' in symbol:
            print(symbol, markets[symbol]['type'])
except Exception as e:
    print(f"خطا در لود بازارها: {e}")