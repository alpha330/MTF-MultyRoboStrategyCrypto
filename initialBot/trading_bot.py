import ccxt
import pandas as pd
import ta
import logging
import threading
from time import sleep
from dotenv import load_dotenv
import os
import datetime

# بارگذاری متغیرهای محیطی
load_dotenv()
API_KEY = os.getenv('BYBIT_TESTNET_API_KEY')
API_SECRET = os.getenv('BYBIT_TESTNET_API_SECRET')

# تنظیم لاگ
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def get_utc_timestamp():
    utc_now = datetime.datetime.now(datetime.timezone.utc)
    return int(utc_now.timestamp() * 1000)

class TradingBot:
    def __init__(self, symbol, timeframe, indicators, higher_timeframe=None, leverage=5, risk_percent=0.01):
        self.exchange = ccxt.bybit({
            'apiKey': API_KEY,
            'secret': API_SECRET,
            'enableRateLimit': True,
            'test': True,
            'recv_window': 20000
        })
        self.exchange.nonce = get_utc_timestamp
        self.symbol = symbol.replace('/', '')  # تبدیل BTC/USDT به BTCUSDT
        self.timeframe = timeframe
        self.indicators = indicators
        self.higher_timeframe = higher_timeframe
        self.leverage = leverage
        self.risk_percent = risk_percent
        self.running = False

        # تنظیم بازار Linear Futures
        self.exchange.load_markets()
        if self.symbol not in self.exchange.markets:
            logger.error(f"سمبل {self.symbol} در بازار موجود نیست")
            raise ValueError(f"سمبل {self.symbol} پشتیبانی نمی‌شود")

        # تنظیم لوریج
        try:
            self.exchange.set_leverage(self.leverage, self.symbol, params={'category': 'linear'})
            logger.info(f"لوریج {self.leverage}x برای {self.symbol} تنظیم شد")
        except Exception as e:
            logger.error(f"خطا در تنظیم لوریج: {e}")

    def fetch_ohlcv(self, timeframe):
        for _ in range(3):
            try:
                ohlcv = self.exchange.fetch_ohlcv(self.symbol, timeframe, limit=100)
                df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
                logger.info(f"داده‌های OHLCV برای {self.symbol} در {timeframe} گرفته شد")
                return df
            except Exception as e:
                logger.error(f"خطا در گرفتن داده‌ها برای {self.symbol} در {timeframe}: {str(e)}")
                sleep(5)
        logger.error(f"ناتوانی در گرفتن داده‌ها برای {self.symbol} پس از ۳ تلاش")
        return None
    
    def run(self):
        self.running = True
        logger.info(f"ربات {self.symbol} در تایم‌فریم {self.timeframe} شروع شد")
        while self.running:
            try:
                df = self.fetch_ohlcv(self.timeframe)
                if df is None or df.empty:
                    logger.warning(f"داده‌های OHLCV برای {self.symbol} در {self.timeframe} نامعتبر است")
                    sleep(60)
                    continue
                
                indicators_data = self.calculate_indicators(df)
                rsi = indicators_data.get('RSI')
                if rsi is None:
                    logger.warning(f"RSI برای {self.symbol} محاسبه نشد")
                    sleep(60)
                    continue
                rsi = rsi.iloc[-1]
                price = df['close'].iloc[-1]
                bb_upper = indicators_data.get('BB_Upper')
                bb_lower = indicators_data.get('BB_Lower')
                volume = indicators_data.get('Volume')
                volume_ma = indicators_data.get('Volume_MA')
                if bb_upper is None or bb_lower is None or volume is None or volume_ma is None:
                    logger.warning(f"اندیکاتورهای Bollinger یا Volume برای {self.symbol} محاسبه نشدند")
                    sleep(60)
                    continue
                bb_upper = bb_upper.iloc[-1]
                bb_lower = bb_lower.iloc[-1]
                volume = volume.iloc[-1]
                volume_ma = volume_ma.iloc[-1]
    
                higher_signal = self.check_higher_timeframe()
    
                signal = None
                if (rsi < 30 and price < bb_lower and volume > volume_ma and
                    (higher_signal == 'Long' or higher_signal == 'Neutral')):
                    signal = 'Long'
                elif (rsi > 70 and price > bb_upper and volume > volume_ma and
                      (higher_signal == 'Short' or higher_signal == 'Neutral')):
                    signal = 'Short'
    
                if signal:
                    balance = self.exchange.fetch_balance()['USDT']['free']
                    quantity = self.calculate_position_size(balance, price)
                    stop_loss = price * (1 - 0.02) if signal == 'Long' else price * (1 + 0.02)
                    take_profit = price * (1 + 0.04) if signal == 'Long' else price * (1 - 0.04)
                    logger.info(f"سیگنال {signal} در {self.symbol} - RSI: {rsi:.2f}, Price: {price:.2f}, Quantity: {quantity:.4f}")
    
                    try:
                        if signal == 'Long':
                            self.exchange.create_market_buy_order(self.symbol, quantity, {
                                'stopLossPrice': stop_loss,
                                'takeProfitPrice': take_profit,
                                'type': 'future'
                            })
                        else:
                            self.exchange.create_market_sell_order(self.symbol, quantity, {
                                'stopLossPrice': stop_loss,
                                'takeProfitPrice': take_profit,
                                'type': 'future'
                            })
                        logger.info(f"پوزیشن {signal} باز شد - Quantity: {quantity:.4f}")
                    except Exception as e:
                        logger.error(f"خطا در باز کردن پوزیشن: {e}")
    
                sleep(60)
    
            except Exception as e:
                logger.error(f"خطا در ربات {self.symbol}: {e}")
                sleep(60)

    def calculate_indicators(self, df):
        indicators_data = {}
        for indicator in self.indicators:
            if indicator == 'RSI':
                indicators_data['RSI'] = ta.momentum.RSIIndicator(df['close'], window=14).rsi()
            elif indicator == 'MACD':
                macd = ta.trend.MACD(df['close'])
                indicators_data['MACD'] = macd.macd()
                indicators_data['MACD_Signal'] = macd.macd_signal()
            elif indicator == 'Bollinger':
                bb = ta.volatility.BollingerBands(df['close'], window=20)
                indicators_data['BB_Upper'] = bb.bollinger_hband()
                indicators_data['BB_Lower'] = bb.bollinger_lband()
            elif indicator == 'EMA':
                indicators_data['EMA20'] = ta.trend.EMAIndicator(df['close'], window=20).ema_indicator()
                indicators_data['EMA50'] = ta.trend.EMAIndicator(df['close'], window=50).ema_indicator()
            elif indicator == 'Volume':
                indicators_data['Volume'] = df['volume']
                indicators_data['Volume_MA'] = ta.trend.SMAIndicator(df['volume'], window=20).sma_indicator()
        return indicators_data

    def check_higher_timeframe(self):
        if not self.higher_timeframe:
            return 'Neutral'
        df_higher = self.fetch_ohlcv(self.higher_timeframe)
        if df_higher is None:
            return 'Neutral'
        indicators_higher = self.calculate_indicators(df_higher)
        macd = indicators_higher.get('MACD').iloc[-1]
        macd_signal = indicators_higher.get('MACD_Signal').iloc[-1]
        ema20 = indicators_higher.get('EMA20').iloc[-1]
        ema50 = indicators_higher.get('EMA50').iloc[-1]
        if macd > macd_signal and ema20 > ema50:
            return 'Long'
        elif macd < macd_signal and ema20 < ema50:
            return 'Short'
        return 'Neutral'

    def calculate_position_size(self, balance, price, stop_loss_percent=0.02):
        risk_amount = balance * self.risk_percent
        stop_loss_distance = price * stop_loss_percent
        return risk_amount / stop_loss_distance

    def run(self):
        self.running = True
        logger.info(f"ربات {self.symbol} در تایم‌فریم {self.timeframe} شروع شد")
        while self.running:
            try:
                df = self.fetch_ohlcv(self.timeframe)
                if df is None:
                    sleep(60)
                    continue

                indicators_data = self.calculate_indicators(df)
                rsi = indicators_data.get('RSI').iloc[-1]
                price = df['close'].iloc[-1]
                bb_upper = indicators_data.get('BB_Upper').iloc[-1]
                bb_lower = indicators_data.get('BB_Lower').iloc[-1]
                volume = indicators_data.get('Volume').iloc[-1]
                volume_ma = indicators_data.get('Volume_MA').iloc[-1]

                higher_signal = self.check_higher_timeframe()

                signal = None
                if (rsi < 30 and price < bb_lower and volume > volume_ma and
                    (higher_signal == 'Long' or higher_signal == 'Neutral')):
                    signal = 'Long'
                elif (rsi > 70 and price > bb_upper and volume > volume_ma and
                      (higher_signal == 'Short' or higher_signal == 'Neutral')):
                    signal = 'Short'

                if signal:
                    balance = self.exchange.fetch_balance()['USDT']['free']
                    quantity = self.calculate_position_size(balance, price)
                    stop_loss = price * (1 - 0.02) if signal == 'Long' else price * (1 + 0.02)
                    take_profit = price * (1 + 0.04) if signal == 'Long' else price * (1 - 0.04)
                    logger.info(f"سیگنال {signal} در {self.symbol} - RSI: {rsi:.2f}, Price: {price:.2f}, Quantity: {quantity:.4f}")

                    try:
                        if signal == 'Long':
                            self.exchange.create_market_buy_order(self.symbol, quantity, {
                                'stopLossPrice': stop_loss,
                                'takeProfitPrice': take_profit,
                                'type': 'future'
                            })
                        else:
                            self.exchange.create_market_sell_order(self.symbol, quantity, {
                                'stopLossPrice': stop_loss,
                                'takeProfitPrice': take_profit,
                                'type': 'future'
                            })
                        logger.info(f"پوزیشن {signal} باز شد - Quantity: {quantity:.4f}")
                    except Exception as e:
                        logger.error(f"خطا در باز کردن پوزیشن: {e}")

                sleep(60)

            except Exception as e:
                logger.error(f"خطا در ربات {self.symbol}: {e}")
                sleep(60)

    def stop(self):
        self.running = False
        logger.info(f"ربات {self.symbol} متوقف شد")

class BotManager:
    def __init__(self):
        self.bots = []

    def add_bot(self, symbol, timeframe, indicators, higher_timeframe=None):
        bot = TradingBot(symbol, timeframe, indicators, higher_timeframe)
        self.bots.append(bot)
        return bot

    def start_all(self):
        for bot in self.bots:
            threading.Thread(target=bot.run, daemon=True).start()

if __name__ == "__main__":
    manager = BotManager()

    bot1 = manager.add_bot(
        symbol='BTC/USDT',
        timeframe='5m',
        indicators=['RSI', 'Bollinger', 'Volume'],
        higher_timeframe='15m'
    )

    bot2 = manager.add_bot(
        symbol='BTC/USDT',
        timeframe='15m',
        indicators=['MACD', 'EMA']
    )

    manager.start_all()

    try:
        while True:
            sleep(1)
    except KeyboardInterrupt:
        for bot in manager.bots:
            bot.stop()