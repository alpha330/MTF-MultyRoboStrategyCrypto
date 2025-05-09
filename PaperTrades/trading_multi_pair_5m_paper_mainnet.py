import ccxt.async_support as ccxt_async
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
import uuid
from tenacity import retry, stop_after_attempt, wait_exponential

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
        logging.FileHandler('/root/MTF-MultyRoboStrategyCrypto/initialBot/trading_multi_pair_5m_paper_mainnet.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN_PAPER1M_10')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHANAL_ID')
BYBIT_LIVE_API_SECRET = os.getenv('BYBIT_LIVE_API_SECRET')
BYBIT_LIVE_API_KEY = os.getenv('BYBIT_LIVE_API_KEY')

# Validate environment variables
if not all([TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, BYBIT_LIVE_API_KEY, BYBIT_LIVE_API_SECRET]):
    raise ValueError("Missing required environment variables in .env file")

# Telegram Bot Setup
try:
    telegram_bot = telegram.Bot(token=TELEGRAM_TOKEN)
except Exception as e:
    logger.error(f"{bcolors.FAIL}Error initializing Telegram bot: {e}")
    raise

class Wallet:
    def __init__(self, initial_balance=100):
        self.balance = initial_balance
        self.positions = []
        self.trade_history = []
        self.fee_rate = 0.00075
        self.max_margin_ratio = 0.8  # افزایش به 0.8 برای انعطاف بیشتر

    def get_used_margin(self):
        used_margin = 0
        for pos in self.positions:
            position_value = pos['quantity'] * pos['entry_price']
            margin = position_value / pos['leverage']
            used_margin += margin
        return used_margin

    def can_open_position(self, position_value, leverage):
        margin_required = position_value / leverage
        used_margin = self.get_used_margin()
        max_allowed_margin = self.balance * self.max_margin_ratio
        logger.info(f"Checking margin: Required={margin_required:.2f}, Used={used_margin:.2f}, Max Allowed={max_allowed_margin:.2f}")
        return used_margin + margin_required <= max_allowed_margin

class TradingBot:
    def __init__(self, symbol, timeframe='5m', leverage=5, risk_percent=0.02, wallet=None):
        self.symbol = symbol
        self.timeframe = timeframe
        self.leverage = leverage
        self.risk_percent = risk_percent
        self.running = False
        self.last_signal = 'Neutral'
        self.exchange = ccxt_async.bybit({
            'apiKey': BYBIT_LIVE_API_KEY,
            'secret': BYBIT_LIVE_API_SECRET,
            'enableRateLimit': True
        })
        self.wallet = wallet
        self.atr_threshold = None
        self._set_leverage()

    def _set_leverage(self):
        logger.info(f"{bcolors.OKCYAN}LEVERAGE {self.leverage}x FOR {self.symbol} SET FOR PAPER TRADING (MAINNET)")

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=10))
    async def fetch_ohlcv(self):
        try:
            ohlcv = await self.exchange.fetch_ohlcv(self.symbol, self.timeframe, limit=400)
            df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            logger.info(f"{bcolors.OKGREEN}FOR OHLCV DATA {self.symbol} IN {self.timeframe} CANDLES ARE GET: {len(df)} (MAINNET)")
            if len(df) < 50:
                logger.warning(f"{bcolors.WARNING}CANDLES ({len(df)}) FOR {self.symbol} IN {self.timeframe} NOT ENOUGH")
                return None
            return df
        except Exception as e:
            logger.error(f"{bcolors.FAIL}EXCEPTION DURING GETTING DATA CANDLE {self.symbol} IN {self.timeframe}: {str(e)}")
            raise
        finally:
            await asyncio.sleep(0.5)  # تأخیر 0.5 ثانیه برای کاهش فشار روی API

    def calculate_indicators(self, df):
        indicators_data = {}
        indicators_data['EMA5'] = ta.trend.EMAIndicator(df['close'], window=5).ema_indicator()
        indicators_data['VWAP'] = ta.volume.VolumeWeightedAveragePrice(df['high'], df['low'], df['close'], df['volume'], window=14).volume_weighted_average_price()
        indicators_data['RSI'] = ta.momentum.RSIIndicator(df['close'], window=5).rsi()
        indicators_data['Volume'] = df['volume']
        indicators_data['Volume_MA'] = ta.trend.SMAIndicator(df['volume'], window=20).sma_indicator()
        indicators_data['Swing_High'] = df['high'].rolling(window=5).max()
        indicators_data['Swing_Low'] = df['low'].rolling(window=5).min()
        indicators_data['ATR'] = ta.volatility.AverageTrueRange(df['high'], df['low'], df['close'], window=5).average_true_range()
        return indicators_data

    def calculate_position_size(self, price, stop_loss_price):
        stop_loss_distance = abs(price - stop_loss_price)
        if stop_loss_distance == 0:
            logger.error(f"{bcolors.WARNING}Stop Loss distance is zero, cannot calculate position size")
            return 0
        risk_amount = self.wallet.balance * self.risk_percent
        quantity = risk_amount / stop_loss_distance
        effective_balance = self.wallet.balance * self.leverage
        max_quantity = effective_balance / price
        quantity = min(quantity, max_quantity)
        position_value = quantity * price
        logger.info(f"Position calculation: Price={price:.4f}, SL Distance={stop_loss_distance:.4f}, Quantity={quantity:.4f}, Position Value={position_value:.2f}")
        if not self.wallet.can_open_position(position_value, self.leverage):
            logger.warning(f"{bcolors.WARNING}Cannot open position on {self.symbol}: Exceeds {self.wallet.max_margin_ratio*100}% balance margin limit")
            return 0
        try:
            quantity = float(self.exchange.amount_to_precision(self.symbol, quantity))
            logger.info(f"Adjusted Quantity: {quantity:.4f}")
        except Exception as e:
            logger.error(f"{bcolors.FAIL}Error adjusting quantity precision: {e}")
            quantity = round(quantity, 4)
        if quantity <= 0:
            logger.warning(f"{bcolors.WARNING}Invalid quantity: {quantity}")
            return 0
        return quantity

    def get_open_position(self, side=None):
        for pos in self.wallet.positions:
            if pos['symbol'] == self.symbol and (side is None or 
               (side == 'buy' and pos['side'] == 'Long') or 
               (side == 'sell' and pos['side'] == 'Short')):
                return pos
        return None

    def close_position(self, position, exit_price, reason='Manual', close_percentage=1.0):
        try:
            quantity = position['quantity'] * close_percentage
            entry_price = position['entry_price']
            side = position['side']
            if side == 'Long':
                pnl = (exit_price - entry_price) * quantity
            else:  # Short
                pnl = (entry_price - exit_price) * quantity
            entry_fee = entry_price * quantity * self.wallet.fee_rate
            exit_fee = exit_price * quantity * self.wallet.fee_rate
            total_pnl = pnl - entry_fee - exit_fee
            self.wallet.balance += total_pnl
            status = 'Win' if total_pnl > 0 else 'Loss'
            trade_record = {
                'id': position['id'],
                'side': side,
                'symbol': self.symbol,
                'quantity': quantity,
                'entry_price': entry_price,
                'exit_price': exit_price,
                'pnl': total_pnl,
                'reason': reason,
                'status': status,
                'leverage': self.leverage,
                'stop_loss': position['stop_loss'],
                'take_profit': position['take_profit'],
                'timestamp': datetime.datetime.now().isoformat()
            }
            self.wallet.trade_history.append(trade_record)
            if close_percentage < 1.0:
                position['quantity'] *= (1 - close_percentage)
                position['stop_loss'] = position['trailing_stop']
            else:
                self.wallet.positions.remove(position)
            logger.info(f"{bcolors.OKGREEN}POSITION CLOSED: {side}, Symbol: {self.symbol}, Quantity: {quantity:.4f}, Entry: {entry_price:.4f}, Exit: {exit_price:.4f}, PnL: {total_pnl:.2f}, Reason: {reason}, Status: {status}")
            logger.info(f"{bcolors.OKBLUE}New Balance: {self.wallet.balance:.2f} USDT, Used Margin: {self.wallet.get_used_margin():.2f} USDT")
            try:
                asyncio.create_task(telegram_bot.send_message(
                    chat_id=TELEGRAM_CHAT_ID,
                    text=f"Position closed on {self.symbol} (Paper Trading, Mainnet)\n"
                         f"Side: {side}\nQuantity: {quantity:.4f}\n"
                         f"Entry Price: {entry_price:.4f}\nExit Price: {exit_price:.4f}\n"
                         f"PnL: {total_pnl:.2f} USDT ({status})\nReason: {reason}\n"
                         f"New Balance: {self.wallet.balance:.2f} USDT"
                ))
            except Exception as telegram_error:
                logger.error(f"{bcolors.FAIL}Error sending Telegram message: {telegram_error}")
        except Exception as e:
            logger.error(f"{bcolors.FAIL}EXCEPTION DURING CLOSE POSITION on {self.symbol}: {e}")

    def check_tp_sl_trailing(self, current_price, ema5):
        for pos in self.wallet.positions[:]:
            if pos['symbol'] != self.symbol:
                continue
            stop_loss = pos['stop_loss']
            take_profit = pos['take_profit']
            side = pos['side']
            if side == 'Long':
                if current_price <= stop_loss:
                    self.close_position(pos, stop_loss, reason='Stop Loss Hit')
                    continue
                elif current_price >= take_profit and not pos.get('first_target_hit', False):
                    self.close_position(pos, take_profit, reason='Take Profit Hit (1:1)', close_percentage=0.5)
                    pos['first_target_hit'] = True
                    pos['trailing_stop'] = max(stop_loss, ema5)
                    continue
                elif pos.get('first_target_hit', False):
                    pos['trailing_stop'] = max(pos['trailing_stop'], ema5)
                    if current_price <= pos['trailing_stop']:
                        self.close_position(pos, pos['trailing_stop'], reason='Trailing Stop Hit')
            else:  # Short
                if current_price >= stop_loss:
                    self.close_position(pos, stop_loss, reason='Stop Loss Hit')
                    continue
                elif current_price <= take_profit and not pos.get('first_target_hit', False):
                    self.close_position(pos, take_profit, reason='Take Profit Hit (1:1)', close_percentage=0.5)
                    pos['first_target_hit'] = True
                    pos['trailing_stop'] = min(stop_loss, ema5)
                    continue
                elif pos.get('first_target_hit', False):
                    pos['trailing_stop'] = min(pos['trailing_stop'], ema5)
                    if current_price >= pos['trailing_stop']:
                        self.close_position(pos, pos['trailing_stop'], reason='Trailing Stop Hit')

    def get_positions_stats(self):
        total_positions = len([t for t in self.wallet.trade_history if t['symbol'] == self.symbol])
        open_positions = len([p for p in self.wallet.positions if p['symbol'] == self.symbol])
        win_positions = len([t for t in self.wallet.trade_history if t['symbol'] == self.symbol and t['status'] == 'Win'])
        loss_positions = len([t for t in self.wallet.trade_history if t['symbol'] == self.symbol and t['status'] == 'Loss'])
        return {
            'total_positions': total_positions,
            'open_positions': open_positions,
            'win_positions': win_positions,
            'loss_positions': loss_positions
        }

    async def run(self):
        self.running = True
        logger.info(f"{bcolors.OKBLUE}ALGOBOT {self.symbol} IN TIME FRAME {self.timeframe} HAS BEEN STARTED (PAPER TRADING, MAINNET)")
        while self.running:
            try:
                df = await self.fetch_ohlcv()
                if df is None or df.empty:
                    logger.warning(f"{bcolors.WARNING}DATA OHLCV FOR {self.symbol} IN {self.timeframe} NOT VALID")
                    await asyncio.sleep(60)
                    continue

                indicators_data = self.calculate_indicators(df)
                price = df['close'].iloc[-1]
                self.atr_threshold = price * 0.001

                ema5 = indicators_data['EMA5'].iloc[-1]
                self.check_tp_sl_trailing(price, ema5)

                vwap = indicators_data['VWAP'].iloc[-1]
                rsi = indicators_data['RSI'].iloc[-1]
                volume = indicators_data['Volume'].iloc[-1]
                volume_ma = indicators_data['Volume_MA'].iloc[-1]
                swing_low = indicators_data['Swing_Low'].iloc[-1]
                swing_high = indicators_data['Swing_High'].iloc[-1]
                atr = indicators_data['ATR'].iloc[-1]

                logger.info(f"{bcolors.OKCYAN}Indicators for {self.symbol} - EMA5: {ema5:.4f}, VWAP: {vwap:.4f}, RSI: {rsi:.2f}, Volume: {volume:.2f}, Volume MA: {volume_ma:.2f}, Swing Low: {swing_low:.4f}, Swing High: {swing_high:.4f}, ATR: {atr:.4f}")

                long_position = self.get_open_position(side='buy')
                short_position = self.get_open_position(side='sell')

                if long_position and ema5 < vwap:
                    self.close_position(long_position, price, reason='EMA5 below VWAP')
                    await asyncio.sleep(60)
                    continue
                if short_position and ema5 > vwap:
                    self.close_position(short_position, price, reason='EMA5 above VWAP')
                    await asyncio.sleep(60)
                    continue

                signal = None
                if (ema5 > vwap and
                    20 <= rsi <= 60 and
                    volume > volume_ma and
                    atr > self.atr_threshold):
                    signal = 'Long'
                elif (ema5 < vwap and
                      40 <= rsi <= 80 and
                      volume > volume_ma and
                      atr > self.atr_threshold):
                    signal = 'Short'

                if signal:
                    logger.info(f"{bcolors.OKBLUE}Current Balance Before Opening Positions on {self.symbol}: {self.wallet.balance:.2f} USDT, Used Margin: {self.wallet.get_used_margin():.2f} USDT")
                    stop_loss = price * (1 - 0.005) if signal == 'Long' else price * (1 + 0.005)
                    take_profit = price * (1 + 0.01) if signal == 'Long' else price * (1 - 0.01)
                    quantity = self.calculate_position_size(price, stop_loss)
                    if quantity == 0:
                        logger.warning(f"{bcolors.WARNING}Cannot Open Position on {self.symbol}: Zero Quantity or Margin Limit")
                        await asyncio.sleep(60)
                        continue

                    stop_loss = round(stop_loss, 4)
                    take_profit = round(take_profit, 4)

                    logger.info(f"{bcolors.OKBLUE}Signal {signal} on {self.symbol} - Price: {price:.4f}, Quantity: {quantity:.4f}, Stop Loss: {stop_loss:.4f}, Take Profit: {take_profit:.4f}")

                    try:
                        position = {
                            'id': str(uuid.uuid4()),
                            'side': signal,
                            'symbol': self.symbol,
                            'quantity': quantity,
                            'entry_price': price,
                            'stop_loss': stop_loss,
                            'take_profit': take_profit,
                            'leverage': self.leverage,
                            'timestamp': datetime.datetime.now().isoformat(),
                            'first_target_hit': False
                        }
                        self.wallet.positions.append(position)
                        logger.info(f"{bcolors.OKBLUE}Order created successfully on {self.symbol} (Paper Trading): {position}")

                        try:
                            await telegram_bot.send_message(
                                chat_id=TELEGRAM_CHAT_ID,
                                text=f"New {signal} position opened on {self.symbol} (Paper Trading, Mainnet)\n"
                                     f"Symbol: {self.symbol}\n"
                                     f"Side: {signal}\nQuantity: {quantity:.4f}\n"
                                     f"Leverage: {self.leverage}x\n"
                                     f"Entry Price: {price:.4f}\n"
                                     f"Stop Loss: {stop_loss:.4f}\n"
                                     f"Take Profit: {take_profit:.4f}\n"
                                     f"Balance: {self.wallet.balance:.2f} USDT\n"
                                     f"Used Margin: {self.wallet.get_used_margin():.2f} USDT"
                            )
                        except Exception as telegram_error:
                            logger.error(f"{bcolors.FAIL}Error sending Telegram message: {telegram_error}")

                    except Exception as e:
                        logger.error(f"{bcolors.FAIL}Exception During Opening Position on {self.symbol}: {e}")
                        try:
                            await telegram_bot.send_message(
                                chat_id=TELEGRAM_CHAT_ID,
                                text=f"Failed to open {signal} position on {self.symbol} (Paper Trading)\nError: {e}"
                            )
                        except Exception as telegram_error:
                            logger.error(f"{bcolors.FAIL}Error sending Telegram error message: {telegram_error}")

                await asyncio.sleep(60)

            except Exception as e:
                logger.error(f"{bcolors.FAIL}General Exception In ALGOBOT {self.symbol}: {e}")
                await asyncio.sleep(60)

    async def stop(self):
        self.running = False
        logger.info(f"{bcolors.OKCYAN}ALGOBOT {self.symbol} STOPPED (PAPER TRADING, MAINNET)")
        try:
            await telegram_bot.send_message(
                chat_id=TELEGRAM_CHAT_ID,
                text=f"Trading bot for {self.symbol} ({self.timeframe}) stopped (Paper Trading, Mainnet)\n"
                     f"Final Balance: {self.wallet.balance:.2f} USDT"
            )
        except Exception as telegram_error:
            logger.error(f"{bcolors.FAIL}Error sending Telegram message: {telegram_error}")

    async def get_status(self):
        df = await self.fetch_ohlcv()
        if df is None:
            return f"Error fetching data for {self.symbol}"
        indicators = self.calculate_indicators(df)
        long_pos = self.get_open_position(side='buy')
        short_pos = self.get_open_position(side='sell')
        status = f"Bot Status for {self.symbol} ({self.timeframe}) (Paper Trading, Mainnet):\n"
        status += f"Running: {self.running}\n"
        status += f"Last Signal: {self.last_signal}\n"
        status += f"Balance: {self.wallet.balance:.2f} USDT\n"
        status += f"Used Margin: {self.wallet.get_used_margin():.2f} USDT\n"
        status += f"EMA5: {indicators.get('EMA5', pd.Series([0])).iloc[-1]:.4f}\n"
        status += f"VWAP: {indicators.get('VWAP', pd.Series([0])).iloc[-1]:.4f}\n"
        status += f"RSI: {indicators.get('RSI', pd.Series([0])).iloc[-1]:.2f}\n"
        status += f"Volume: {indicators.get('Volume', pd.Series([0])).iloc[-1]:.2f}\n"
        status += f"Volume MA: {indicators.get('Volume_MA', pd.Series([0])).iloc[-1]:.2f}\n"
        status += f"ATR: {indicators.get('ATR', pd.Series([0])).iloc[-1]:.4f}\n"
        status += f"Open Long Position: {'Yes' if long_pos else 'No'}\n"
        status += f"Open Short Position: {'Yes' if short_pos else 'No'}\n"
        return status

class BotManager:
    def __init__(self):
        self.bots = []
        self.wallet = Wallet(initial_balance=100)

    def add_bot(self, symbol, timeframe):
        bot = TradingBot(symbol, timeframe, wallet=self.wallet)
        self.bots.append(bot)
        return bot

    async def run_all(self):
        tasks = [bot.run() for bot in self.bots]
        await asyncio.gather(*tasks)

# Telegram command handlers
async def start(update, context):
    global manager
    for bot in manager.bots:
        bot.running = True
    await update.message.reply_text("Trading bots started (Paper Trading, Mainnet)")
    logger.info(f"{bcolors.OKGREEN}Bots started via Telegram (Paper Trading, Mainnet)")

async def stop(update, context):
    global manager
    for bot in manager.bots:
        await bot.stop()
    await update.message.reply_text("Trading bots stopped (Paper Trading, Mainnet)")
    logger.info(f"{bcolors.WARNING}Bots stopped via Telegram (Paper Trading, Mainnet)")

async def status(update, context):
    global manager
    for bot in manager.bots:
        try:
            if not update.message:
                logger.error(f"{bcolors.FAIL}No message object in update for {bot.symbol}")
                continue
            status = await bot.get_status()
            await update.message.reply_text(status)
        except Exception as e:
            logger.error(f"{bcolors.FAIL}Error getting status for {bot.symbol}: {e}")
            if update.message:
                await update.message.reply_text(f"Error fetching status for {bot.symbol}: {e}")
    logger.info(f"{bcolors.OKCYAN}Status requested via Telegram (Paper Trading, Mainnet)")

async def positions(update, context):
    global manager
    stats = ""
    for bot in manager.bots:
        pos_stats = bot.get_positions_stats()
        stats += f"Positions Stats for {bot.symbol} (Paper Trading, Mainnet):\n"
        stats += f"Total Positions: {pos_stats['total_positions']}\n"
        stats += f"Open Positions: {pos_stats['open_positions']}\n"
        stats += f"Win Positions: {pos_stats['win_positions']}\n"
        stats += f"Loss Positions: {pos_stats['loss_positions']}\n\n"
    stats += f"Wallet Balance: {manager.wallet.balance:.2f} USDT\n"
    stats += f"Used Margin: {manager.wallet.get_used_margin():.2f} USDT\n"
    await update.message.reply_text(stats)
    logger.info(f"{bcolors.OKCYAN}Positions stats requested via Telegram (Paper Trading, Mainnet)")

async def run_telegram_bot():
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("stop", stop))
    application.add_handler(CommandHandler("status", status))
    application.add_handler(CommandHandler("positions", positions))
    await application.initialize()
    await application.start()
    await application.updater.start_polling()
    while True:
        await asyncio.sleep(3600)

async def main():
    global manager
    try:
        manager = BotManager()
        trading_pairs = [
            'XRP/USDT:USDT', 'BTC/USDT:USDT', 'ETH/USDT:USDT', 'BNB/USDT:USDT','SOL/USDT:USDT'
        ]  # کاهش به 10 جفت‌ارز برای کاهش فشار روی API
        for symbol in trading_pairs:
            try:
                manager.add_bot(symbol=symbol, timeframe='5m')
                logger.info(f"{bcolors.OKGREEN}Bot added for {symbol}")
            except Exception as e:
                logger.error(f"{bcolors.FAIL}Failed to add bot for {symbol}: {e}")
        
        tasks = [manager.run_all(), run_telegram_bot()]
        await asyncio.gather(*tasks)
        
        telegram_bot.send_message(
            chat_id=TELEGRAM_CHAT_ID,
            text="Trading bots initialized for 10 pairs (Paper Trading, Mainnet, 5m)"
        )
    except Exception as e:
        logger.error(f"{bcolors.FAIL}Fatal error in main: {e}")
        telegram_bot.send_message(
            chat_id=TELEGRAM_CHAT_ID,
            text=f"Fatal error in bot: {e}"
        )

if __name__ == "__main__":
    asyncio.run(main())