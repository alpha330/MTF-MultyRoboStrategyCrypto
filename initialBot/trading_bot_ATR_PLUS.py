import ccxt
import pandas as pd
import ta
import logging
import threading
from time import sleep
from dotenv import load_dotenv
import os
import datetime

# تنظیم لاگ
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('/root/MTF-MultyRoboStrategyCrypto/initialBot/trading_bot_ATR_PLUS.log'),  # ذخیره لاگ‌ها تو فایل
        logging.StreamHandler()  # نمایش لاگ‌ها تو کنسول
    ]
)
logger = logging.getLogger(__name__)

# بارگذاری متغیرهای محیطی
load_dotenv()
API_KEY = os.getenv('BYBIT_TESTNET_API_KEY')
API_SECRET = os.getenv('BYBIT_TESTNET_API_SECRET')

def get_utc_timestamp():
    utc_now = datetime.datetime.now(datetime.timezone.utc)
    return int(utc_now.timestamp() * 1000)

class TradingBot:
    def __init__(self, symbol, timeframe, indicators, higher_timeframe=None, leverage=5, risk_percent=0.01):
        self.symbol = symbol
        self.timeframe = timeframe
        self.indicators = indicators
        self.higher_timeframe = higher_timeframe
        self.leverage = leverage
        self.risk_percent = risk_percent
        self.running = False
        self.exchange = ccxt.bybit({
            'apiKey': API_KEY,
            'secret': API_SECRET,
            'enableRateLimit': True,
        })
        self.exchange.set_sandbox_mode(True)
        self.exchange.nonce = get_utc_timestamp

        self.exchange.load_markets()
        if self.symbol not in self.exchange.markets:
            logger.error(f"سمبل {self.symbol} در بازار موجود نیست")
            raise ValueError(f"سمبل {self.symbol} پشتیبانی نمی‌شود")

        self._set_leverage()

    def _set_leverage(self):
        try:
            position_info = self.exchange.fetch_positions([self.symbol], params={'category': 'linear'})
            current_leverage = None
            for pos in position_info:
                if pos['symbol'] == self.symbol:
                    current_leverage = pos.get('leverage', None)
                    break
            logger.info(f"لوریج فعلی برای {self.symbol}: {current_leverage}")
            if current_leverage != self.leverage:
                response = self.exchange.set_leverage(self.leverage, self.symbol, params={'category': 'linear', 'recv_window': 60000})
                logger.info(f"لوریج {self.leverage}x برای {self.symbol} تنظیم شد: {response}")
            else:
                logger.info(f"لوریج {self.leverage}x برای {self.symbol} قبلاً تنظیم شده است.")
        except Exception as e:
            logger.error(f"خطا در تنظیم لوریج: {e}")

    def fetch_ohlcv(self, timeframe):
        for _ in range(3):
            try:
                ohlcv = self.exchange.fetch_ohlcv(self.symbol, timeframe, limit=200)
                df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
                logger.info(f"داده‌های OHLCV برای {self.symbol} در {timeframe} گرفته شد - تعداد کندل‌ها: {len(df)}")
                if len(df) < 50:
                    logger.warning(f"تعداد کندل‌ها ({len(df)}) برای {self.symbol} در {timeframe} کافی نیست")
                    return None
                return df
            except Exception as e:
                logger.error(f"خطا در گرفتن داده‌ها برای {self.symbol} در {timeframe}: {str(e)}")
                sleep(5)
        logger.error(f"ناتوانی در گرفتن داده‌ها برای {self.symbol} پس از ۳ تلاش")
        return None

    def calculate_indicators(self, df):
        indicators_data = {}
        for indicator in self.indicators:
            if indicator == 'RSI':
                indicators_data['RSI'] = ta.momentum.RSIIndicator(df['close'], window=14).rsi()
            elif indicator == 'Stochastic':
                stoch = ta.momentum.StochasticOscillator(df['high'], df['low'], df['close'], window=14, smooth_window=3)
                indicators_data['Stoch_K'] = stoch.stoch()
                indicators_data['Stoch_D'] = stoch.stoch_signal()
            elif indicator == 'ADX':
                adx = ta.trend.ADXIndicator(df['high'], df['low'], df['close'], window=14)
                indicators_data['ADX'] = adx.adx()
                indicators_data['Plus_DI'] = adx.adx_pos()
                indicators_data['Minus_DI'] = adx.adx_neg()
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
        if df_higher is None or df_higher.empty:
            return 'Neutral'
        indicators_higher = self.calculate_indicators(df_higher)
        ema20 = indicators_higher.get('EMA20')
        ema50 = indicators_higher.get('EMA50')
        adx = indicators_higher.get('ADX')
        plus_di = indicators_higher.get('Plus_DI')
        minus_di = indicators_higher.get('Minus_DI')
        if any(x is None for x in [ema20, ema50, adx, plus_di, minus_di]):
            return 'Neutral'
        ema20 = ema20.iloc[-1]
        ema50 = ema50.iloc[-1]
        adx = adx.iloc[-1]
        plus_di = plus_di.iloc[-1]
        minus_di = minus_di.iloc[-1]
        if adx > 25 and ema20 > ema50 and plus_di > minus_di:
            return 'Long'
        elif adx > 25 and ema20 < ema50 and minus_di > plus_di:
            return 'Short'
        return 'Neutral'

    def calculate_position_size(self, balance, price, stop_loss_percent=0.02):
        risk_amount = balance * self.risk_percent
        stop_loss_distance = price * stop_loss_percent
        if stop_loss_distance == 0:
            logger.error("فاصله استاپ لاس صفر است، نمی‌توان سایز پوزیشن را محاسبه کرد")
            return 0
        return risk_amount / stop_loss_distance

    def get_open_position(self):
        try:
            positions = self.exchange.fetch_positions([self.symbol], params={'category': 'linear'})
            for pos in positions:
                if pos['symbol'] == self.symbol and pos['contracts'] > 0:
                    return pos
            return None
        except Exception as e:
            logger.error(f"خطا در گرفتن پوزیشن‌ها: {e}")
            return None

    def close_position(self, position):
        try:
            quantity = position['contracts']
            side = 'buy' if position['side'] == 'sell' else 'sell'
            order = self.exchange.create_market_order(self.symbol, side, quantity, params={'category': 'linear', 'reduceOnly': True})
            logger.info(f"پوزیشن بسته شد: {order}")
        except Exception as e:
            logger.error(f"خطا در بستن پوزیشن: {e}")

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
                price = df['close'].iloc[-1]

                open_position = self.get_open_position()

                if open_position and 'RSI' in self.indicators and 'Stochastic' in self.indicators:
                    rsi = indicators_data.get('RSI')
                    stoch_k = indicators_data.get('Stoch_K')
                    stoch_d = indicators_data.get('Stoch_D')
                    if any(x is None for x in [rsi, stoch_k, stoch_d]):
                        logger.warning("اندیکاتورهای RSI/Stochastic محاسبه نشدند")
                        sleep(60)
                        continue
                    rsi = rsi.iloc[-1]
                    stoch_k = stoch_k.iloc[-1]
                    stoch_d = stoch_d.iloc[-1]
                    logger.info(f"RSI فعلی: {rsi:.2f}, Stochastic K: {stoch_k:.2f}, D: {stoch_d:.2f}")
                    if ((rsi <= 50 or (stoch_k < 50 and stoch_d < 50)) and open_position['side'] == 'sell') or \
                       ((rsi >= 50 or (stoch_k > 50 and stoch_d > 50)) and open_position['side'] == 'buy'):
                        self.close_position(open_position)
                        sleep(60)
                        continue

                if open_position:
                    logger.info(f"پوزیشن باز وجود دارد: {open_position}. پوزیشن جدید باز نمی‌شود.")
                    sleep(60)
                    continue

                signal = None
                higher_signal = self.check_higher_timeframe()

                if 'RSI' in self.indicators and 'Stochastic' in self.indicators and 'Volume' in self.indicators:
                    rsi = indicators_data.get('RSI')
                    stoch_k = indicators_data.get('Stoch_K')
                    stoch_d = indicators_data.get('Stoch_D')
                    volume = indicators_data.get('Volume')
                    volume_ma = indicators_data.get('Volume_MA')
                    if any(x is None for x in [rsi, stoch_k, stoch_d, volume, volume_ma]):
                        logger.warning(f"اندیکاتورهای RSI/Stochastic/Volume برای {self.symbol} محاسبه نشدند")
                        sleep(60)
                        continue
                    rsi = rsi.iloc[-1]
                    stoch_k = stoch_k.iloc[-1]
                    stoch_d = stoch_d.iloc[-1]
                    volume = volume.iloc[-1]
                    volume_ma = volume_ma.iloc[-1]

                    if (rsi < 30 and stoch_k < 20 and stoch_d < 20 and stoch_k > stoch_d and volume > volume_ma and
                        (higher_signal == 'Long' or higher_signal == 'Neutral')):
                        signal = 'Long'
                    elif (rsi > 70 and stoch_k > 80 and stoch_d > 80 and stoch_k < stoch_d and volume > volume_ma and
                          (higher_signal == 'Short' or higher_signal == 'Neutral')):
                        signal = 'Short'

                elif 'ADX' in self.indicators and 'EMA' in self.indicators:
                    adx = indicators_data.get('ADX')
                    plus_di = indicators_data.get('Plus_DI')
                    minus_di = indicators_data.get('Minus_DI')
                    ema20 = indicators_data.get('EMA20')
                    ema50 = indicators_data.get('EMA50')
                    if any(x is None for x in [adx, plus_di, minus_di, ema20, ema50]):
                        logger.warning(f"اندیکاتورهای ADX/EMA برای {self.symbol} محاسبه نشدند")
                        sleep(60)
                        continue
                    adx = adx.iloc[-1]
                    plus_di = plus_di.iloc[-1]
                    minus_di = minus_di.iloc[-1]
                    ema20 = ema20.iloc[-1]
                    ema50 = ema50.iloc[-1]

                    if adx > 25 and plus_di > minus_di and ema20 > ema50:
                        signal = 'Long'
                    elif adx > 25 and minus_di > plus_di and ema20 < ema50:
                        signal = 'Short'

                else:
                    logger.warning(f"اندیکاتورهای تعریف‌شده برای {self.symbol} پشتیبانی نمی‌شوند")
                    sleep(60)
                    continue

                if signal:
                    balance = self.exchange.fetch_balance(params={'recv_window': 60000, 'type': 'linear'})['USDT']['free']
                    logger.info(f"بالانس فعلی قبل از معامله: {balance:.2f} USDT")
                    quantity = self.calculate_position_size(balance, price)
                    if quantity == 0:
                        logger.warning("سایز پوزیشن صفر است، پوزیشن باز نمی‌شود")
                        sleep(60)
                        continue
                    stop_loss = price * (1 - 0.02) if signal == 'Long' else price * (1 + 0.02)
                    take_profit = price * (1 + 0.04) if signal == 'Long' else price * (1 - 0.04)
                    logger.info(f"سیگنال {signal} در {self.symbol} - Price: {price:.2f}, Quantity: {quantity:.4f}, Stop Loss: {stop_loss:.2f}, Take Profit: {take_profit:.2f}")

                    try:
                        params = {
                            'category': 'linear',
                            'stopLoss': stop_loss,
                            'takeProfit': take_profit,
                        }
                        if signal == 'Long':
                            order = self.exchange.create_market_buy_order(self.symbol, quantity, params)
                        else:
                            order = self.exchange.create_market_sell_order(self.symbol, quantity, params)
                        sleep(2)
                        open_orders = self.exchange.fetch_open_orders(self.symbol, params={'category': 'linear'})
                        order_details = None
                        for o in open_orders:
                            if o['id'] == order['id']:
                                order_details = o
                                break
                        if order_details:
                            logger.info(f"پوزیشن {signal} باز شد - Quantity: {quantity:.4f}, Order: {order_details}")
                        else:
                            logger.warning(f"جزئیات سفارش {order['id']} پیدا نشد. سفارش ممکن است بسته شده باشد.")
                        position = self.get_open_position()
                        if position:
                            logger.info(f"پوزیشن فعال: {position}")
                        else:
                            logger.warning("پوزیشن باز شده پیدا نشد!")
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
        symbol='BTC/USDT:USDT',
        timeframe='5m',
        indicators=['RSI', 'Stochastic', 'Volume'],
        higher_timeframe='15m'
    )

    bot2 = manager.add_bot(
        symbol='BTC/USDT:USDT',
        timeframe='15m',
        indicators=['ADX', 'EMA']
    )

    manager.start_all()

    try:
        while True:
            sleep(1)
    except KeyboardInterrupt:
        for bot in manager.bots:
            bot.stop()