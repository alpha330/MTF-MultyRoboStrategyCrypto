import ccxt
import pandas as pd
import ta
import logging
import threading
from time import sleep
from dotenv import load_dotenv
import os
import datetime

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
        logging.FileHandler('/root/MTF-MultyRoboStrategyCrypto/initialBot/trading_bot_ATR_PLUS.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Load environment variables
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
            logger.error(f"{bcolors.FAIL}Symbol {self.symbol} Not Exists")
            raise ValueError(f"{bcolors.FAIL}Symbol {self.symbol} Not Exists")

        self._set_leverage()

    def _set_leverage(self):
        try:
            position_info = self.exchange.fetch_positions([self.symbol], params={'category': 'linear'})
            current_leverage = None
            for pos in position_info:
                if pos['symbol'] == self.symbol:
                    current_leverage = pos.get('leverage', None)
                    break
            logger.info(f"CORRENT LEVERAGE FOR {self.symbol}: {current_leverage}")
            if current_leverage != self.leverage:
                response = self.exchange.set_leverage(self.leverage, self.symbol, params={'category': 'linear', 'recv_window': 60000})
                logger.info(f"{bcolors.OKCYAN}LEVERAGE {self.leverage}x FOR {self.symbol} SET: {response}")
            else:
                logger.info(f"{bcolors.OKCYAN}LEVERAGE {self.leverage}x FOR {self.symbol} SET BEFORE")
        except Exception as e:
            logger.error(f"{bcolors.FAIL}EXCEPTION DURING SET LEVERAGE: {e}")

    def fetch_ohlcv(self, timeframe):
        for _ in range(3):
            try:
                ohlcv = self.exchange.fetch_ohlcv(self.symbol, timeframe, limit=200)
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
            elif indicator == 'ATR':
                indicators_data['ATR'] = ta.volatility.AverageTrueRange(df['high'], df['low'], df['close'], window=14).average_true_range()
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
        logger.info(f"{bcolors.OKCYAN}Higher Timeframe Indicators - ADX: {adx:.2f}, +DI: {plus_di:.2f}, -DI: {minus_di:.2f}, EMA20: {ema20:.2f}, EMA50: {ema50:.2f}")
        if adx > 20 and ema20 > ema50 and plus_di > minus_di:
            return 'Long'
        elif adx > 20 and ema20 < ema50 and minus_di > plus_di:
            return 'Short'
        return 'Neutral'

    def calculate_position_size(self, balance, price, stop_loss_percent=0.02):
        risk_amount = balance * self.risk_percent
        stop_loss_distance = price * stop_loss_percent
        if stop_loss_distance == 0:
            logger.error(f"{bcolors.WARNING}Stop Loss distance is zero, cannot calculate position size")
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
            logger.error(f"{bcolors.FAIL}EXCEPTION DURING GETTING DATA POSITIONS: {e}")
            return None

    def close_position(self, position):
        try:
            quantity = position['contracts']
            side = 'buy' if position['side'] == 'sell' else 'sell'
            order = self.exchange.create_market_order(self.symbol, side, quantity, params={'category': 'linear', 'reduceOnly': True})
            logger.info(f"{bcolors.OKGREEN}POSITIONS CLOSED: {order}")
        except Exception as e:
            logger.error(f"{bcolors.FAIL}EXCEPTION DURING CLOSE POSITIONS: {e}")

    def run(self):
        self.running = True
        logger.info(f"{bcolors.OKBLUE}ALGOBOT {self.symbol} IN TIME FRAME {self.timeframe} HAS BEEN STARTED")
        while self.running:
            try:
                df = self.fetch_ohlcv(self.timeframe)
                if df is None or df.empty:
                    logger.warning(f"{bcolors.WARNING}DATA OHLCV FOR {self.symbol} IN {self.timeframe} NOT VALID")
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
                        logger.warning(f"{bcolors.WARNING}INDICATORS RSI/Stochastic NOT CALCULATED")
                        sleep(60)
                        continue
                    rsi = rsi.iloc[-1]
                    stoch_k = stoch_k.iloc[-1]
                    stoch_d = stoch_d.iloc[-1]
                    logger.info(f"{bcolors.UNDERLINE}Current RSI: {rsi:.2f}, Stochastic K: {stoch_k:.2f}, D: {stoch_d:.2f}")
                    if ((rsi <= 50 or (stoch_k < 50 and stoch_d < 50)) and open_position['side'] == 'sell') or \
                       ((rsi >= 50 or (stoch_k > 50 and stoch_d > 50)) and open_position['side'] == 'buy'):
                        self.close_position(open_position)
                        sleep(60)
                        continue

                if open_position:
                    logger.info(f"{bcolors.WARNING}Current Position Exists: {open_position} Cannot Open New Position")
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
                        logger.warning(f"{bcolors.WARNING}Indicators RSI/Stochastic/Volume for {self.symbol} Not Calculated")
                        sleep(60)
                        continue
                    rsi = rsi.iloc[-1]
                    stoch_k = stoch_k.iloc[-1]
                    stoch_d = stoch_d.iloc[-1]
                    volume = volume.iloc[-1]
                    volume_ma = volume_ma.iloc[-1]
                    logger.info(f"{bcolors.OKCYAN}Current Indicators - RSI: {rsi:.2f}, Stochastic K: {stoch_k:.2f}, D: {stoch_d:.2f}, Volume: {volume:.2f}, Volume MA: {volume_ma:.2f}, Higher Signal: {higher_signal}")

                    if (rsi < 40 and stoch_k < 30 and stoch_d < 30 and stoch_k > stoch_d and volume > volume_ma and
                        (higher_signal == 'Long' or higher_signal == 'Neutral')):
                        signal = 'Long'
                    elif (rsi > 60 and stoch_k > 70 and stoch_d > 70 and stoch_k < stoch_d and volume > volume_ma and
                          (higher_signal == 'Short' or higher_signal == 'Neutral')):
                        signal = 'Short'

                elif 'ADX' in self.indicators and 'EMA' in self.indicators:
                    adx = indicators_data.get('ADX')
                    plus_di = indicators_data.get('Plus_DI')
                    minus_di = indicators_data.get('Minus_DI')
                    ema20 = indicators_data.get('EMA20')
                    ema50 = indicators_data.get('EMA50')
                    if any(x is None for x in [adx, plus_di, minus_di, ema20, ema50]):
                        logger.warning(f"{bcolors.WARNING}Indicators ADX/EMA for {self.symbol} Not Calculated")
                        sleep(60)
                        continue
                    adx = adx.iloc[-1]
                    plus_di = plus_di.iloc[-1]
                    minus_di = minus_di.iloc[-1]
                    ema20 = ema20.iloc[-1]
                    ema50 = ema50.iloc[-1]

                    if adx > 20 and plus_di > minus_di and ema20 > ema50:
                        signal = 'Long'
                    elif adx > 20 and minus_di > plus_di and ema20 < ema50:
                        signal = 'Short'

                else:
                    logger.warning(f"{bcolors.WARNING}Assigned Indicators For {self.symbol} Not Supported")
                    sleep(60)
                    continue

                if signal:
                    balance = self.exchange.fetch_balance(params={'recv_window': 60000, 'type': 'linear'})['USDT']['free']
                    logger.info(f"{bcolors.OKBLUE}Current Balance Before Opening Positions: {balance:.2f} USDT")
                    quantity = self.calculate_position_size(balance, price)
                    if quantity == 0:
                        logger.warning(f"{bcolors.WARNING}Cannot Open Positions Because Of Zero Margin")
                        sleep(60)
                        continue
                    atr = indicators_data.get('ATR')
                    if atr is not None:
                        atr = atr.iloc[-1]
                        stop_loss = price * (1 - 2 * atr / price) if signal == 'Long' else price * (1 + 2 * atr / price)
                        take_profit = price * (1 + 4 * atr / price) if signal == 'Long' else price * (1 - 4 * atr / price)
                    else:
                        stop_loss = price * (1 - 0.02) if signal == 'Long' else price * (1 + 0.02)
                        take_profit = price * (1 + 0.04) if signal == 'Long' else price * (1 - 0.04)
                    logger.info(f"Signal {signal} on {self.symbol} - Price: {price:.2f}, Quantity: {quantity:.4f}, Stop Loss: {stop_loss:.2f}, Take Profit: {take_profit:.2f}")

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
                            logger.info(f"{bcolors.OKCYAN}Position {signal} Opened - Quantity: {quantity:.4f}, Order: {order_details}")
                        else:
                            logger.warning(f"{bcolors.WARNING}Order Details {order['id']} Not Found, It May Be Closed")
                        position = self.get_open_position()
                        if position:
                            logger.info(f"{bcolors.OKBLUE}Active Position: {position}")
                        else:
                            logger.warning(f"{bcolors.WARNING}Opened Position Not Found!")
                    except Exception as e:
                        logger.error(f"{bcolors.FAIL}Exception During Opening Position: {e}")

                sleep(60)

            except Exception as e:
                logger.error(f"{bcolors.FAIL}General Exception In ALGOBOT {self.symbol}: {e}")
                sleep(60)

    def stop(self):
        self.running = False
        logger.info(f"{bcolors.OKCYAN}ALGOBOT {self.symbol} STOPPED")

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
        indicators=['RSI', 'Stochastic', 'Volume', 'ATR'],
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