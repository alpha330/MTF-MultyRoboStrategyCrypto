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
import uuid

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
        logging.FileHandler('/root/MTF-MultyRoboStrategyCrypto/initialBot/bybit_10Pair_5m_paper_trade.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN_PAPER1M_10')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHANAL_ID')

# Validate environment variables
if not all([TELEGRAM_TOKEN, TELEGRAM_CHAT_ID]):
    raise ValueError("Missing required Telegram environment variables in .env file")

# Telegram Bot Setup
try:
    telegram_bot = telegram.Bot(token=TELEGRAM_TOKEN)
except Exception as e:
    logger.error(f"{bcolors.FAIL}Error initializing Telegram bot: {e}")
    raise

class Wallet:
    def __init__(self, initial_balance=100):
        self.balance = initial_balance
        self.positions = []  # All open positions across all pairs
        self.trade_history = []  # All closed positions
        self.fee_rate = 0.00075  # 0.075% taker fee
        self.max_margin_ratio = 0.6  # Use up to 60% of balance for margin

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
        return used_margin + margin_required <= max_allowed_margin

class TradingBot:
    def __init__(self, symbol, timeframe='5m', leverage=5, risk_percent=0.02, wallet=None):
        self.symbol = symbol
        self.timeframe = timeframe
        self.leverage = leverage
        self.risk_percent = risk_percent
        self.running = False
        self.last_signal = 'Neutral'
        self.exchange = ccxt.bybit({'enableRateLimit': True})  # Mainnet for OHLCV
        self.exchange.load_markets()
        if self.symbol not in self.exchange.markets:
            logger.error(f"{bcolors.FAIL}Symbol {self.symbol} Not Exists")
            raise ValueError(f"Symbol {self.symbol} Not Exists")
        self.wallet = wallet
        self._set_leverage()

    def _set_leverage(self):
        logger.info(f"{bcolors.OKCYAN}LEVERAGE {self.leverage}x FOR {self.symbol} SET FOR PAPER TRADING (MAINNET)")

    def fetch_ohlcv(self):
        for _ in range(3):
            try:
                ohlcv = self.exchange.fetch_ohlcv(self.symbol, self.timeframe, limit=400)
                df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
                logger.info(f"{bcolors.OKGREEN}FOR OHLCV DATA {self.symbol} IN {self.timeframe} CANDLES ARE GET: {len(df)} (MAINNET)")
                if len(df) < 50:
                    logger.warning(f"{bcolors.WARNING}CANDLES ({len(df)}) FOR {self.symbol} IN {self.timeframe} NOT ENOUGH")
                    return None
                return df
            except Exception as e:
                logger.error(f"{bcolors.FAIL}EXCEPTION DURING GETTING DATA CANDLE {self.symbol} IN {self.timeframe}: {str(e)}")
                time.sleep(5)
        logger.error(f"{bcolors.FAIL}CANNOT GET DATA CANDLES {self.symbol} AFTER 3 TIMES TRY")
        return None

    def calculate_indicators(self, df):
        indicators_data = {}
        indicators_data['EMA9'] = ta.trend.EMAIndicator(df['close'], window=9).ema_indicator()
        indicators_data['VWAP'] = ta.volume.VolumeWeightedAveragePrice(df['high'], df['low'], df['close'], df['volume'], window=14).volume_weighted_average_price()
        indicators_data['RSI'] = ta.momentum.RSIIndicator(df['close'], window=14).rsi()
        indicators_data['Volume'] = df['volume']
        indicators_data['Volume_MA'] = ta.trend.SMAIndicator(df['volume'], window=20).sma_indicator()
        indicators_data['Swing_High'] = df['high'].rolling(window=5, center=True).max()
        indicators_data['Swing_Low'] = df['low'].rolling(window=5, center=True).min()
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
        if not self.wallet.can_open_position(position_value, self.leverage):
            logger.warning(f"{bcolors.WARNING}Cannot open position on {self.symbol}: Exceeds 60% balance margin limit")
            return 0
        try:
            quantity = float(self.exchange.amount_to_precision(self.symbol, quantity))
        except:
            quantity = round(quantity, 4)
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
            # Calculate profit/loss
            if side == 'Long':
                pnl = (exit_price - entry_price) * quantity
            else:  # Short
                pnl = (entry_price - exit_price) * quantity
            # Apply fees
            entry_fee = entry_price * quantity * self.wallet.fee_rate
            exit_fee = exit_price * quantity * self.wallet.fee_rate
            total_pnl = pnl - entry_fee - exit_fee
            # Update balance
            self.wallet.balance += total_pnl
            # Determine Win/Loss
            status = 'Win' if total_pnl > 0 else 'Loss'
            # Store in trade history
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
            # Update or remove position
            if close_percentage < 1.0:
                position['quantity'] *= (1 - close_percentage)
                position['stop_loss'] = position['trailing_stop']
            else:
                self.wallet.positions.remove(position)
            logger.info(f"{bcolors.OKGREEN}POSITION CLOSED: {side}, Symbol: {self.symbol}, Quantity: {quantity:.4f}, Entry: {entry_price:.4f}, Exit: {exit_price:.4f}, PnL: {total_pnl:.2f}, Reason: {reason}, Status: {status}")
            logger.info(f"{bcolors.OKBLUE}New Balance: {self.wallet.balance:.2f} USDT, Used Margin: {self.wallet.get_used_margin():.2f} USDT")
            # Send Telegram notification
            try:
                telegram_bot.send_message(
                    chat_id=TELEGRAM_CHAT_ID,
                    text=f"Position closed on {self.symbol} (Paper Trading, Mainnet)\n"
                         f"Side: {side}\nQuantity: {quantity:.4f}\n"
                         f"Entry Price: {entry_price:.4f}\nExit Price: {exit_price:.4f}\n"
                         f"PnL: {total_pnl:.2f} USDT ({status})\nReason: {reason}\n"
                         f"New Balance: {self.wallet.balance:.2f} USDT"
                )
            except Exception as telegram_error:
                logger.error(f"{bcolors.FAIL}Error sending Telegram message: {telegram_error}")
        except Exception as e:
            logger.error(f"{bcolors.FAIL}EXCEPTION DURING CLOSE POSITION on {self.symbol}: {e}")

    def check_tp_sl_trailing(self, current_price, ema9):
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
                    pos['trailing_stop'] = max(stop_loss, ema9)
                    continue
                elif pos.get('first_target_hit', False):
                    pos['trailing_stop'] = max(pos['trailing_stop'], ema9)
                    if current_price <= pos['trailing_stop']:
                        self.close_position(pos, pos['trailing_stop'], reason='Trailing Stop Hit')
            else:  # Short
                if current_price >= stop_loss:
                    self.close_position(pos, stop_loss, reason='Stop Loss Hit')
                    continue
                elif current_price <= take_profit and not pos.get('first_target_hit', False):
                    self.close_position(pos, take_profit, reason='Take Profit Hit (1:1)', close_percentage=0.5)
                    pos['first_target_hit'] = True
                    pos['trailing_stop'] = min(stop_loss, ema9)
                    continue
                elif pos.get('first_target_hit', False):
                    pos['trailing_stop'] = min(pos['trailing_stop'], ema9)
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

    def run(self):
        self.running = True
        logger.info(f"{bcolors.OKBLUE}ALGOBOT {self.symbol} IN TIME FRAME {self.timeframe} HAS BEEN STARTED (PAPER TRADING, MAINNET)")
        while self.running:
            try:
                df = self.fetch_ohlcv()
                if df is None or df.empty:
                    logger.warning(f"{bcolors.WARNING}DATA OHLCV FOR {self.symbol} IN {self.timeframe} NOT VALID")
                    time.sleep(60)
                    continue

                indicators_data = self.calculate_indicators(df)
                price = df['close'].iloc[-1]

                # Check stop loss, take profit, and trailing stop
                ema9 = indicators_data['EMA9'].iloc[-1]
                self.check_tp_sl_trailing(price, ema9)

                # Get indicators
                vwap = indicators_data['VWAP'].iloc[-1]
                rsi = indicators_data['RSI'].iloc[-1]
                volume = indicators_data['Volume'].iloc[-1]
                volume_ma = indicators_data['Volume_MA'].iloc[-1]
                swing_low = indicators_data['Swing_Low'].iloc[-1]
                swing_high = indicators_data['Swing_High'].iloc[-1]

                logger.info(f"{bcolors.OKCYAN}Indicators for {self.symbol} - EMA9: {ema9:.4f}, VWAP: {vwap:.4f}, RSI: {rsi:.2f}, Volume: {volume:.2f}, Volume MA: {volume_ma:.2f}, Swing Low: {swing_low:.4f}, Swing High: {swing_high:.4f}")

                long_position = self.get_open_position(side='buy')
                short_position = self.get_open_position(side='sell')

                # Check for closing positions
                if long_position and ema9 < vwap:
                    self.close_position(long_position, price, reason='EMA9 below VWAP')
                    time.sleep(60)
                    continue
                if short_position and ema9 > vwap:
                    self.close_position(short_position, price, reason='EMA9 above VWAP')
                    time.sleep(60)
                    continue

                signal = None
                # Long signal
                if (ema9 > vwap and
                    abs(price - swing_low) / price < 0.01 and
                    20 <= rsi <= 60 and
                    volume > volume_ma):
                    signal = 'Long'
                # Short signal
                elif (ema9 < vwap and
                      abs(price - swing_high) / price < 0.01 and
                      40 <= rsi <= 80 and
                      volume > volume_ma):
                    signal = 'Short'

                if signal:
                    logger.info(f"{bcolors.OKBLUE}Current Balance Before Opening Positions on {self.symbol}: {self.wallet.balance:.2f} USDT, Used Margin: {self.wallet.get_used_margin():.2f} USDT")
                    # Calculate stop loss and take profit (1%)
                    stop_loss = price * (1 - 0.01) if signal == 'Long' else price * (1 + 0.01)
                    take_profit = price * (1 + 0.01) if signal == 'Long' else price * (1 - 0.01)
                    quantity = self.calculate_position_size(price, stop_loss)
                    if quantity == 0:
                        logger.warning(f"{bcolors.WARNING}Cannot Open Position on {self.symbol}: Zero Quantity or Margin Limit")
                        time.sleep(60)
                        continue

                    # Round to precision
                    stop_loss = round(stop_loss, 4)
                    take_profit = round(take_profit, 4)

                    logger.info(f"{bcolors.OKBLUE}Signal {signal} on {self.symbol} - Price: {price:.4f}, Quantity: {quantity:.4f}, Stop Loss: {stop_loss:.4f}, Take Profit: {take_profit:.4f}")

                    try:
                        # Simulate opening position
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

                        # Send Telegram notification
                        try:
                            telegram_bot.send_message(
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
                            telegram_bot.send_message(
                                chat_id=TELEGRAM_CHAT_ID,
                                text=f"Failed to open {signal} position on {self.symbol} (Paper Trading)\nError: {e}"
                            )
                        except Exception as telegram_error:
                            logger.error(f"{bcolors.FAIL}Error sending Telegram error message: {telegram_error}")

                time.sleep(60)

            except Exception as e:
                logger.error(f"{bcolors.FAIL}General Exception In ALGOBOT {self.symbol}: {e}")
                time.sleep(60)

    def stop(self):
        self.running = False
        logger.info(f"{bcolors.OKCYAN}ALGOBOT {self.symbol} STOPPED (PAPER TRADING, MAINNET)")
        try:
            telegram_bot.send_message(
                chat_id=TELEGRAM_CHAT_ID,
                text=f"Trading bot for {self.symbol} ({self.timeframe}) stopped (Paper Trading, Mainnet)\n"
                     f"Final Balance: {self.wallet.balance:.2f} USDT"
            )
        except Exception as telegram_error:
            logger.error(f"{bcolors.FAIL}Error sending Telegram message: {telegram_error}")

    def get_status(self):
        df = self.fetch_ohlcv()
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
        status += f"EMA9: {indicators.get('EMA9', pd.Series([0])).iloc[-1]:.4f}\n"
        status += f"VWAP: {indicators.get('VWAP', pd.Series([0])).iloc[-1]:.4f}\n"
        status += f"RSI: {indicators.get('RSI', pd.Series([0])).iloc[-1]:.2f}\n"
        status += f"Volume: {indicators.get('Volume', pd.Series([0])).iloc[-1]:.2f}\n"
        status += f"Volume MA: {indicators.get('Volume_MA', pd.Series([0])).iloc[-1]:.2f}\n"
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

    def start_all(self):
        for bot in self.bots:
            threading.Thread(target=bot.run, daemon=True).start()

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
        bot.stop()
    await update.message.reply_text("Trading bots stopped (Paper Trading, Mainnet)")
    logger.info(f"{bcolors.WARNING}Bots stopped via Telegram (Paper Trading, Mainnet)")

async def status(update, context):
    global manager
    status = ""
    for bot in manager.bots:
        status += bot.get_status() + "\n\n"
    await update.message.reply_text(status)
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

def main():
    global manager
    manager = BotManager()

    # List of trading pairs
    trading_pairs = [
        'XRP/USDT:USDT',
        'BTC/USDT:USDT',
        'ETH/USDT:USDT',
        'BNB/USDT:USDT',
        'ADA/USDT:USDT',
        'SOL/USDT:USDT',
        'DOGE/USDT:USDT',
        'DOT/USDT:USDT',
        'MATIC/USDT:USDT',
        'LINK/USDT:USDT'
    ]

    # Add bots for each trading pair
    for symbol in trading_pairs:
        try:
            manager.add_bot(symbol=symbol, timeframe='5m')
            logger.info(f"{bcolors.OKGREEN}Bot added for {symbol}")
        except Exception as e:
            logger.error(f"{bcolors.FAIL}Failed to add bot for {symbol}: {e}")

    manager.start_all()

    # Send test message
    try:
        telegram_bot.send_message(
            chat_id=TELEGRAM_CHAT_ID,
            text="Trading bots initialized for multiple pairs (Paper Trading, Mainnet)"
        )
    except Exception as e:
        logger.error(f"{bcolors.FAIL}Error sending test message: {e}")

    # Run Telegram bot
    asyncio.run(run_telegram_bot())

if __name__ == "__main__":
    main()