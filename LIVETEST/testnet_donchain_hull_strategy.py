import ccxt
import pandas as pd
import numpy as np
import time
import csv
import json
import logging
import requests
from datetime import datetime
from dotenv import load_dotenv
import os

# Load environment variables
load_dotenv()
API_KEY = os.getenv('BYBIT_LIVE_API_KEY')
API_SECRET = os.getenv('BYBIT_LIVE_API_SECRET')
TELEGRAM_TOKEN = os.getenv('TESTNET_LIVE_DONHULL')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHANAL_ID')

# تنظیمات لاگ‌گذاری
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# رنگ‌ها برای لاگ‌ها
class bcolors:
    OKBLUE = '\033[94m'
    OKCYAN = '\033[96m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'

BRAND = "MAXIMUS"

# تابع ارسال پیام به تلگرام
def sync_send_telegram_message(message):
    telegram_token = TELEGRAM_TOKEN
    chat_id = TELEGRAM_CHAT_ID
    url = f"https://api.telegram.org/bot{telegram_token}/sendMessage"
    payload = {"chat_id": chat_id, "text": message}
    for attempt in range(3):
        try:
            response = requests.post(url, json=payload)
            if response.status_code == 200:
                logger.info(f"{bcolors.OKGREEN}Telegram message sent: {message}")
                return
            else:
                logger.error(f"{bcolors.FAIL}Attempt {attempt+1}/3 failed: {response.text}")
        except Exception as e:
            logger.error(f"{bcolors.FAIL}Attempt {attempt+1}/3 failed: {e}")
        time.sleep(1)
    logger.error(f"{bcolors.FAIL}Failed to send Telegram message after 3 attempts")

class MaximusBot:
    def __init__(self, api_key, api_secret, symbol='BTC/USDT:USDT'):
        self.exchange = ccxt.bybit({
            'apiKey': api_key,
            'secret': api_secret,
            'enableRateLimit': True,
        })
        self.exchange.set_sandbox_mode(False)  # حساب لایو
        self.symbol = symbol
        self.running = False
        self.candle_count = 0
        self.buy_signals = 0
        self.sell_signals = 0
        self.current_position = None
        self.min_quantity = 0.0001  # حداقل مقدار سفارش Bybit
        self.leverage = 10
        self.api_symbol = 'BTCUSDT'

    def set_leverage(self):
        try:
            self.exchange.set_leverage(self.leverage, self.symbol, params={'category': 'linear'})
            logger.info(f"{bcolors.OKCYAN}LEVERAGE SET TO {self.leverage}x")
        except Exception as e:
            if "leverage not modified" in str(e).lower() or "already set" in str(e).lower():
                logger.info(f"{bcolors.OKCYAN}LEVERAGE ALREADY SET TO {self.leverage}x")
            else:
                logger.error(f"{bcolors.FAIL}ERROR SETTING LEVERAGE: {e}")
                sync_send_telegram_message(f"[{BRAND}] Error setting leverage for {self.symbol}\nError: {str(e)}")

    def fetch_ohlcv(self, timeframe, limit=400):
        try:
            ohlcv = self.exchange.fetch_ohlcv(self.symbol, timeframe, limit=limit)
            df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            return df
        except Exception as e:
            logger.error(f"{bcolors.FAIL}ERROR FETCHING OHLCV FOR {timeframe}: {e}")
            sync_send_telegram_message(f"[{BRAND}] Error fetching OHLCV for {timeframe}\nError: {str(e)}")
            return None

    def fetch_ohlcv_both(self):
        df_5m = self.fetch_ohlcv('5m')
        df_15m = self.fetch_ohlcv('15m')
        if df_5m is not None and df_15m is not None:
            logger.info(f"{bcolors.OKGREEN}OHLCV DATA FOR {self.symbol} IN 5m FETCHED: {len(df_5m)} CANDLES")
            logger.info(f"{bcolors.OKGREEN}OHLCV DATA FOR {self.symbol} IN 15m FETCHED: {len(df_15m)} CANDLES")
        return df_5m, df_15m

    def calculate_indicators(self, df_5m, df_15m):
        try:
            def hma(series, period):
                wma1 = series.rolling(window=period//2).mean() * 2
                wma2 = series.rolling(window=period).mean()
                raw_hma = wma1 - wma2
                return raw_hma.rolling(window=int(np.sqrt(period))).mean()

            def donchian(df, period):
                return pd.Series(df['high'].rolling(window=period).max(), name='donchian_high'), \
                       pd.Series(df['low'].rolling(window=period).min(), name='donchian_low')

            def atr(df, period):
                high_low = df['high'] - df['low']
                high_close = np.abs(df['high'] - df['close'].shift())
                low_close = np.abs(df['low'] - df['close'].shift())
                tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
                return tr.rolling(window=period).mean()

            indicators = {}
            indicators['hma_long'] = hma(df_15m['close'], 10)
            indicators['hma_short'] = hma(df_5m['close'], 9)
            indicators['donchian_high'], indicators['donchian_low'] = donchian(df_5m, 20)
            indicators['ma50'] = df_15m['close'].rolling(window=9).mean()
            indicators['ma200'] = df_15m['close'].rolling(window=100).mean()
            indicators['atr'] = atr(df_5m, 9)
            indicators['atr_avg'] = indicators['atr'].rolling(window=14).mean()

            for key in indicators:
                indicators[key] = indicators[key].fillna(method='bfill')

            return indicators
        except Exception as e:
            logger.error(f"{bcolors.FAIL}ERROR CALCULATING INDICATORS: {e}")
            sync_send_telegram_message(f"[{BRAND}] Error calculating indicators\nError: {str(e)}")
            return None

    def calculate_position_size(self, balance, price, sl_pct):
        try:
            margin = balance * 0.1  # 10% بالانس (8.1 USDT)
            order_value = margin * self.leverage  # 81 USDT با لوریج 10x
            qty = order_value / price  # مقدار بیت‌کوین
            if qty < self.min_quantity:
                logger.warning(f"{bcolors.WARNING}QUANTITY {qty:.6f} BELOW MINIMUM {self.min_quantity}")
                return 0
            if margin > balance * 0.9:  # اطمینان از کافی بودن بالانس
                logger.warning(f"{bcolors.WARNING}INSUFFICIENT BALANCE FOR ORDER: Required {margin:.2f} USDT, Available {balance:.2f} USDT")
                return 0
            qty = self.exchange.amount_to_precision(self.symbol, qty)
            return float(qty)
        except Exception as e:
            logger.error(f"{bcolors.FAIL}ERROR CALCULATING POSITION SIZE: {e}")
            sync_send_telegram_message(f"[{BRAND}] Error calculating position size\nError: {str(e)}")
            return 0

    def get_open_positions(self):
        try:
            positions = self.exchange.private_get_v5_position_list({
                'category': 'linear',
                'symbol': self.api_symbol,
                'recv_window': 60000
            })['result']['list']
            result = {'long': None, 'short': None}
            for pos in positions:
                if float(pos['size']) > 0:
                    if pos['side'] == 'Buy':
                        result['long'] = pos
                    elif pos['side'] == 'Sell':
                        result['short'] = pos
            logger.info(f"{bcolors.OKCYAN}POSITIONS FETCHED: {result}")
            return result
        except Exception as e:
            logger.error(f"{bcolors.FAIL}ERROR FETCHING POSITIONS: {e}")
            sync_send_telegram_message(f"[{BRAND}] Error fetching positions\nError: {str(e)}")
            return {'long': None, 'short': None}

    def close_position(self, position):
        try:
            side = 'buy' if position['side'] == 'Sell' else 'sell'
            quantity = float(position['size'])
            order = self.exchange.create_market_order(
                self.symbol, side, quantity,
                params={'category': 'linear', 'positionIdx': 1 if side == 'buy' else 2, 'recv_window': 60000}
            )
            self.current_position = None
            logger.info(f"{bcolors.OKBLUE}POSITION CLOSED: {order}")
            sync_send_telegram_message(
                f"[{BRAND}] Position closed on {self.symbol}\nSide: {side}\nQuantity: {quantity:.4f}"
            )
        except Exception as e:
            logger.error(f"{bcolors.FAIL}ERROR CLOSING POSITION: {e}")
            sync_send_telegram_message(f"[{BRAND}] Error closing position on {self.symbol}\nError: {str(e)}")

    def log_balance(self, balance, price):
        try:
            with open('balance_log.csv', 'a', newline='') as f:
                writer = csv.writer(f)
                writer.writerow([datetime.now().isoformat(), balance, price])
            logger.info(f"{bcolors.OKCYAN}BALANCE LOGGED: {balance:.2f} USDT, PRICE: {price:.2f}")
        except Exception as e:
            logger.error(f"{bcolors.FAIL}ERROR LOGGING BALANCE: {e}")

    def save_dashboard_data(self, balance, price, atr, positions):
        try:
            data = {
                'timestamp': datetime.now().isoformat(),
                'balance': balance,
                'price': price,
                'atr': atr,
                'positions': positions
            }
            with open('dashboard_data.json', 'w') as f:
                json.dump(data, f, indent=4)
            logger.info(f"{bcolors.OKCYAN}DASHBOARD DATA SAVED")
        except Exception as e:
            logger.error(f"{bcolors.FAIL}ERROR SAVING DASHBOARD DATA: {e}")

    def run(self):
        self.set_leverage()
        balance = self.exchange.fetch_balance(params={'recv_window': 60000})['USDT']['free']
        logger.info(f"{bcolors.OKCYAN}INITIAL BALANCE: {balance:.2f} USDT")
        if balance < 8.1:
            logger.error(f"{bcolors.FAIL}INSUFFICIENT INITIAL BALANCE: {balance:.2f} USDT, Required: 8.1 USDT")
            sync_send_telegram_message(f"[{BRAND}] Insufficient initial balance: {balance:.2f} USDT, Required: 8.1 USDT")
            return
        self.running = True
        logger.info(f"{bcolors.OKBLUE}{BRAND} ALGOBOT {self.symbol} IN TIME FRAME 5m/15m HAS BEEN STARTED")
        sync_send_telegram_message(f"[{BRAND}] Trading bot initialized by Ali Mahmoodi\nSymbol: {self.symbol}")

        min_balance = 1
        long_hma_threshold = 1.002
        short_hma_threshold = 1.002
        sl_pct = 0.01
        tp_pct = 0.01

        while self.running:
            try:
                df_5m, df_15m = self.fetch_ohlcv_both()
                if df_5m is None or df_15m is None:
                    logger.warning(f"{bcolors.WARNING}INVALID OHLCV DATA")
                    time.sleep(30)
                    continue

                indicators_data = self.calculate_indicators(df_5m, df_15m)
                if indicators_data is None:
                    logger.warning(f"{bcolors.WARNING}INVALID INDICATORS DATA")
                    time.sleep(30)
                    continue

                for key in ['hma_long', 'hma_short', 'donchian_high', 'donchian_low', 'ma50', 'ma200', 'atr', 'atr_avg']:
                    if indicators_data[key].isna().any():
                        logger.warning(f"{bcolors.WARNING}NaN DETECTED IN {key}, SKIPPING CYCLE")
                        time.sleep(30)
                        continue

                balance = self.exchange.fetch_balance(params={'recv_window': 60000})['USDT']['free']
                ticker = self.exchange.fetch_ticker(self.symbol)
                market_price = ticker['last']
                self.candle_count += 1

                self.log_balance(balance, market_price)
                self.save_dashboard_data(balance, market_price, indicators_data['atr'].iloc[-1], self.get_open_positions())

                if balance < min_balance:
                    logger.warning(f"{bcolors.WARNING}BALANCE {balance:.2f} BELOW MINIMUM {min_balance}")
                    time.sleep(30)
                    continue

                positions = self.get_open_positions()
                position = positions['long'] or positions['short']

                trend = 'range'
                if (indicators_data['ma50'].iloc[-1] > indicators_data['ma200'].iloc[-1] and 
                    indicators_data['atr'].iloc[-1] > indicators_data['atr_avg'].iloc[-1] * 1.2):
                    trend = 'bullish'
                elif (indicators_data['ma50'].iloc[-1] < indicators_data['ma200'].iloc[-1] and 
                      indicators_data['atr'].iloc[-1] > indicators_data['atr_avg'].iloc[-1] * 1.2):
                    trend = 'bearish'
                elif indicators_data['atr'].iloc[-1] < indicators_data['atr_avg'].iloc[-1] * 0.8:
                    trend = 'range'

                logger.info(f"{bcolors.OKCYAN}TREND: {trend}, PRICE: {market_price:.2f}, HMA_LONG: {indicators_data['hma_long'].iloc[-1]:.2f}, HMA_SHORT: {indicators_data['hma_short'].iloc[-1]:.2f}")

                if (trend in ['bullish', 'range'] and not position and
                    indicators_data['hma_long'].iloc[-1] < indicators_data['hma_long'].iloc[-2] * long_hma_threshold and
                    market_price < indicators_data['donchian_high'].iloc[-1] and balance >= min_balance):
                    self.buy_signals += 1
                    quantity = self.calculate_position_size(balance, market_price, sl_pct)
                    if quantity < self.min_quantity or quantity == 0:
                        logger.warning(f"{bcolors.WARNING}INSUFFICIENT MARGIN OR INVALID QUANTITY FOR LONG POSITION: Quantity {quantity:.6f}")
                        time.sleep(30)
                        continue
                    order_value = quantity * market_price
                    margin_required = order_value / self.leverage
                    if margin_required > balance * 0.1:
                        logger.warning(f"{bcolors.WARNING}INSUFFICIENT BALANCE FOR LONG POSITION: Required {margin_required:.2f} USDT, Available {balance:.2f} USDT")
                        time.sleep(30)
                        continue
                    sl = market_price * (1 - sl_pct)
                    tp = market_price * (1 + tp_pct)
                    sl = float(self.exchange.price_to_precision(self.symbol, sl))
                    tp = float(self.exchange.price_to_precision(self.symbol, tp))
                    if sl >= market_price or tp <= market_price:
                        logger.warning(f"{bcolors.WARNING}INVALID SL {sl:.2f} OR TP {tp:.2f} FOR LONG")
                        time.sleep(30)
                        continue
                    logger.info(f"{bcolors.OKCYAN}LONG ORDER: QTY {quantity:.6f}, SL {sl:.2f}, TP {tp:.2f}, MARGIN: {margin_required:.2f} USDT")
                    try:
                        order = self.exchange.create_market_buy_order(
                            self.symbol, quantity,
                            params={
                                'category': 'linear',
                                'stopLoss': str(sl),
                                'takeProfit': str(tp),
                                'positionIdx': 1,
                                'recv_window': 60000
                            }
                        )
                        self.current_position = {
                            'side': 'long',
                            'quantity': quantity,
                            'stop_loss': sl,
                            'take_profit': tp,
                            'entry_price': market_price
                        }
                        logger.info(f"{bcolors.OKBLUE}LONG ORDER CREATED: {order}")
                        sync_send_telegram_message(
                            f"[{BRAND}] New Long position opened on {self.symbol}\nPrice: {market_price:.2f}\nQuantity: {quantity:.6f}\nStop Loss: {sl:.2f}\nTake Profit: {tp:.2f}\nMargin: {margin_required:.2f} USDT\nTrend: {trend}"
                        )
                    except Exception as e:
                        if "retCode: 110007" in str(e):
                            logger.error(f"{bcolors.FAIL}INSUFFICIENT BALANCE FOR LONG POSITION: Required {margin_required:.2f} USDT, Available {balance:.2f} USDT")
                            sync_send_telegram_message(
                                f"[{BRAND}] Insufficient balance for long position on {self.symbol}\nBalance: {balance:.2f} USDT, Required: {margin_required:.2f} USDT"
                            )
                        else:
                            logger.error(f"{bcolors.FAIL}ERROR OPENING LONG POSITION: {e}")
                            sync_send_telegram_message(f"[{BRAND}] Error opening long position on {self.symbol}\nError: {str(e)}")

                if (trend in ['bearish', 'range'] and not position and
                    indicators_data['hma_short'].iloc[-1] > indicators_data['hma_short'].iloc[-2] * short_hma_threshold and
                    market_price > indicators_data['donchian_low'].iloc[-1] and balance >= min_balance):
                    self.sell_signals += 1
                    quantity = self.calculate_position_size(balance, market_price, sl_pct)
                    if quantity < self.min_quantity or quantity == 0:
                        logger.warning(f"{bcolors.WARNING}INSUFFICIENT MARGIN OR INVALID QUANTITY FOR SHORT POSITION: Quantity {quantity:.6f}")
                        time.sleep(30)
                        continue
                    order_value = quantity * market_price
                    margin_required = order_value / self.leverage
                    if margin_required > balance * 0.1:
                        logger.warning(f"{bcolors.WARNING}INSUFFICIENT BALANCE FOR SHORT POSITION: Required {margin_required:.2f} USDT, Available {balance:.2f} USDT")
                        time.sleep(30)
                        continue
                    sl = market_price * (1 + sl_pct)
                    tp = market_price * (1 - tp_pct)
                    sl = float(self.exchange.price_to_precision(self.symbol, sl))
                    tp = float(self.exchange.price_to_precision(self.symbol, tp))
                    if sl <= market_price or tp >= market_price:
                        logger.warning(f"{bcolors.WARNING}INVALID SL {sl:.2f} OR TP {tp:.2f} FOR SHORT")
                        time.sleep(30)
                        continue
                    logger.info(f"{bcolors.OKCYAN}SHORT ORDER: QTY {quantity:.6f}, SL {sl:.2f}, TP {tp:.2f}, MARGIN: {margin_required:.2f} USDT")
                    try:
                        order = self.exchange.create_market_sell_order(
                            self.symbol, quantity,
                            params={
                                'category': 'linear',
                                'stopLoss': str(sl),
                                'takeProfit': str(tp),
                                'positionIdx': 2,
                                'recv_window': 60000
                            }
                        )
                        self.current_position = {
                            'side': 'short',
                            'quantity': quantity,
                            'stop_loss': sl,
                            'take_profit': tp,
                            'entry_price': market_price
                        }
                        logger.info(f"{bcolors.OKBLUE}SHORT ORDER CREATED: {order}")
                        sync_send_telegram_message(
                            f"[{BRAND}] New Short position opened on {self.symbol}\nPrice: {market_price:.2f}\nQuantity: {quantity:.6f}\nStop Loss: {sl:.2f}\nTake Profit: {tp:.2f}\nMargin: {margin_required:.2f} USDT\nTrend: {trend}"
                        )
                    except Exception as e:
                        if "retCode: 110007" in str(e):
                            logger.error(f"{bcolors.FAIL}INSUFFICIENT BALANCE FOR SHORT POSITION: Required {margin_required:.2f} USDT, Available {balance:.2f} USDT")
                            sync_send_telegram_message(
                                f"[{BRAND}] Insufficient balance for short position on {self.symbol}\nBalance: {balance:.2f} USDT, Required: {margin_required:.2f} USDT"
                            )
                        else:
                            logger.error(f"{bcolors.FAIL}ERROR OPENING SHORT POSITION: {e}")
                            sync_send_telegram_message(f"[{BRAND}] Error opening short position on {self.symbol}\nError: {str(e)}")

                if position and self.current_position:
                    current_price = market_price
                    if position['side'] == 'long':
                        if current_price <= self.current_position['stop_loss']:
                            self.close_position(position)
                        elif current_price >= self.current_position['take_profit']:
                            self.close_position(position)
                    elif position['side'] == 'short':
                        if current_price >= self.current_position['stop_loss']:
                            self.close_position(position)
                        elif current_price <= self.current_position['take_profit']:
                            self.close_position(position)
                elif position and not self.current_position:
                    logger.warning(f"{bcolors.WARNING}POSITION EXISTS BUT current_position IS NONE, CLOSING POSITION")
                    self.close_position(position)

                time.sleep(30)

            except Exception as e:
                logger.error(f"{bcolors.FAIL}GENERAL EXCEPTION IN {BRAND} ALGOBOT {self.symbol}: {e}")
                sync_send_telegram_message(f"[{BRAND}] General error in {self.symbol}\nError: {str(e)}")
                time.sleep(30)

if __name__ == "__main__":
    api_key = API_KEY
    api_secret = API_SECRET
    bot = MaximusBot(api_key, api_secret)
    bot.run()