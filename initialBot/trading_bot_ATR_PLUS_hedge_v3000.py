import ccxt
import pandas as pd
import numpy as np
import logging
import time
import telegram
from telegram.ext import Application, CommandHandler
import asyncio
from datetime import datetime, timezone
from dotenv import load_dotenv
import os

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
    utc_now = datetime.now(timezone.utc)
    return int(utc_now.timestamp() * 1000)

# Logger Setup
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

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('trading_bot_ATR_PLUS_hedge_v3.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Telegram Bot Setup
try:
    telegram_bot = telegram.Bot(token=TELEGRAM_TOKEN)
except Exception as e:
    logger.error(f"{bcolors.FAIL}Error initializing Telegram bot: {e}")
    raise

class TradingBot:
    def __init__(self, symbol, timeframe, exchange, higher_bot=None, risk_percent=0.01):
        self.symbol = symbol
        self.timeframe = timeframe
        self.exchange = exchange
        self.higher_bot = higher_bot
        self.risk_percent = risk_percent
        self.max_positions = 2
        self.min_volume_threshold = 1000 if not exchange.testnet else 0
        self.running = True

    def fetch_ohlcv(self, limit=500):
        try:
            ohlcv = self.exchange.fetch_ohlcv(self.symbol, self.timeframe, limit=limit)
            df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            return df
        except Exception as e:
            logger.error(f"{bcolors.FAIL}Error fetching OHLCV data: {e}")
            return None

    def calculate_indicators(self, df):
        if len(df) < 52:
            logger.warning(f"{bcolors.WARNING}Not enough data for indicators calculation")
            return {}
        
        if self.timeframe == '1h':
            high_9 = df['high'].rolling(window=9).max()
            low_9 = df['low'].rolling(window=9).min()
            high_26 = df['high'].rolling(window=26).max()
            low_26 = df['low'].rolling(window=26).min()
            high_52 = df['high'].rolling(window=52).max()
            low_52 = df['low'].rolling(window=52).min()
            
            chikou_span = df['close'].shift(-26) if len(df) >= 26 else pd.Series([np.nan] * len(df))
            if chikou_span.isna().all():
                logger.warning(f"{bcolors.WARNING}Chikou Span is all NaN")
            
            indicators = {
                'tenkan_sen': (high_9 + low_9) / 2,
                'kijun_sen': (high_26 + low_26) / 2,
                'senkou_span_a': ((high_9 + low_9) / 2 + (high_26 + low_26) / 2) / 2,
                'senkou_span_b': (high_52 + low_52) / 2,
                'chikou_span': chikou_span,
                'close': df['close'],
                'close_26_ago': df['close'].shift(26) if len(df) >= 26 else pd.Series([np.nan] * len(df))
            }
        else:
            rsi = self.calculate_rsi(df['close'], 14)
            stoch_k, stoch_d = self.calculate_stochastic(df, 14, 3, 3)
            volume_ma = df['volume'].rolling(window=20).mean()
            atr = self.calculate_atr(df, 14)
            adx = self.calculate_adx(df, 14) if self.timeframe == '15m' else None
            
            indicators = {
                'rsi': rsi,
                'stoch_k': stoch_k,
                'stoch_d': stoch_d,
                'volume': df['volume'],
                'volume_ma': volume_ma,
                'atr': atr,
                'adx': adx
            }
        
        return indicators

    def calculate_rsi(self, prices, period):
        delta = prices.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        rs = np.where(loss != 0, gain / loss, np.inf)
        rsi = 100 - (100 / (1 + rs))
        return pd.Series(rsi, index=prices.index)

    def calculate_stochastic(self, df, k_period, d_period, slowing):
        low_min = df['low'].rolling(window=k_period).min()
        high_max = df['high'].rolling(window=k_period).max()
        k = 100 * (df['close'] - low_min) / (high_max - low_min)
        k = k.rolling(window=slowing).mean()
        d = k.rolling(window=d_period).mean()
        return k, d

    def calculate_atr(self, df, period):
        high_low = df['high'] - df['low']
        high_close = abs(df['high'] - df['close'].shift())
        low_close = abs(df['low'] - df['close'].shift())
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        return tr.rolling(window=period).mean()

    def calculate_adx(self, df, period):
        plus_dm = df['high'].diff()
        minus_dm = df['low'].diff()
        plus_dm[plus_dm < 0] = 0
        minus_dm[minus_dm > 0] = 0
        tr = self.calculate_atr(df, period)
        plus_di = 100 * plus_dm.rolling(window=period).mean() / tr
        minus_di = 100 * abs(minus_dm).rolling(window=period).mean() / tr
        dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di)
        adx = dx.rolling(window=period).mean()
        return adx

    def generate_signal(self, indicators):
        signal = 'Neutral'
        
        if self.timeframe == '1h':
            tenkan_sen = indicators.get('tenkan_sen').iloc[-1]
            kijun_sen = indicators.get('kijun_sen').iloc[-1]
            senkou_span_a = indicators.get('senkou_span_a').iloc[-1]
            senkou_span_b = indicators.get('senkou_span_b').iloc[-1]
            chikou_span = indicators.get('chikou_span').iloc[-1]
            close = indicators.get('close').iloc[-1]
            close_26_ago = indicators.get('close_26_ago').iloc[-1]
            
            if (not np.isnan(chikou_span) and not np.isnan(close_26_ago) and
                close > senkou_span_a and close > senkou_span_b and
                tenkan_sen > kijun_sen and chikou_span > close_26_ago):
                signal = 'Long'
            elif (not np.isnan(chikou_span) and not np.isnan(close_26_ago) and
                  close < senkou_span_a and close < senkou_span_b and
                  tenkan_sen < kijun_sen and chikou_span < close_26_ago):
                signal = 'Short'
        
        elif self.timeframe == '15m':
            higher_signal = self.higher_bot.generate_signal(self.higher_bot.calculate_indicators(self.higher_bot.fetch_ohlcv())) if self.higher_bot else 'Neutral'
            adx = indicators.get('adx').iloc[-1] if indicators.get('adx') is not None else 0
            
            if adx > 25 and higher_signal in ['Long', 'Neutral']:
                signal = 'Long'
            elif adx > 25 and higher_signal in ['Short', 'Neutral']:
                signal = 'Short'
        
        else:  # 5m
            if not indicators:
                logger.warning(f"{bcolors.WARNING}No indicators available")
                return 'Neutral'
                
            rsi = indicators.get('rsi').iloc[-1]
            stoch_k = indicators.get('stoch_k').iloc[-1]
            stoch_d = indicators.get('stoch_d').iloc[-1]
            volume = indicators.get('volume').iloc[-1]
            volume_ma = indicators.get('volume_ma').iloc[-1]
            higher_signal = self.higher_bot.generate_signal(self.higher_bot.calculate_indicators(self.higher_bot.fetch_ohlcv())) if self.higher_bot else 'Neutral'
            
            if not self.exchange.testnet and volume < self.min_volume_threshold:
                logger.info(f"{bcolors.WARNING}Volume {volume:.2f} below threshold {self.min_volume_threshold}")
                return 'Neutral'
            elif self.exchange.testnet:
                logger.info(f"{bcolors.OKCYAN}Volume threshold ignored in testnet mode")
            
            volume_condition = volume > volume_ma if not self.exchange.testnet else True
            
            logger.info(f"{bcolors.OKCYAN}Current Indicators - RSI: {rsi:.2f}, "
                        f"Stochastic K: {stoch_k:.2f}, D: {stoch_d:.2f}, "
                        f"Volume: {volume:.2f}, Volume MA: {volume_ma:.2f}, "
                        f"Higher Signal: {higher_signal}")
            
            long_conditions = {
                'rsi < 65': rsi < 65,
                'stoch_k < 75': stoch_k < 75,
                'stoch_d < 75': stoch_d < 75,
                'volume > volume_ma': volume_condition,
                'higher_signal': higher_signal in ['Long', 'Neutral'] if not self.exchange.testnet else True
            }
            
            short_conditions = {
                'rsi > 60': rsi > 60,
                'stoch_k > 65': stoch_k > 65,
                'stoch_d > 60': stoch_d > 60,
                'volume > volume_ma': volume_condition,
                'higher_signal': higher_signal in ['Short', 'Neutral'] if not self.exchange.testnet else True
            }
            
            if all(long_conditions.values()):
                signal = 'Long'
                logger.info(f"{bcolors.OKGREEN}Long signal generated")
            elif all(short_conditions.values()):
                signal = 'Short'
                logger.info(f"{bcolors.OKGREEN}Short signal generated")
            else:
                failed_long = [k for k, v in long_conditions.items() if not v]
                failed_short = [k for k, v in short_conditions.items() if not v]
                logger.info(f"{bcolors.WARNING}No signal generated. "
                           f"Failed Long conditions: {failed_long}, "
                           f"Failed Short conditions: {failed_short}")
        
        return signal

    async def open_position(self, signal, price, atr):
        if signal == 'Neutral':
            return
        
        try:
            balance = self.exchange.fetch_balance()['total']['USDT']
            logger.info(f"{bcolors.OKBLUE}Current Balance: {balance:.2f} USDT")
            
            long_pos, short_pos = self.get_open_position()
            long_count = 1 if long_pos and long_pos['contracts'] > 0 else 0
            short_count = 1 if short_pos and short_pos['contracts'] > 0 else 0
            
            if (signal == 'Long' and long_count >= self.max_positions) or \
               (signal == 'Short' and short_count >= self.max_positions):
                logger.warning(f"{bcolors.WARNING}Max positions reached for {signal}")
                return
            
            risk_amount = balance * self.risk_percent
            stop_loss_distance = atr * 2
            position_size = risk_amount / stop_loss_distance
            quantity = (position_size / price) * self.exchange.fetch_ticker(self.symbol)['last']
            quantity = self.exchange.amount_to_precision(self.symbol, quantity)
            
            if float(quantity) < 0.001:
                logger.warning(f"{bcolors.WARNING}Quantity {quantity} too small")
                return
            
            stop_loss = price * (1 - 2 * atr / price) if signal == 'Long' else price * (1 + 2 * atr / price)
            take_profit = price * (1 + 3 * atr / price) if signal == 'Long' else price * (1 - 3 * atr / price)
            trailing_stop = price * (1 - 1.5 * atr / price) if signal == 'Long' else price * (1 + 1.5 * atr / price)
            
            params = {
                'stopLoss': stop_loss,
                'takeProfit': take_profit,
                'trailingStop': trailing_stop
            }
            
            side = 'buy' if signal == 'Long' else 'sell'
            order = self.exchange.create_market_order(self.symbol, side, quantity, params=params)
            
            logger.info(f"{bcolors.OKBLUE}Signal {signal} on {self.symbol} - Price: {price:.2f}, "
                       f"Quantity: {quantity:.4f}, Stop Loss: {stop_loss:.2f}, Take Profit: {take_profit:.2f}")
            
            await telegram_bot.send_message(
                chat_id=TELEGRAM_CHAT_ID,
                text=f"New {signal} position opened on {self.symbol}\n"
                     f"Price: {price:.2f}\nQuantity: {quantity:.4f}\n"
                     f"Stop Loss: {stop_loss:.2f}\nTake Profit: {take_profit:.2f}"
            )
            
            for _ in range(3):
                time.sleep(20)
                long_pos, short_pos = self.get_open_position()
                if (signal == 'Long' and long_pos and long_pos['contracts'] > 0) or \
                   (signal == 'Short' and short_pos and short_pos['contracts'] > 0):
                    return
                logger.warning(f"{bcolors.WARNING}Opened Position Not Found after 20 seconds, retrying...")
            
            logger.error(f"{bcolors.FAIL}Position Still Not Found!")
            
        except Exception as e:
            logger.error(f"{bcolors.FAIL}Error opening position: {e}")

    def get_open_position(self):
        try:
            positions = self.exchange.fetch_positions([self.symbol])
            long_position = None
            short_position = None
            
            for pos in positions:
                if pos['contracts'] > 0:
                    if pos['side'] == 'long':
                        long_position = pos
                    elif pos['side'] == 'short':
                        short_position = pos
            
            logger.info(f"{bcolors.OKCYAN}Fetched Positions: {positions}")
            return long_position, short_position
        except Exception as e:
            logger.error(f"{bcolors.FAIL}Error fetching positions: {e}")
            return None, None

    async def get_status(self):
        df = self.fetch_ohlcv()
        if df is None:
            return "Error fetching data"
        
        indicators = self.calculate_indicators(df)
        long_pos, short_pos = self.get_open_position()
        
        status = f"Bot Status ({self.timeframe}):\n"
        status += f"Symbol: {self.symbol}\n"
        status += f"Running: {self.running}\n"
        if self.timeframe == '5m':
            status += f"RSI: {indicators.get('rsi', pd.Series([0])).iloc[-1]:.2f}\n"
            status += f"Stochastic K: {indicators.get('stoch_k', pd.Series([0])).iloc[-1]:.2f}\n"
            status += f"Stochastic D: {indicators.get('stoch_d', pd.Series([0])).iloc[-1]:.2f}\n"
            status += f"Volume: {indicators.get('volume', pd.Series([0])).iloc[-1]:.2f}\n"
        status += f"Open Long Position: {'Yes' if long_pos and long_pos['contracts'] > 0 else 'No'}\n"
        status += f"Open Short Position: {'Yes' if short_pos and short_pos['contracts'] > 0 else 'No'}\n"
        return status

# Telegram command handlers
async def start(update, context):
    global bot1
    bot1.running = True
    await update.message.reply_text("Trading bot started")
    logger.info(f"{bcolors.OKGREEN}Bot started via Telegram")

async def stop(update, context):
    global bot1
    bot1.running = False
    await update.message.reply_text("Trading bot stopped")
    logger.info(f"{bcolors.WARNING}Bot stopped via Telegram")

async def status(update, context):
    global bot1
    status = await bot1.get_status()
    await update.message.reply_text(status)
    logger.info(f"{bcolors.OKCYAN}Status requested via Telegram")

async def run_bot():
    global bot1
    exchange = ccxt.bybit({
        'apiKey': API_KEY,
        'secret': API_SECRET,
        'enableRateLimit': True,
        'testnet': True
    })
    exchange.set_sandbox_mode(True)
    exchange.nonce = get_utc_timestamp
    
    symbol = 'BTC/USDT:USDT'
    
    bot3 = TradingBot(symbol, '1h', exchange)
    bot2 = TradingBot(symbol, '15m', exchange, higher_bot=bot3)
    bot1 = TradingBot(symbol, '5m', exchange, higher_bot=bot2)
    
    logger.info(f"{bcolors.OKBLUE}ALGOBOT {symbol} IN TIME FRAME 1h started")
    logger.info(f"{bcolors.OKBLUE}ALGOBOT {symbol} IN TIME FRAME 15m started")
    logger.info(f"{bcolors.OKBLUE}ALGOBOT {symbol} IN TIME FRAME 5m started")
    
    while True:
        if not bot1.running:
            await asyncio.sleep(10)
            continue
        try:
            df = bot1.fetch_ohlcv()
            if df is not None:
                indicators = bot1.calculate_indicators(df)
                signal = bot1.generate_signal(indicators)
                if signal != 'Neutral':
                    price = df['close'].iloc[-1]
                    atr = indicators.get('atr').iloc[-1]
                    await bot1.open_position(signal, price, atr)
            
            await asyncio.sleep(30)
        except Exception as e:
            logger.error(f"{bcolors.FAIL}Error in main loop: {e}")
            await asyncio.sleep(60)

async def main():
    global telegram_bot
    # Send test message to verify Telegram setup
    try:
        await telegram_bot.send_message(chat_id=TELEGRAM_CHAT_ID, text="Trading bot initialized")
    except Exception as e:
        logger.error(f"{bcolors.FAIL}Error sending test message: {e}")
    
    # Start Telegram bot
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("stop", stop))
    application.add_handler(CommandHandler("status", status))
    
    # Run both Telegram bot and trading bot in the same event loop
    await asyncio.gather(
        application.run_polling(),
        run_bot()
    )

if __name__ == "__main__":
    asyncio.run(main())