import ccxt
import pandas as pd
import ta
import logging
import threading
from time import sleep
from dotenv import load_dotenv
import os
import datetime
import telegram
from telegram.ext import Application, CommandHandler
import asyncio

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
        logging.FileHandler('/root/MTF-MultyRoboStrategyCrypto/LIVE/PersianCheetah_LIVE_BTC_1m.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()
API_KEY = os.getenv('BYBIT_LIVE_API_KEY')
API_SECRET = os.getenv('BYBIT_LIVE_API_SECRET')
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN_LIVE_PERSIAN_CHEETAH')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHANAL_ID_PCHEETAH')

# Validate environment variables
if not all([API_KEY, API_SECRET, TELEGRAM_TOKEN, TELEGRAM_CHAT_ID]):
    raise ValueError("Missing required environment variables in .env file")

# Initialize Telegram bot
try:
    telegram_bot = telegram.Bot(token=TELEGRAM_TOKEN)
except Exception as e:
    logger.error(f"{bcolors.FAIL}Error initializing Telegram bot: {e}")
    raise

def get_utc_timestamp():
    utc_now = datetime.datetime.now(datetime.timezone.utc)
    return int(utc_now.timestamp() * 1000)

class TradingBot:
    def __init__(self, symbol, timeframe, indicators, leverage=5, risk_percent=0.05, loop=None):
        self.symbol = symbol
        self.timeframe = timeframe
        self.indicators = indicators
        self.leverage = leverage
        self.risk_percent = risk_percent
        self.running = False
        self.last_signal = 'Neutral'
        self.loop = loop  # Asyncio event loop from BotManager
        self.exchange = ccxt.bybit({
            'apiKey': API_KEY,
            'secret': API_SECRET,
            'enableRateLimit': True,
        })
        self.exchange.nonce = get_utc_timestamp
        self.exchange.set_position_mode(hedged=True)
        self.exchange.load_markets()
        if self.symbol not in self.exchange.markets:
            logger.error(f"{bcolors.FAIL}Symbol {self.symbol} Not Exists")
            raise ValueError(f"{bcolors.FAIL}Symbol {self.symbol} Not Exists")
        self._set_leverage()
        self.telegram_bot = telegram_bot

    async def async_send_telegram_message(self, chat_id, text):
        try:
            await self.telegram_bot.send_message(chat_id=chat_id, text=text)
            logger.info(f"{bcolors.OKGREEN}Telegram message sent: {text}")
        except Exception as e:
            logger.error(f"{bcolors.FAIL}Error sending Telegram message: {e}")

    def _set_leverage(self):
        try:
            positions = self.exchange.fetch_positions([self.symbol], params={'category': 'linear'})
            for pos in positions:
                current_leverage = float(pos['info']['leverage'])
                position_idx = int(pos['info']['positionIdx'])
                if current_leverage != self.leverage:
                    response = self.exchange.set_leverage(
                        self.leverage,
                        self.symbol,
                        params={
                            'category': 'linear',
                            'positionIdx': position_idx,
                            'recv_window': 60000
                        }
                    )
                    logger.info(f"{bcolors.OKCYAN}LEVERAGE {self.leverage}x SET FOR {self.symbol} POSITIONIDX {position_idx}: {response}")
                else:
                    logger.info(f"{bcolors.OKCYAN}LEVERAGE {self.leverage}x ALREADY SET FOR {self.symbol} POSITIONIDX {position_idx}")
        except Exception as e:
            logger.error(f"{bcolors.FAIL}EXCEPTION DURING SET LEVERAGE: {e}")
            if self.loop:
                asyncio.run_coroutine_threadsafe(
                    self.async_send_telegram_message(TELEGRAM_CHAT_ID, f"Error setting leverage for {self.symbol}: {e}"),
                    self.loop
                )

    def fetch_ohlcv(self, timeframe):
        for _ in range(3):
            try:
                ohlcv = self.exchange.fetch_ohlcv(self.symbol, timeframe, limit=400)
                df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
                logger.info(f"{bcolors.OKGREEN}FOR OHLCV DATA {self.symbol} IN {timeframe} CANDLES ARE GET: {len(df)}")
                if len(df) < 50:
                    logger.warning(f"{bcolors.WARNING}CANDLES ({len(df)}) FOR {self.symbol} IN {timeframe} NOT ENOUGH")
                    return None
                return df
            except Exception as e:
                logger.error(f"{bcolors.FAIL}EXCEPTION DURING GETTING DATA CANDLE {self.symbol} IN {timeframe}: {str(e)}")
                sleep(5)
        logger.error(f"{bcolors.FAIL}CANNOT GET DATA CANDLES {self.symbol} AFTER 3 TIMES TRY")
        return None

    def calculate_indicators(self, df):
        indicators_data = {}
        for indicator in self.indicators:
            if indicator == 'RSI':
                indicators_data['RSI'] = ta.momentum.RSIIndicator(df['close'], window=14).rsi()
            elif indicator == 'Bollinger':
                bb = ta.volatility.BollingerBands(df['close'], window=20, window_dev=1.2)
                indicators_data['BB_upper'] = bb.bollinger_hband()
                indicators_data['BB_middle'] = bb.bollinger_mavg()
                indicators_data['BB_lower'] = bb.bollinger_lband()
            elif indicator == 'Volume':
                indicators_data['Volume'] = df['volume']
                indicators_data['Volume_MA'] = ta.trend.SMAIndicator(df['volume'], window=20).sma_indicator()
            elif indicator == 'ATR':
                indicators_data['ATR'] = ta.volatility.AverageTrueRange(df['high'], df['low'], df['close'], window=14).average_true_range()
        return indicators_data

    def calculate_position_size(self, balance, price, stop_loss_percent=0.005):
        risk_amount = balance * self.risk_percent
        stop_loss_distance = price * stop_loss_percent
        if stop_loss_distance == 0:
            logger.error(f"{bcolors.WARNING}Stop Loss distance is zero, cannot calculate position size")
            return 0
        quantity = risk_amount / stop_loss_distance
        min_quantity = 0.001  # Bybit minimum order size for BTC/USDT
        if quantity < min_quantity:
            logger.warning(f"{bcolors.WARNING}Calculated quantity {quantity} is below minimum {min_quantity}, adjusting to minimum")
            quantity = min_quantity
        # Check if margin requirement is met
        margin_required = (quantity * price) / self.leverage
        if margin_required > balance:
            logger.warning(f"{bcolors.WARNING}Margin required {margin_required:.2f} exceeds balance {balance:.2f}, adjusting quantity")
            quantity = (balance * self.leverage) / price
            quantity = max(min_quantity, quantity)
        logger.info(f"{bcolors.OKCYAN}Calculated position size: {quantity:.6f} BTC, Margin required: {margin_required:.2f} USDT")
        return quantity

    def get_open_position(self, side=None):
        try:
            positions = self.exchange.fetch_positions([self.symbol], params={'category': 'linear'})
            logger.info(f"{bcolors.OKCYAN}Fetched Positions: {positions}")
            for pos in positions:
                if pos['symbol'] == self.symbol and pos['contracts'] > 0:
                    if side is None or (side == 'buy' and pos['side'] == 'buy') or (side == 'sell' and pos['side'] == 'sell'):
                        pos['trailing_stop'] = pos.get('trailing_stop', pos['stopLoss'])
                        pos['first_target_hit'] = pos.get('first_target_hit', False)
                        pos['entryTime'] = pos.get('timestamp', get_utc_timestamp())
                        return pos
            return None
        except Exception as e:
            logger.error(f"{bcolors.FAIL}EXCEPTION DURING GETTING DATA POSITIONS: {e}")
            if self.loop:
                asyncio.run_coroutine_threadsafe(
                    self.async_send_telegram_message(TELEGRAM_CHAT_ID, f"Error fetching positions on {self.symbol}: {e}"),
                    self.loop
                )
            return None

    def close_position(self, position, exit_price=None, reason='Manual'):
        try:
            quantity = position['contracts']
            side = 'sell' if position['side'] == 'buy' else 'buy'
            exit_price = exit_price or self.exchange.fetch_ticker(self.symbol)['last']
            order = self.exchange.create_market_order(
                self.symbol,
                side,
                quantity,
                params={
                    'category': 'linear',
                    'reduceOnly': True,
                    'positionIdx': 1 if position['side'] == 'buy' else 2
                }
            )
            logger.info(f"{bcolors.OKGREEN}POSITION CLOSED: {order}")
            if self.loop:
                asyncio.run_coroutine_threadsafe(
                    self.async_send_telegram_message(
                        TELEGRAM_CHAT_ID,
                        f"Position closed on {self.symbol}\nSide: {position['side']}\nQty: {quantity:.4f}\nReason: {reason}\nPrice: {exit_price:.2f}"
                    ),
                    self.loop
                )
        except Exception as e:
            logger.error(f"{bcolors.FAIL}EXCEPTION DURING CLOSE POSITION: {e}")
            if self.loop:
                asyncio.run_coroutine_threadsafe(
                    self.async_send_telegram_message(
                        TELEGRAM_CHAT_ID,
                        f"Error closing position on {self.symbol}: {e}"
                    ),
                    self.loop
                )

    def update_trailing_stop(self, position, current_price, bb_middle):
        trailing_stop_percent = 0.005
        trailing_profit_percent = 0.005
        if position['side'] == 'buy':
            if current_price >= position['takeProfit']:
                position['takeProfit'] = current_price * (1 + trailing_profit_percent)
                position['stopLoss'] = max(position['stopLoss'], current_price * (1 - trailing_stop_percent))
                position['first_target_hit'] = True
            if position.get('first_target_hit', False):
                position['trailing_stop'] = max(position['trailing_stop'], current_price * (1 - trailing_stop_percent))
                if current_price <= position['trailing_stop']:
                    self.close_position(position, position['trailing_stop'], reason='Trailing Stop Hit')
        else:
            if current_price <= position['takeProfit']:
                position['takeProfit'] = current_price * (1 - trailing_profit_percent)
                position['stopLoss'] = min(position['stopLoss'], current_price * (1 + trailing_stop_percent))
                position['first_target_hit'] = True
            if position.get('first_target_hit', False):
                position['trailing_stop'] = min(position['trailing_stop'], current_price * (1 + trailing_stop_percent))
                if current_price >= position['trailing_stop']:
                    self.close_position(position, position['trailing_stop'], reason='Trailing Stop Hit')

    def run(self):
        self.running = True
        logger.info(f"{bcolors.OKBLUE}ALGOBOT {self.symbol} IN TIME FRAME {self.timeframe} HAS BEEN STARTED")
        if self.loop:
            asyncio.run_coroutine_threadsafe(
                self.async_send_telegram_message(
                    TELEGRAM_CHAT_ID,
                    f"ALGOBOT started for {self.symbol} ({self.timeframe})"
                ),
                self.loop
            )
        while self.running:
            try:
                df = self.fetch_ohlcv(self.timeframe)
                if df is None or df.empty:
                    logger.warning(f"{bcolors.WARNING}DATA OHLCV FOR {self.symbol} IN {self.timeframe} NOT VALID")
                    sleep(60)
                    continue

                indicators_data = self.calculate_indicators(df)
                price = df['close'].iloc[-1]

                rsi = indicators_data.get('RSI')
                bb_upper = indicators_data.get('BB_upper')
                bb_middle = indicators_data.get('BB_middle')
                bb_lower = indicators_data.get('BB_lower')
                volume = indicators_data.get('Volume')
                volume_ma = indicators_data.get('Volume_MA')
                atr = indicators_data.get('ATR')

                if any(x is None for x in [rsi, bb_upper, bb_middle, bb_lower, volume, volume_ma, atr]):
                    logger.warning(f"{bcolors.WARNING}Indicators for {self.symbol} Not Calculated")
                    sleep(60)
                    continue

                rsi = rsi.iloc[-1]
                bb_upper = bb_upper.iloc[-1]
                bb_middle = bb_middle.iloc[-1]
                bb_lower = bb_lower.iloc[-1]
                volume = volume.iloc[-1]
                volume_ma = volume_ma.iloc[-1]
                atr = atr.iloc[-1]

                atr_threshold = price * 0.0003
                rsi_long = 45
                rsi_short = 55
                logger.info(f"{bcolors.OKCYAN}{self.symbol} - RSI: {rsi:.2f}, BB Upper: {bb_upper:.4f}, BB Middle: {bb_middle:.4f}, BB Lower: {bb_lower:.4f}, Volume: {volume:.2f}, ATR: {atr:.4f}")

                long_position = self.get_open_position(side='buy')
                short_position = self.get_open_position(side='sell')

                # Position timeout (30 minutes)
                def check_position_timeout(position):
                    if position:
                        pos_time = datetime.datetime.fromtimestamp(position['entryTime'] / 1000.0)
                        if (datetime.datetime.now() - pos_time).total_seconds() > 1800:
                            self.close_position(position, price, reason='Position timeout')

                if long_position:
                    check_position_timeout(long_position)
                    if rsi > rsi_short:
                        self.close_position(long_position, price, reason=f'RSI above {rsi_short}')
                    else:
                        self.update_trailing_stop(long_position, price, bb_middle)

                if short_position:
                    check_position_timeout(short_position)
                    if rsi < rsi_long:
                        self.close_position(short_position, price, reason=f'RSI below {rsi_long}')
                    else:
                        self.update_trailing_stop(short_position, price, bb_middle)

                long_conditions = {
                    f'RSI < {rsi_long}': rsi < rsi_long,
                    'Price <= BB Lower': price <= bb_lower,
                    'Volume > 0.8 * Volume MA': volume > 0.8 * volume_ma,
                    'ATR > Threshold': atr > atr_threshold
                }
                short_conditions = {
                    f'RSI > {rsi_short}': rsi > rsi_short,
                    'Price >= BB Upper': price >= bb_upper,
                    'Volume > 0.8 * Volume MA': volume > 0.8 * volume_ma,
                    'ATR > Threshold': atr > atr_threshold
                }

                logger.info(f"{bcolors.OKCYAN}Long Conditions: {long_conditions}")
                logger.info(f"{bcolors.OKCYAN}Short Conditions: {short_conditions}")

                signal = None
                if all(long_conditions.values()):
                    signal = 'Long'
                elif all(short_conditions.values()):
                    signal = 'Short'

                if signal:
                    balance = self.exchange.fetch_balance(params={'recv_window': 60000})['USDT']['free']
                    logger.info(f"{bcolors.OKBLUE}Current Balance Before Opening Positions: {balance:.2f} USDT")
                    if balance < 0:  # Minimum balance check
                        logger.error(f"{bcolors.FAIL}Balance {balance:.2f} USDT is too low to open a position")
                        if self.loop:
                            asyncio.run_coroutine_threadsafe(
                                self.async_send_telegram_message(
                                    TELEGRAM_CHAT_ID,
                                    f"Cannot open position on {self.symbol}: Balance {balance:.2f} USDT is too low"
                                ),
                                self.loop
                            )
                        sleep(60)
                        continue

                    stop_loss = price * (1 - 0.005) if signal == 'Long' else price * (1 + 0.005)
                    take_profit = price * (1 + 0.01) if signal == 'Long' else price * (1 - 0.01)
                    quantity = self.calculate_position_size(balance, price, stop_loss_percent=0.005)

                    if quantity == 0:
                        logger.warning(f"{bcolors.WARNING}Cannot Open Positions Because Of Zero Margin")
                        sleep(60)
                        continue

                    try:
                        params = {
                            'category': 'linear',
                            'stopLoss': round(stop_loss, 4),
                            'takeProfit': round(take_profit, 4),
                            'positionIdx': 1 if signal == 'Long' else 2
                        }
                        if signal == 'Long':
                            order = self.exchange.create_market_buy_order(self.symbol, quantity, params)
                        else:
                            order = self.exchange.create_market_sell_order(self.symbol, quantity, params)
                        sleep(15)
                        position = self.get_open_position(side='buy' if signal == 'Long' else 'sell')
                        if position:
                            logger.info(f"{bcolors.OKBLUE}Active Position: {position}")
                            if self.loop:
                                asyncio.run_coroutine_threadsafe(
                                    self.async_send_telegram_message(
                                        TELEGRAM_CHAT_ID,
                                        f"New {signal} on {self.symbol}\nQty: {quantity:.4f}\nLeverage: {self.leverage}x\nEntry: {price:.2f}\nSL: {stop_loss:.2f}\nTP: {take_profit:.2f}\nBalance: {balance:.2f} USDT"
                                    ),
                                    self.loop
                                )
                        else:
                            logger.warning(f"{bcolors.WARNING}Opened Position Not Found after 15 seconds")
                            if self.loop:
                                asyncio.run_coroutine_threadsafe(
                                    self.async_send_telegram_message(
                                        TELEGRAM_CHAT_ID,
                                        f"Warning: Opened position not found after 15 seconds on {self.symbol}"
                                    ),
                                    self.loop
                                )
                    except Exception as e:
                        logger.error(f"{bcolors.FAIL}Exception During Opening Position: {e}")
                        if self.loop:
                            asyncio.run_coroutine_threadsafe(
                                self.async_send_telegram_message(
                                    TELEGRAM_CHAT_ID,
                                    f"Error opening position on {self.symbol}: {e}"
                                ),
                                self.loop
                            )

                sleep(60)

            except Exception as e:
                logger.error(f"{bcolors.FAIL}General Exception In ALGOBOT {self.symbol}: {e}")
                if self.loop:
                    asyncio.run_coroutine_threadsafe(
                        self.async_send_telegram_message(
                            TELEGRAM_CHAT_ID,
                            f"Error in ALGOBOT {self.symbol}: {e}"
                        ),
                        self.loop
                    )
                sleep(60)

    def stop(self):
        self.running = False
        logger.info(f"{bcolors.OKCYAN}ALGOBOT {self.symbol} STOPPED")
        if self.loop:
            asyncio.run_coroutine_threadsafe(
                self.async_send_telegram_message(
                    TELEGRAM_CHAT_ID,
                    f"ALGOBOT stopped for {self.symbol}"
                ),
                self.loop
            )

class BotManager:
    def __init__(self):
        self.bots = []
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.application = Application.builder().token(TELEGRAM_TOKEN).build()
        self.application.add_handler(CommandHandler("start", self.start_telegram))
        self.application.add_handler(CommandHandler("stop", self.stop_telegram))
        self.application.add_handler(CommandHandler("status", self.status_telegram))
        self.application.add_handler(CommandHandler("positions", self.positions_telegram))

    def add_bot(self, symbol, timeframe, indicators):
        bot = TradingBot(symbol, timeframe, indicators, loop=self.loop)
        self.bots.append(bot)
        return bot

    def start_all(self):
        for bot in self.bots:
            threading.Thread(target=bot.run, daemon=True).start()
        threading.Thread(target=self.run_telegram_bot, daemon=True).start()

    def run_telegram_bot(self):
        try:
            self.loop.run_until_complete(self.application.initialize())
            self.loop.run_until_complete(self.application.start())
            self.loop.run_until_complete(self.application.updater.start_polling())
            logger.info(f"{bcolors.OKGREEN}Telegram bot started")
            self.loop.run_forever()
        except Exception as e:
            logger.error(f"{bcolors.FAIL}Error in Telegram bot loop: {e}")
        finally:
            self.loop.run_until_complete(self.application.updater.stop())
            self.loop.run_until_complete(self.application.stop())
            self.loop.run_until_complete(self.application.shutdown())
            if not self.loop.is_closed():
                self.loop.close()
            logger.info(f"{bcolors.OKCYAN}Telegram bot stopped")

    async def start_telegram(self, update, context):
        for bot in self.bots:
            bot.running = True
            threading.Thread(target=bot.run, daemon=True).start()
        await update.message.reply_text("ALGOBOT started")
        logger.info(f"{bcolors.OKGREEN}ALGOBOT started via Telegram")
        for bot in self.bots:
            await bot.async_send_telegram_message(TELEGRAM_CHAT_ID, "ALGOBOT started")

    async def stop_telegram(self, update, context):
        for bot in self.bots:
            bot.stop()
        await update.message.reply_text("ALGOBOT stopped")
        logger.info(f"{bcolors.WARNING}ALGOBOT stopped via Telegram")
        for bot in self.bots:
            await bot.async_send_telegram_message(TELEGRAM_CHAT_ID, "ALGOBOT stopped")

    async def status_telegram(self, update, context):
        for bot in self.bots:
            df = bot.fetch_ohlcv(bot.timeframe)
            indicators = bot.calculate_indicators(df) if df is not None else {}
            long_position = bot.get_open_position(side='buy')
            short_position = bot.get_open_position(side='sell')
            balance = bot.exchange.fetch_balance(params={'recv_window': 60000})['USDT']['free']
            status = f"ALGOBOT Status for {bot.symbol} ({bot.timeframe}):\n"
            status += f"Running: {bot.running}\n"
            status += f"Last Signal: {bot.last_signal}\n"
            status += f"Balance: {balance:.2f} USDT\n"
            status += f"RSI: {indicators.get('RSI', pd.Series([0])).iloc[-1]:.2f}\n"
            status += f"BB Upper: {indicators.get('BB_upper', pd.Series([0])).iloc[-1]:.4f}\n"
            status += f"BB Middle: {indicators.get('BB_middle', pd.Series([0])).iloc[-1]:.4f}\n"
            status += f"BB Lower: {indicators.get('BB_lower', pd.Series([0])).iloc[-1]:.4f}\n"
            status += f"ATR: {indicators.get('ATR', pd.Series([0])).iloc[-1]:.4f}\n"
            status += f"Open Long: {'Yes' if long_position else 'No'}\n"
            status += f"Open Short: {'Yes' if short_position else 'No'}\n"
            await update.message.reply_text(status)
        logger.info(f"{bcolors.OKCYAN}Status requested via Telegram")

    async def positions_telegram(self, update, context):
        stats = ""
        for bot in self.bots:
            positions = bot.exchange.fetch_positions([bot.symbol], params={'category': 'linear'})
            open_positions = len([p for p in positions if p['contracts'] > 0])
            stats += f"ALGOBOT Stats for {bot.symbol} ({bot.timeframe}):\n"
            stats += f"Open Positions: {open_positions}\n\n"
            for pos in positions:
                if pos['contracts'] > 0:
                    stats += f"Side: {pos['side']}, Size: {pos['contracts']:.4f}, Entry: {pos['entryPrice']:.2f}\n"
            stats += "\n"
            await update.message.reply_text(stats)
        logger.info(f"{bcolors.OKCYAN}Positions stats requested via Telegram")

if __name__ == "__main__":
    manager = BotManager()

    # Bot1: 1-minute timeframe for trading
    bot1 = manager.add_bot(
        symbol='BTC/USDT:USDT',
        timeframe='1m',
        indicators=['RSI', 'Bollinger', 'Volume', 'ATR']
    )

    manager.start_all()

    try:
        while True:
            sleep(1)
    except KeyboardInterrupt:
        for bot in manager.bots:
            bot.stop()