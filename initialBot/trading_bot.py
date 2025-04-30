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
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# بارگذاری متغیرهای محیطی
load_dotenv("../.env")
API_KEY = os.getenv('BYBIT_TESTNET_API_KEY')
API_SECRET = os.getenv('BYBIT_TESTNET_API_SECRET')

def get_utc_timestamp():
    utc_now = datetime.datetime.now(datetime.timezone.utc)
    return int(utc_now.timestamp() * 1000)

class TradingBot:
    def __init__(self, symbol, timeframe, indicators, higher_timeframe=None, leverage=5, risk_percent=0.01):
        self.symbol = symbol  # فرمت: BTC/USDT:USDT
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

        # تنظیم بازار Linear Futures
        self.exchange.load_markets()
        if self.symbol not in self.exchange.markets:
            logger.error(f"سمبل {self.symbol} در بازار موجود نیست")
            raise ValueError(f"سمبل {self.symbol} پشتیبانی نمی‌شود")

        # تنظیم لوریج
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
        if df_higher is None or df_higher.empty:
            return 'Neutral'
        indicators_higher = self.calculate_indicators(df_higher)
        macd = indicators_higher.get('MACD')
        macd_signal = indicators_higher.get('MACD_Signal')
        ema20 = indicators_higher.get('EMA20')
        ema50 = indicators_higher.get('EMA50')
        if macd is None or macd_signal is None or ema20 is None or ema50 is None:
            return 'Neutral'
        macd = macd.iloc[-1]
        macd_signal = macd_signal.iloc[-1]
        ema20 = ema20.iloc[-1]
        ema50 = ema50.iloc[-1]
        if macd > macd_signal and ema20 > ema50:
            return 'Long'
        elif macd < macd_signal and ema20 < ema50:
            return 'Short'
        return 'Neutral'

    def calculate_position_size(self, balance, price, stop_loss_percent=0.02):
        risk_amount = balance * self.risk_percent
        stop_loss_distance = price * stop_loss_percent
        if stop_loss_distance == 0:
            logger.error("فاصله استاپ لاس صفر است، نمی‌توان سایز پوزیشن را محاسبه کرد")
            return 0
        return risk_amount / stop_loss_distance

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

                # چک کردن پوزیشن باز
                positions = self.exchange.fetch_positions([self.symbol], params={'category': 'linear'})
                open_position = None
                for pos in positions:
                    if pos['symbol'] == self.symbol and pos['contracts'] > 0:
                        open_position = pos
                        break

                # مدیریت پوزیشن باز (بستن با شرط RSI)
                if open_position and 'RSI' in self.indicators:
                    rsi = indicators_data.get('RSI')
                    if rsi is not None:
                        rsi = rsi.iloc[-1]
                        if (rsi <= 50 and open_position['side'] == 'sell') or (rsi >= 50 and open_position['side'] == 'buy'):
                            self.close_position(open_position)
                            sleep(60)
                            continue

                # فقط اگه پوزیشن باز نداریم، پوزیشن جدید باز می‌کنیم
                if open_position:
                    logger.info(f"پوزیشن باز وجود دارد: {open_position}. پوزیشن جدید باز نمی‌شود.")
                    sleep(60)
                    continue

                # تولید سیگنال
                signal = None
                higher_signal = self.check_higher_timeframe()

                # استراتژی برای تایم‌فریم 5 دقیقه (RSI, Bollinger, Volume)
                if 'RSI' in self.indicators and 'Bollinger' in self.indicators and 'Volume' in self.indicators:
                    rsi = indicators_data.get('RSI')
                    bb_upper = indicators_data.get('BB_Upper')
                    bb_lower = indicators_data.get('BB_Lower')
                    volume = indicators_data.get('Volume')
                    volume_ma = indicators_data.get('Volume_MA')
                    if any(x is None for x in [rsi, bb_upper, bb_lower, volume, volume_ma]):
                        logger.warning(f"اندیکاتورهای RSI/Bollinger/Volume برای {self.symbol} محاسبه نشدند")
                        sleep(60)
                        continue
                    rsi = rsi.iloc[-1]
                    bb_upper = bb_upper.iloc[-1]
                    bb_lower = bb_lower.iloc[-1]
                    volume = volume.iloc[-1]
                    volume_ma = volume_ma.iloc[-1]

                    if (rsi < 30 and price < bb_lower and volume > volume_ma and
                        (higher_signal == 'Long' or higher_signal == 'Neutral')):
                        signal = 'Long'
                    elif (rsi > 70 and price > bb_upper and volume > volume_ma and
                          (higher_signal == 'Short' or higher_signal == 'Neutral')):
                        signal = 'Short'

                # استراتژی برای تایم‌فریم 15 دقیقه (MACD, EMA)
                elif 'MACD' in self.indicators and 'EMA' in self.indicators:
                    macd = indicators_data.get('MACD')
                    macd_signal = indicators_data.get('MACD_Signal')
                    ema20 = indicators_data.get('EMA20')
                    ema50 = indicators_data.get('EMA50')
                    if any(x is None for x in [macd, macd_signal, ema20, ema50]):
                        logger.warning(f"اندیکاتورهای MACD/EMA برای {self.symbol} محاسبه نشدند")
                        sleep(60)
                        continue
                    macd = macd.iloc[-1]
                    macd_signal = macd_signal.iloc[-1]
                    ema20 = ema20.iloc[-1]
                    ema50 = ema50.iloc[-1]

                    if macd > macd_signal and ema20 > ema50:
                        signal = 'Long'
                    elif macd < macd_signal and ema20 < ema50:
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
                        order_details = self.exchange.fetch_order(order['id'], self.symbol, params={'category': 'linear'})
                        logger.info(f"پوزیشن {signal} باز شد - Quantity: {quantity:.4f}, Order: {order_details}")
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
        indicators=['RSI', 'Bollinger', 'Volume'],
        higher_timeframe='15m'
    )

    bot2 = manager.add_bot(
        symbol='BTC/USDT:USDT',
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