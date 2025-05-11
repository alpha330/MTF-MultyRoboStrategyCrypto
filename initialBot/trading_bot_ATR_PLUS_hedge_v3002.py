import ccxt
import pandas as pd
import ta
import logging
import threading
import time
import telegram
from telegram.ext import Application, CommandHandler
import asyncio
import datetime
from dotenv import load_dotenv
import os
import requests
import csv
import json
import queue

# Define color codes for logs
class bcolors:
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKCYAN = '\033[96m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('trading_bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Branding
BRAND = "MAXIMUS"
AUTHOR = "Ali Mahmoodi"
logger.info(f"{bcolors.HEADER}{BRAND} Trading Algorithm | Developed by {AUTHOR}")

# Load environment variables
load_dotenv()
API_KEY = os.getenv('BYBIT_TESTNET_API_KEY')
API_SECRET = os.getenv('BYBIT_TESTNET_API_SECRET')
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

# Validate environment variables
if not all([API_KEY, API_SECRET, TELEGRAM_TOKEN, TELEGRAM_CHAT_ID]):
    raise ValueError("Missing required environment variables in .env file")

def get_utc_timestamp():
    utc_now = datetime.datetime.now(datetime.timezone.utc)
    return int(utc_now.timestamp() * 1000)

# Telegram Bot Setup
try:
    telegram_bot = telegram.Bot(token=TELEGRAM_TOKEN)
except Exception as e:
    logger.error(f"{bcolors.FAIL}Error initializing Telegram bot: {e}")
    raise

# Queue for Telegram messages
telegram_queue = queue.Queue()

# Async wrapper for sending Telegram messages with retry
async def send_telegram_message(message, retries=3, delay=1):
    for attempt in range(retries):
        try:
            await telegram_bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=message)
            logger.info(f"{bcolors.OKGREEN}Telegram message sent: {message}")
            return
        except Exception as e:
            logger.error(f"{bcolors.FAIL}Attempt {attempt + 1}/{retries} failed: {e}")
            if attempt < retries - 1:
                await asyncio.sleep(delay)
    logger.error(f"{bcolors.FAIL}Failed to send Telegram message after {retries} attempts")

# Telegram message processor
async def telegram_message_processor():
    loop = asyncio.get_event_loop()
    while True:
        try:
            message = telegram_queue.get_nowait()
            await send_telegram_message(message)
            telegram_queue.task_done()
        except queue.Empty:
            await asyncio.sleep(0.1)
        except Exception as e:
            logger.error(f"{bcolors.FAIL}Error in telegram_message_processor: {e}")

# Synchronous wrapper for Telegram messages
def sync_send_telegram_message(message):
    telegram_queue.put(message)

class TradingBot:
    def __init__(self, symbol, timeframe, leverage=3, risk_percent=0.01):
        self.symbol = symbol
        self.timeframe = timeframe
        self.leverage = leverage
        self.risk_percent = risk_percent
        self.running = False
        self.last_signal = 'Neutral'
        self.min_quantity = 0.0001
        self.candle_count = 0
        self.balance_log = []
        self.exchange = ccxt.bybit({
            'apiKey': API_KEY,
            'secret': API_SECRET,
            'enableRateLimit': True,
        })
        self.exchange.set_sandbox_mode(True)
        self.exchange.nonce = get_utc_timestamp
        self.exchange.set_position_mode(hedged=True)
        self.exchange.load_markets()
        if self.symbol not in self.exchange.markets:
            logger.error(f"{bcolors.FAIL}Symbol {self.symbol} Not Exists")
            raise ValueError(f"Symbol {self.symbol} Not Exists")
        self._set_leverage()

    def _set_leverage(self):
        try:
            response = self.exchange.set_leverage(self.leverage, self.symbol, params={'category': 'linear', 'recv_window': 60000})
            logger.info(f"{bcolors.OKCYAN}LEVERAGE {self.leverage}x FOR {self.symbol} SET: {response}")
        except Exception as e:
            if "leverage not modified" in str(e):
                logger.info(f"{bcolors.OKCYAN}LEVERAGE ALREADY SET TO {self.leverage}x")
            else:
                logger.error(f"{bcolors.FAIL}EXCEPTION DURING SET LEVERAGE: {e}")

    def fetch_ohlcv(self, timeframe):
        for _ in range(3):
            try:
                ohlcv = self.exchange.fetch_ohlcv(self.symbol, timeframe, limit=400)
                df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
                logger.info(f"{bcolors.OKGREEN}OHLCV DATA FOR {self.symbol} IN {timeframe} FETCHED: {len(df)} CANDLES")
                if len(df) < 50:
                    logger.WARNING(f"{bcolors.WARNING}NOT ENOUGH CANDLES ({len(df)}) FOR {self.symbol} IN {timeframe}")
                    return None
                return df
            except Exception as e:
                logger.error(f"{bcolors.FAIL}EXCEPTION FETCHING OHLCV: {e}")
                time.sleep(5)
        logger.error(f"{bcolors.FAIL}FAILED TO FETCH OHLCV AFTER 3 ATTEMPTS")
        return None

    def calculate_indicators(self, df):
        indicators_data = {}
        indicators_data['RSI'] = ta.momentum.RSIIndicator(df['close'], window=14).rsi()
        indicators_data['ATR'] = ta.volatility.AverageTrueRange(df['high'], df['low'], df['close'], window=14).average_true_range()
        return indicators_data

    def calculate_position_size(self, balance, price, stop_loss_percent=0.015):
        risk_amount = balance * self.risk_percent
        stop_loss_distance = price * stop_loss_percent
        if stop_loss_distance == 0:
            logger.error(f"{bcolors.WARNING}STOP LOSS DISTANCE IS ZERO")
            return 0
        quantity = risk_amount / stop_loss_distance
        return max(self.min_quantity, float(self.exchange.amount_to_precision(self.symbol, quantity)))

    def get_open_positions(self):
        try:
            positions = self.exchange.fetch_positions([self.symbol], params={'category': 'linear'})
            result = {'long': None, 'short': None}
            for pos in positions:
                if pos['contracts'] > 0:
                    if pos['side'] == 'long':
                        result['long'] = pos
                    elif pos['side'] == 'short':
                        result['short'] = pos
            logger.info(f"{bcolors.OKCYAN}POSITIONS FETCHED: {result}")
            return result
        except Exception as e:
            logger.error(f"{bcolors.FAIL}EXCEPTION FETCHING POSITIONS: {e}")
            return {'long': None, 'short': None}

    def close_position(self, position):
        try:
            quantity = position['contracts']
            side = 'sell' if position['side'] == 'long' else 'buy'
            order = self.exchange.create_market_order(
                self.symbol, side, quantity,
                params={
                    'category': 'linear',
                    'reduceOnly': True,
                    'positionIdx': 1 if position['side'] == 'long' else 2,
                    'recv_window': 60000
                }
            )
            logger.info(f"{bcolors.OKGREEN}POSITION CLOSED: {position['side']} QTY {quantity}")
            sync_send_telegram_message(
                f"[{BRAND}] Position closed on {self.symbol}\nSide: {position['side'].capitalize()}\nQuantity: {quantity:.4f}"
            )
        except Exception as e:
            logger.error(f"{bcolors.FAIL}EXCEPTION CLOSING POSITION: {e}")

    def set_trailing_stop(self, position, trailing_distance):
        try:
            url = 'https://api-testnet.bybit.com/v5/position/trading-stop'
            headers = {'X-BAPI-API-KEY': API_KEY}
            data = {
                'category': 'linear',
                'symbol': self.symbol.replace('/', ''),
                'trailingStop': str(trailing_distance),
                'positionIdx': 1 if position['side'] == 'long' else 2,
                'recvWindow': 60000,
                'timestamp': get_utc_timestamp(),
            }
            data['sign'] = self.exchange.generate_signature(data, API_SECRET)
            response = requests.post(url, headers=headers, json=data)
            if response.status_code == 200:
                logger.info(f"{bcolors.OKGREEN}TRAILING STOP SET FOR {position['side']} AT {trailing_distance}")
                sync_send_telegram_message(
                    f"[{BRAND}] Trailing stop set for {position['side']} on {self.symbol}\nDistance: {trailing_distance:.2f}"
                )
            else:
                logger.error(f"{bcolors.FAIL}FAILED TO SET TRAILING STOP: {response.text}")
        except Exception as e:
            logger.error(f"{bcolors.FAIL}ERROR SETTING TRAILING STOP: {e}")

    def adjust_margin(self, position, new_qty, price):
        try:
            current_qty = float(position['contracts'])
            if abs(new_qty - current_qty) < 0.0001:
                return
            margin = (new_qty - current_qty) * price / self.leverage
            url = 'https://api-testnet.bybit.com/v5/position/add-margin'
            headers = {'X-BAPI-API-KEY': API_KEY}
            data = {
                'category': 'linear',
                'symbol': self.symbol.replace('/', ''),
                'margin': str(abs(margin)),
                'positionIdx': 1 if position['side'] == 'long' else 2,
                'recvWindow': 60000,
                'timestamp': get_utc_timestamp(),
            }
            data['sign'] = self.exchange.generate_signature(data, API_SECRET)
            response = requests.post(url, headers=headers, json=data)
            if response.status_code == 200:
                logger.info(f"{bcolors.OKGREEN}ADJUSTED MARGIN FOR {position['side']}: NEW QTY {new_qty:.4f}")
            else:
                logger.error(f"{bcolors.FAIL}FAILED TO ADJUST MARGIN: {response.text}")
        except Exception as e:
            logger.error(f"{bcolors.FAIL}ERROR ADJUSTING MARGIN: {e}")

    def log_balance(self, balance, price):
        timestamp = datetime.datetime.now(datetime.timezone.utc)
        self.balance_log.append([timestamp, balance, price])
        with open('balance_log.csv', 'a', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([timestamp, balance, price])
        logger.info(f"{bcolors.OKCYAN}BALANCE LOGGED: {balance:.2f} USDT, PRICE: {price:.2f}")

    def save_dashboard_data(self, balance, price, rsi, atr, positions):
        dashboard_data = {
            'timestamp': datetime.datetime.now(datetime.timezone.utc).isoformat(),
            'balance': balance,
            'price': price,
            'hodl_value': (self.balance_log[0][1] / self.balance_log[0][2]) * price if self.balance_log else 0,
            'rsi': rsi,
            'atr': atr,
            'positions': {
                'long': {
                    'active': bool(positions['long']),
                    'quantity': positions['long']['contracts'] if positions['long'] else 0,
                    'entry_price': positions['long']['entryPrice'] if positions['long'] else 0,
                    'unrealized_pnl': positions['long'].get('unrealizedPnl', 0) if positions['long'] else 0
                },
                'short': {
                    'active': bool(positions['short']),
                    'quantity': positions['short']['contracts'] if positions['short'] else 0,
                    'entry_price': positions['short']['entryPrice'] if positions['short'] else 0,
                    'unrealized_pnl': positions['short'].get('unrealizedPnl', 0) if positions['short'] else 0
                }
            }
        }
        with open('dashboard_data.json', 'w') as f:
            json.dump(dashboard_data, f)
        logger.info(f"{bcolors.OKCYAN}DASHBOARD DATA SAVED")

    def run(self):
        self.running = True
        logger.info(f"{bcolors.OKBLUE}{BRAND} ALGOBOT {self.symbol} IN TIME FRAME {self.timeframe} HAS BEEN STARTED")
        with open('balance_log.csv', 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['timestamp', 'balance', 'price'])
        with open('dashboard_data.json', 'w') as f:
            json.dump({}, f)
        while self.running:
            try:
                df = self.fetch_ohlcv(self.timeframe)
                if df is None or df.empty:
                    logger.warning(f"{bcolors.WARNING}INVALID OHLCV DATA FOR {self.symbol} IN {self.timeframe}")
                    time.sleep(60)
                    continue

                indicators_data = self.calculate_indicators(df)
                price = df['close'].iloc[-1]
                self.candle_count += 1

                rsi = indicators_data.get('RSI')
                atr = indicators_data.get('ATR')
                if any(x is None for x in [rsi, atr]):
                    logger.warning(f"{bcolors.WARNING}RSI/ATR NOT CALCULATED")
                    time.sleep(60)
                    continue
                rsi = rsi.iloc[-1]
                atr = atr.iloc[-1]

                positions = self.get_open_positions()
                long_position = positions['long']
                short_position = positions['short']

                balance = self.exchange.fetch_balance(params={'recv_window': 60000})['USDT']['free']
                self.log_balance(balance, price)
                self.save_dashboard_data(balance, price, rsi, atr, positions)

                if self.candle_count % 5 == 0 and (long_position or short_position):
                    for pos in [long_position, short_position]:
                        if pos:
                            qty = float(pos['contracts'])
                            unrealized_pnl = float(pos.get('unrealizedPnl', 0) or 0)
                            new_qty = qty * (1.01 if unrealized_pnl > 0 else 0.99)
                            new_qty = max(self.min_quantity, round(new_qty, 4))
                            self.adjust_margin(pos, new_qty, price)

                total_pnl = sum(float(pos.get('unrealizedPnl', 0) or 0) for pos in [long_position, short_position] if pos)
                if total_pnl >= balance * 0.05 or total_pnl <= balance * -0.03:
                    for pos in [long_position, short_position]:
                        if pos:
                            self.close_position(pos)
                    logger.info(f"{bcolors.OKGREEN}CLOSED ALL POSITIONS DUE TO TOTAL PNL: {total_pnl:.2f}")
                    sync_send_telegram_message(f"[{BRAND}] Closed all positions on {self.symbol} due to total PNL: {total_pnl:.2f}")
                    time.sleep(60)
                    continue

                for pos in [long_position, short_position]:
                    if pos:
                        entry_price = float(pos['entryPrice'])
                        take_profit = entry_price * (1 + 0.03 if pos['side'] == 'long' else 1 - 0.03)
                        if (pos['side'] == 'long' and price >= take_profit) or (pos['side'] == 'short' and price <= take_profit):
                            trailing_distance = max(0.0075 * price, 0.5 * atr)
                            self.set_trailing_stop(pos, trailing_distance)

                if not (long_position or short_position) and (rsi < 45 or rsi > 55):
                    quantity = self.calculate_position_size(balance, price, stop_loss_percent=0.015)
                    if quantity < self.min_quantity:
                        logger.warning(f"{bcolors.WARNING}INSUFFICIENT MARGIN FOR POSITIONS")
                        time.sleep(60)
                        continue

                    stop_loss_long = price * (1 - max(0.015, atr / price))
                    take_profit_long = price * (1 + max(0.03, 2 * atr / price))
                    stop_loss_short = price * (1 + max(0.015, atr / price))
                    take_profit_short = price * (1 - max(0.03, 2 * atr / price))

                    try:
                        order_long = self.exchange.create_market_buy_order(
                            self.symbol, quantity,
                            params={
                                'category': 'linear',
                                'stopLoss': str(self.exchange.price_to_precision(self.symbol, stop_loss_long)),
                                'takeProfit': str(self.exchange.price_to_precision(self.symbol, take_profit_long)),
                                'positionIdx': 1,
                                'recv_window': 60000
                            }
                        )
                        logger.info(f"{bcolors.OKBLUE}LONG ORDER CREATED: {order_long}")
                        sync_send_telegram_message(
                            f"[{BRAND}] New Long position opened on {self.symbol}\nPrice: {price:.2f}\nQuantity: {quantity:.4f}\nStop Loss: {stop_loss_long:.2f}\nTake Profit: {take_profit_long:.2f}"
                        )
                    except Exception as e:
                        logger.error(f"{bcolors.FAIL}ERROR OPENING LONG POSITION: {e}")

                    time.sleep(0.5)

                    try:
                        order_short = self.exchange.create_market_sell_order(
                            self.symbol, quantity,
                            params={
                                'category': 'linear',
                                'stopLoss': str(self.exchange.price_to_precision(self.symbol, stop_loss_short)),
                                'takeProfit': str(self.exchange.price_to_precision(self.symbol, take_profit_short)),
                                'positionIdx': 2,
                                'recv_window': 60000
                            }
                        )
                        logger.info(f"{bcolors.OKBLUE}SHORT ORDER CREATED: {order_short}")
                        sync_send_telegram_message(
                            f"[{BRAND}] New Short position opened on {self.symbol}\nPrice: {price:.2f}\nQuantity: {quantity:.4f}\nStop Loss: {stop_loss_short:.2f}\nTake Profit: {take_profit_short:.2f}"
                        )
                    except Exception as e:
                        logger.error(f"{bcolors.FAIL}ERROR OPENING SHORT POSITION: {e}")

                time.sleep(60)

            except Exception as e:
                logger.error(f"{bcolors.FAIL}GENERAL EXCEPTION IN {BRAND} ALGOBOT {self.symbol}: {e}")
                time.sleep(60)

    def stop(self):
        self.running = False
        logger.info(f"{bcolors.OKCYAN}{BRAND} ALGOBOT {self.symbol} STOPPED")
        sync_send_telegram_message(f"[{BRAND}] Trading bot for {self.symbol} ({self.timeframe}) stopped")

    def get_status(self):
        df = self.fetch_ohlcv(self.timeframe)
        if df is None:
            return "Error fetching data"
        indicators = self.calculate_indicators(df)
        positions = self.get_open_positions()
        status = f"{BRAND} Bot Status ({self.timeframe}):\n"
        status += f"Symbol: {self.symbol}\n"
        status += f"Running: {self.running}\n"
        status += f"Last Signal: {self.last_signal}\n"
        status += f"RSI: {indicators.get('RSI', pd.Series([0])).iloc[-1]:.2f}\n"
        status += f"ATR: {indicators.get('ATR', pd.Series([0])).iloc[-1]:.2f}\n"
        status += f"Open Long Position: {'Yes' if positions['long'] else 'No'}\n"
        status += f"Open Short Position: {'Yes' if positions['short'] else 'No'}\n"
        return status

class BotManager:
    def __init__(self):
        self.bots = []

    def add_bot(self, symbol, timeframe):
        bot = TradingBot(symbol, timeframe)
        self.bots.append(bot)
        return bot

    def start_all(self):
        for bot in self.bots:
            threading.Thread(target=bot.run, daemon=True).start()

# Telegram command handlers
async def start(update, context):
    global manager
    for bot in manager.bots:
        bot.running = True
    await update.message.reply_text(f"[{BRAND}] Trading bot started")
    logger.info(f"{bcolors.OKGREEN}{BRAND} Bot started via Telegram")

async def stop(update, context):
    global manager
    for bot in manager.bots:
        bot.stop()
    await update.message.reply_text(f"[{BRAND}] Trading bot stopped")
    logger.info(f"{bcolors.WARNING}{BRAND} Bot stopped via Telegram")

async def status(update, context):
    global manager
    status = ""
    for bot in manager.bots:
        status += bot.get_status() + "\n\n"
    await update.message.reply_text(status)
    logger.info(f"{bcolors.OKCYAN}{BRAND} Status requested via Telegram")

async def run_telegram_bot():
    application = Application.builder().token(TELEGRAM_TOKEN).pool_timeout(30).connection_pool_size(20).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("stop", stop))
    application.add_handler(CommandHandler("status", status))
    await application.initialize()
    await application.start()
    await application.updater.start_polling()
    await telegram_message_processor()

def main():
    global manager
    manager = BotManager()
    bot = manager.add_bot(symbol='BTC/USDT:USDT', timeframe='1m')
    manager.start_all()
    sync_send_telegram_message(f"[{BRAND}] Trading bot initialized by {AUTHOR}")
    asyncio.run(run_telegram_bot())

if __name__ == "__main__":
    main()