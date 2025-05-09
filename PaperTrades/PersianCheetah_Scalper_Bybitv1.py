import ccxt.async_support as ccxt_async
import pandas as pd
import ta
import logging
import asyncio
import datetime
import telegram
from telegram.ext import Application, CommandHandler
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

# Create log directory if it doesn't exist
log_dir = '/root/MTF-MultyRoboStrategyCrypto/PaperTrades/logs'
os.makedirs(log_dir, exist_ok=True)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(os.path.join(log_dir, 'PersianCheetah_Scalper_Bybit.log')),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN_PERSIAN_CHEETAH')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHANAL_ID')
BYBIT_LIVE_API_KEY = os.getenv('BYBIT_LIVE_API_KEY')
BYBIT_LIVE_API_SECRET = os.getenv('BYBIT_LIVE_API_SECRET')

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
        self.fee_rate = 0.0002  # Bybit Maker fee for futures
        self.max_margin_ratio = 0.8

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

class PersianCheetahScalper:
    def __init__(self, symbol, timeframe='1m', leverage=10, risk_percent=0.1, wallet=None):
        self.symbol = symbol
        self.timeframe = timeframe
        self.leverage = 5 if 'XRP' in symbol else leverage  # Lower leverage for XRP
        self.risk_percent = risk_percent
        self.running = False
        self.last_signal = 'Neutral'
        self.exchange = ccxt_async.bybit({
            'apiKey': BYBIT_LIVE_API_KEY,
            'secret': BYBIT_LIVE_API_SECRET,
            'enableRateLimit': True
        })
        self.wallet = wallet
        if self.wallet is None:
            logger.error(f"{bcolors.FAIL}Wallet is not provided for {self.symbol}")
            raise ValueError("Wallet must be provided")
        self.trailing_stop_percent = 0.003 if 'XRP' in symbol else 0.005
        self.trailing_profit_percent = 0.005

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=10))
    async def fetch_ohlcv(self):
        try:
            ohlcv = await self.exchange.fetch_ohlcv(self.symbol, self.timeframe, limit=200, params={'category': 'linear'})
            df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            logger.info(f"{bcolors.OKGREEN}Fetched {len(df)} OHLCV candles for {self.symbol} in {self.timeframe}")
            if len(df) < 50:
                logger.warning(f"{bcolors.WARNING}Insufficient candles ({len(df)}) for {self.symbol}")
                return None
            return df
        except Exception as e:
            logger.error(f"{bcolors.FAIL}Error fetching OHLCV for {self.symbol}: {e}")
            raise
        finally:
            await asyncio.sleep(0.2)

    def calculate_indicators(self, df):
        try:
            indicators = {}
            indicators['RSI'] = ta.momentum.RSIIndicator(df['close'], window=14).rsi()
            bb = ta.volatility.BollingerBands(df['close'], window=20, window_dev=2)
            indicators['BB_upper'] = bb.bollinger_hband()
            indicators['BB_middle'] = bb.bollinger_mavg()
            indicators['BB_lower'] = bb.bollinger_lband()
            indicators['Volume'] = df['volume']
            indicators['Volume_MA'] = ta.trend.SMAIndicator(df['volume'], window=20).sma_indicator()
            indicators['ATR'] = ta.volatility.AverageTrueRange(df['high'], df['low'], df['close'], window=14).average_true_range()
            return indicators
        except Exception as e:
            logger.error(f"{bcolors.FAIL}Error calculating indicators for {self.symbol}: {e}")
            return None

    def calculate_position_size(self, price, stop_loss_price):
        risk_amount = self.wallet.balance * self.risk_percent  
        position_value = risk_amount * self.leverage  
        quantity = position_value / price
        if not self.wallet.can_open_position(position_value, self.leverage):
            logger.warning(f"{bcolors.WARNING}Cannot open position on {self.symbol}: Margin limit exceeded")
            return 0
        try:
            quantity = float(self.exchange.amount_to_precision(self.symbol, quantity))
        except Exception as e:
            logger.error(f"{bcolors.FAIL}Error adjusting quantity precision: {e}")
            quantity = round(quantity, 4)
        if quantity <= 0:
            logger.warning(f"{bcolors.WARNING}Invalid quantity: {quantity}")
            return 0
        logger.info(f"{bcolors.OKCYAN}Calculated position: Value={position_value:.2f}, Quantity={quantity:.4f}, Margin={position_value/self.leverage:.2f}")
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
            logger.info(f"{bcolors.OKGREEN}POSITION CLOSED: {side}, {self.symbol}, Qty: {quantity:.4f}, Entry: {entry_price:.4f}, Exit: {exit_price:.4f}, PnL: {total_pnl:.2f}, Reason: {reason}")
            logger.info(f"{bcolors.OKBLUE}Balance: {self.wallet.balance:.2f} USDT, Margin: {self.wallet.get_used_margin():.2f}")
            asyncio.create_task(telegram_bot.send_message(
                chat_id=TELEGRAM_CHAT_ID,
                text=f"PersianCheetah_Scalper_Bybit: Position closed on {self.symbol}\n"
                     f"Side: {side}\nQty: {quantity:.4f}\nEntry: {entry_price:.4f}\nExit: {exit_price:.4f}\n"
                     f"PnL: {total_pnl:.2f} USDT ({status})\nReason: {reason}\nBalance: {self.wallet.balance:.2f} USDT"
            ))
        except Exception as e:
            logger.error(f"{bcolors.FAIL}Error closing position on {self.symbol}: {e}")

    def check_tp_sl_trailing(self, current_price, bb_middle):
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
                if current_price >= take_profit:
                    pos['take_profit'] = current_price * (1 + self.trailing_profit_percent)
                    pos['stop_loss'] = max(pos['stop_loss'], current_price * (1 - self.trailing_stop_percent))
                    pos['first_target_hit'] = True
                if pos.get('first_target_hit', False):
                    pos['trailing_stop'] = max(pos['trailing_stop'], current_price * (1 - self.trailing_stop_percent))
                    if current_price <= pos['trailing_stop']:
                        self.close_position(pos, pos['trailing_stop'], reason='Trailing Stop Hit')
            else:  # Short
                if current_price >= stop_loss:
                    self.close_position(pos, stop_loss, reason='Stop Loss Hit')
                    continue
                if current_price <= take_profit:
                    pos['take_profit'] = current_price * (1 - self.trailing_profit_percent)
                    pos['stop_loss'] = min(pos['stop_loss'], current_price * (1 + self.trailing_stop_percent))
                    pos['first_target_hit'] = True
                if pos.get('first_target_hit', False):
                    pos['trailing_stop'] = min(pos['trailing_stop'], current_price * (1 + self.trailing_stop_percent))
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
        logger.info(f"{bcolors.OKBLUE}PersianCheetah_Scalper_Bybit started for {self.symbol} (1m, Paper Trading)")
        while self.running:
            try:
                df = await self.fetch_ohlcv()
                if df is None or df.empty:
                    logger.warning(f"{bcolors.WARNING}Invalid OHLCV data for {self.symbol}")
                    await asyncio.sleep(10)
                    continue

                indicators = self.calculate_indicators(df)
                if indicators is None:
                    logger.warning(f"{bcolors.WARNING}Failed to calculate indicators for {self.symbol}")
                    await asyncio.sleep(10)
                    continue

                price = df['close'].iloc[-1]
                rsi = indicators['RSI'].iloc[-1]
                bb_upper = indicators['BB_upper'].iloc[-1]
                bb_middle = indicators['BB_middle'].iloc[-1]
                bb_lower = indicators['BB_lower'].iloc[-1]
                volume = indicators['Volume'].iloc[-1]
                volume_ma = indicators['Volume_MA'].iloc[-1]
                atr = indicators['ATR'].iloc[-1]

                atr_threshold = price * 0.0005
                logger.info(f"{bcolors.OKCYAN}{self.symbol} - RSI: {rsi:.2f}, BB Upper: {bb_upper:.4f}, BB Middle: {bb_middle:.4f}, BB Lower: {bb_lower:.4f}, Volume: {volume:.2f}, ATR: {atr:.4f}, Wallet Balance: {self.wallet.balance:.2f}")

                long_conditions = {
                    'RSI < 40': rsi < 40,
                    'Price <= BB Lower': price <= bb_lower,
                    'Volume > Volume MA': volume > volume_ma,
                    'ATR > Threshold': atr > atr_threshold
                }
                short_conditions = {
                    'RSI > 60': rsi > 60,
                    'Price >= BB Upper': price >= bb_upper,
                    'Volume > Volume MA': volume > volume_ma,
                    'ATR > Threshold': atr > atr_threshold
                }
                logger.info(f"{bcolors.OKCYAN}Long Conditions for {self.symbol}: {long_conditions}")
                logger.info(f"{bcolors.OKCYAN}Short Conditions for {self.symbol}: {short_conditions}")

                self.check_tp_sl_trailing(price, bb_middle)

                long_position = self.get_open_position(side='buy')
                short_position = self.get_open_position(side='sell')

                if long_position and rsi > 60:
                    self.close_position(long_position, price, reason='RSI above 60')
                    await asyncio.sleep(10)
                    continue
                if short_position and rsi < 40:
                    self.close_position(short_position, price, reason='RSI below 40')
                    await asyncio.sleep(10)
                    continue

                signal = None
                if all(long_conditions.values()):
                    signal = 'Long'
                elif all(short_conditions.values()):
                    signal = 'Short'

                if signal:
                    logger.info(f"{bcolors.OKBLUE}Balance before {signal} on {self.symbol}: {self.wallet.balance:.2f} USDT")
                    stop_loss = price * (1 - 0.005) if signal == 'Long' else price * (1 + 0.005)
                    take_profit = price * (1 + 0.01) if signal == 'Long' else price * (1 - 0.01)
                    quantity = self.calculate_position_size(price, stop_loss)
                    if quantity == 0:
                        logger.warning(f"{bcolors.WARNING}Cannot open position on {self.symbol}: Zero quantity")
                        await asyncio.sleep(10)
                        continue

                    stop_loss = round(stop_loss, 4)
                    take_profit = round(take_profit, 4)

                    position = {
                        'id': str(uuid.uuid4()),
                        'side': signal,
                        'symbol': self.symbol,
                        'quantity': quantity,
                        'entry_price': price,
                        'stop_loss': stop_loss,
                        'take_profit': take_profit,
                        'leverage': self.leverage,
                        'trailing_stop': stop_loss,
                        'timestamp': datetime.datetime.now().isoformat(),
                        'first_target_hit': False
                    }
                    self.wallet.positions.append(position)
                    logger.info(f"{bcolors.OKBLUE}Opened {signal} on {self.symbol}: Qty: {quantity:.4f}, SL: {stop_loss:.4f}, TP: {take_profit:.4f}")

                    await telegram_bot.send_message(
                        chat_id=TELEGRAM_CHAT_ID,
                        text=f"PersianCheetah_Scalper_Bybit: New {signal} on {self.symbol}\n"
                             f"Qty: {quantity:.4f}\nLeverage: {self.leverage}x\nEntry: {price:.4f}\n"
                             f"SL: {stop_loss:.4f}\nTP: {take_profit:.4f}\nBalance: {self.wallet.balance:.2f} USDT"
                    )

                await asyncio.sleep(10)

            except Exception as e:
                logger.error(f"{bcolors.FAIL}Error in PersianCheetah_Scalper_Bybit for {self.symbol}: {e}")
                await asyncio.sleep(10)

    async def stop(self):
        self.running = False
        logger.info(f"{bcolors.OKCYAN}PersianCheetah_Scalper_Bybit stopped for {self.symbol}")
        await telegram_bot.send_message(
            chat_id=TELEGRAM_CHAT_ID,
            text=f"PersianCheetah_Scalper_Bybit stopped for {self.symbol}\nBalance: {self.wallet.balance:.2f} USDT"
        )

    async def get_status(self):
        df = await self.fetch_ohlcv()
        if df is None:
            return f"Error fetching data for {self.symbol}"
        indicators = self.calculate_indicators(df)
        if indicators is None:
            return f"Error calculating indicators for {self.symbol}"
        long_position = self.get_open_position(side='buy')
        short_position = self.get_open_position(side='sell')
        status = f"PersianCheetah_Scalper_Bybit Status for {self.symbol} (1m, Paper Trading):\n"
        status += f"Running: {self.running}\n"
        status += f"Last Signal: {self.last_signal}\n"
        status += f"Balance: {self.wallet.balance:.2f} USDT\n"
        status += f"Used Margin: {self.wallet.get_used_margin():.2f} USDT\n"
        status += f"RSI: {indicators.get('RSI', pd.Series([0])).iloc[-1]:.2f}\n"
        status += f"BB Upper: {indicators.get('BB_upper', pd.Series([0])).iloc[-1]:.4f}\n"
        status += f"BB Middle: {indicators.get('BB_middle', pd.Series([0])).iloc[-1]:.4f}\n"
        status += f"BB Lower: {indicators.get('BB_lower', pd.Series([0])).iloc[-1]:.4f}\n"
        status += f"ATR: {indicators.get('ATR', pd.Series([0])).iloc[-1]:.4f}\n"
        status += f"Open Long: {'Yes' if long_position else 'No'}\n"
        status += f"Open Short: {'Yes' if short_position else 'No'}\n"
        return status

class BotManager:
    def __init__(self):
        self.bots = []
        self.wallet = Wallet(initial_balance=100)

    def add_bot(self, symbol, timeframe):
        bot = PersianCheetahScalper(symbol, timeframe, wallet=self.wallet)
        self.bots.append(bot)
        return bot

    async def run_all(self):
        tasks = [bot.run() for bot in self.bots]
        await asyncio.gather(*tasks)

async def start(update, context):
    global manager
    for bot in manager.bots:
        bot.running = True
    await update.message.reply_text("PersianCheetah_Scalper_Bybit started")
    logger.info(f"{bcolors.OKGREEN}PersianCheetah_Scalper_Bybit started via Telegram")

async def stop(update, context):
    global manager
    for bot in manager.bots:
        await bot.stop()
    await update.message.reply_text("PersianCheetah_Scalper_Bybit stopped")
    logger.info(f"{bcolors.WARNING}PersianCheetah_Scalper_Bybit stopped via Telegram")

async def status(update, context):
    global manager
    for bot in manager.bots:
        status = await bot.get_status()
        await update.message.reply_text(status)
    logger.info(f"{bcolors.OKCYAN}Status requested via Telegram")

async def positions(update, context):
    global manager
    stats = ""
    for bot in manager.bots:
        pos_stats = bot.get_positions_stats()
        stats += f"PersianCheetah_Scalper_Bybit Stats for {bot.symbol}:\n"
        stats += f"Total Positions: {pos_stats['total_positions']}\n"
        stats += f"Open Positions: {pos_stats['open_positions']}\n"
        stats += f"Win Positions: {pos_stats['win_positions']}\n"
        stats += f"Loss Positions: {pos_stats['loss_positions']}\n\n"
    stats += f"Wallet Balance: {manager.wallet.balance:.2f} USDT\n"
    stats += f"Used Margin: {manager.wallet.get_used_margin():.2f} USDT\n"
    await update.message.reply_text(stats)
    logger.info(f"{bcolors.OKCYAN}Positions stats requested via Telegram")

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
        trading_pairs = ['BTCUSDT', 'ETHUSDT', 'XRPUSDT']
        for symbol in trading_pairs:
            manager.add_bot(symbol=symbol, timeframe='1m')
            logger.info(f"{bcolors.OKGREEN}Added bot for {symbol}")
        tasks = [manager.run_all(), run_telegram_bot()]
        await asyncio.gather(*tasks)
        await telegram_bot.send_message(
            chat_id=TELEGRAM_CHAT_ID,
            text="PersianCheetah_Scalper_Bybit initialized for BTC, ETH, XRP (1m, Paper Trading, Futures)"
        )
    except Exception as e:
        logger.error(f"{bcolors.FAIL}Fatal error in PersianCheetah_Scalper_Bybit: {e}")
        await telegram_bot.send_message(
            chat_id=TELEGRAM_CHAT_ID,
            text=f"PersianCheetah_Scalper_Bybit error: {e}"
        )

if __name__ == "__main__":
    asyncio.run(main())