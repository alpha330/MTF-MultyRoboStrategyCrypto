import pandas as pd
import ta
import logging
from datetime import datetime

# تنظیم لاگ
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('backtest_log.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class BacktestBot:
    def __init__(self, initial_balance=500, leverage=5, risk_percent=0.01, fee_rate=0.0006):
        self.initial_balance = initial_balance
        self.balance = initial_balance
        self.leverage = leverage
        self.risk_percent = risk_percent
        self.fee_rate = fee_rate  # کارمزد ترید (Bybit معمولاً ۰.۰۶٪)
        self.btc_held = 0  # برای HODL
        self.trades = []
        self.position = None  # پوزیشن فعلی (None, 'Long', 'Short')

        # لود داده‌ها
        self.df_5m = pd.read_csv('BTCUSDT_5m_historical.csv')
        self.df_15m = pd.read_csv('BTCUSDT_15m_historical.csv')
        self.df_1h = pd.read_csv('BTCUSDT_1h_historical.csv')

        # محاسبه HODL
        self.hodl_btc = initial_balance / self.df_5m['close'].iloc[0]  # مقدار بیت‌کوین خریده‌شده با ۵۰۰ دلار
        self.hodl_value = 0  # ارزش HODL در آخر

    def calculate_indicators(self, df, indicators):
        indicators_data = {}
        for indicator in indicators:
            if indicator == 'RSI':
                if len(df) >= 14:
                    indicators_data['RSI'] = ta.momentum.RSIIndicator(df['close'], window=14).rsi()
                else:
                    indicators_data['RSI'] = pd.Series([float('nan')] * len(df))
            elif indicator == 'Stochastic':
                if len(df) >= 14:
                    stoch = ta.momentum.StochasticOscillator(df['high'], df['low'], df['close'], window=14, smooth_window=3)
                    indicators_data['Stoch_K'] = stoch.stoch()
                    indicators_data['Stoch_D'] = stoch.stoch_signal()
                else:
                    indicators_data['Stoch_K'] = pd.Series([float('nan')] * len(df))
                    indicators_data['Stoch_D'] = pd.Series([float('nan')] * len(df))
            elif indicator == 'ADX':
                if len(df) >= 14:
                    adx = ta.trend.ADXIndicator(df['high'], df['low'], df['close'], window=14)
                    indicators_data['ADX'] = adx.adx()
                    indicators_data['Plus_DI'] = adx.adx_pos()
                    indicators_data['Minus_DI'] = adx.adx_neg()
                else:
                    indicators_data['ADX'] = pd.Series([float('nan')] * len(df))
                    indicators_data['Plus_DI'] = pd.Series([float('nan')] * len(df))
                    indicators_data['Minus_DI'] = pd.Series([float('nan')] * len(df))
            elif indicator == 'EMA':
                if len(df) >= 50:  # بزرگ‌ترین پنجره (EMA50)
                    indicators_data['EMA20'] = ta.trend.EMAIndicator(df['close'], window=20).ema_indicator()
                    indicators_data['EMA50'] = ta.trend.EMAIndicator(df['close'], window=50).ema_indicator()
                else:
                    indicators_data['EMA20'] = pd.Series([float('nan')] * len(df))
                    indicators_data['EMA50'] = pd.Series([float('nan')] * len(df))
            elif indicator == 'Ichimoku':
                if len(df) >= 52:  # بزرگ‌ترین پنجره (Senkou Span B)
                    ichimoku = ta.trend.IchimokuIndicator(df['high'], df['low'], window1=9, window2=26, window3=52)
                    indicators_data['Tenkan_sen'] = ichimoku.ichimoku_conversion_line()
                    indicators_data['Kijun_sen'] = ichimoku.ichimoku_base_line()
                    indicators_data['Senkou_Span_A'] = ichimoku.ichimoku_a()
                    indicators_data['Senkou_Span_B'] = ichimoku.ichimoku_b()
                    indicators_data['Chikou_Span'] = df['close'].shift(-26)
                else:
                    indicators_data['Tenkan_sen'] = pd.Series([float('nan')] * len(df))
                    indicators_data['Kijun_sen'] = pd.Series([float('nan')] * len(df))
                    indicators_data['Senkou_Span_A'] = pd.Series([float('nan')] * len(df))
                    indicators_data['Senkou_Span_B'] = pd.Series([float('nan')] * len(df))
                    indicators_data['Chikou_Span'] = pd.Series([float('nan')] * len(df))
            elif indicator == 'ATR':
                if len(df) >= 14:
                    indicators_data['ATR'] = ta.volatility.AverageTrueRange(df['high'], df['low'], df['close'], window=14).average_true_range()
                else:
                    indicators_data['ATR'] = pd.Series([float('nan')] * len(df))
        return indicators_data

    def check_higher_timeframe(self, timestamp):
        # فیلتر داده‌های 15m و 1h بر اساس زمان فعلی
        df_15m = self.df_15m[self.df_15m['timestamp'] <= timestamp].tail(200)
        df_1h = self.df_1h[self.df_1h['timestamp'] <= timestamp].tail(200)

        # اگه دیتا خالی بود یا تعداد ردیف‌ها کافی نبود، سیگنال پیش‌فرض برگردون
        if len(df_1h) == 0 or len(df_15m) == 0 or len(df_15m) < 50 or len(df_1h) < 50:
            return 'Neutral'

        # Bot3 (1h) - Ichimoku
        indicators_1h = self.calculate_indicators(df_1h, ['Ichimoku'])
        tenkan_sen = indicators_1h.get('Tenkan_sen').iloc[-1] if len(df_1h) >= 9 else float('nan')
        kijun_sen = indicators_1h.get('Kijun_sen').iloc[-1] if len(df_1h) >= 26 else float('nan')
        senkou_span_a = indicators_1h.get('Senkou_Span_A').iloc[-1] if len(df_1h) >= 26 else float('nan')
        senkou_span_b = indicators_1h.get('Senkou_Span_B').iloc[-1] if len(df_1h) >= 52 else float('nan')
        chikou_span = indicators_1h.get('Chikou_Span').iloc[-1] if len(df_1h) >= 26 else float('nan')
        close = df_1h['close'].iloc[-1] if len(df_1h) > 0 else float('nan')
        close_26_ago = df_1h['close'].iloc[-27] if len(df_1h) > 27 else close

        signal_1h = 'Neutral'
        if not any(pd.isna([close, senkou_span_a, senkou_span_b, tenkan_sen, kijun_sen, chikou_span, close_26_ago])):
            if (close > senkou_span_a and close > senkou_span_b and
                tenkan_sen > kijun_sen and
                chikou_span > close_26_ago and
                senkou_span_a > senkou_span_b):
                signal_1h = 'Long'
            elif (close < senkou_span_a and close < senkou_span_b and
                  tenkan_sen < kijun_sen and
                  chikou_span < close_26_ago and
                  senkou_span_a < senkou_span_b):
                signal_1h = 'Short'

        # Bot2 (15m) - ADX و EMA
        indicators_15m = self.calculate_indicators(df_15m, ['ADX', 'EMA'])
        ema20 = indicators_15m.get('EMA20').iloc[-1] if len(df_15m) >= 20 else float('nan')
        ema50 = indicators_15m.get('EMA50').iloc[-1] if len(df_15m) >= 50 else float('nan')
        adx = indicators_15m.get('ADX').iloc[-1] if len(df_15m) >= 14 else float('nan')
        plus_di = indicators_15m.get('Plus_DI').iloc[-1] if len(df_15m) >= 14 else float('nan')
        minus_di = indicators_15m.get('Minus_DI').iloc[-1] if len(df_15m) >= 14 else float('nan')

        signal_15m = signal_1h  # ابتدا از سیگنال 1h استفاده می‌کنیم
        if signal_1h == 'Neutral' and not any(pd.isna([adx, ema20, ema50, plus_di, minus_di])):
            if adx > 20 and ema20 > ema50 and plus_di > minus_di:
                signal_15m = 'Long'
            elif adx > 20 and ema20 < ema50 and minus_di > plus_di:
                signal_15m = 'Short'

        return signal_15m

    def calculate_position_size(self, price):
        risk_amount = self.balance * self.risk_percent
        stop_loss_distance = price * 0.02  # فرض ۲٪ فاصله استاپ لاس
        return (risk_amount / stop_loss_distance) * self.leverage

    def run_backtest(self):
        logger.info("Starting backtest...")
        for index, row in self.df_5m.iterrows():
            timestamp = row['timestamp']
            price = row['close']

            # فیلتر داده‌ها با حداقل 200 ردیف
            df_5m_window = self.df_5m[self.df_5m['timestamp'] <= timestamp].tail(200)
            if len(df_5m_window) < 200:
                df_5m_window = self.df_5m.iloc[:200]  # اگه کمتر از 200 تا باشه، از دیتای اولیه استفاده کن

            # محاسبه اندیکاتورها
            indicators = self.calculate_indicators(df_5m_window, ['RSI', 'Stochastic', 'ATR'])

            rsi = indicators.get('RSI').iloc[-1] if len(df_5m_window) >= 14 else float('nan')
            stoch_k = indicators.get('Stoch_K').iloc[-1] if len(df_5m_window) >= 14 else float('nan')
            stoch_d = indicators.get('Stoch_D').iloc[-1] if len(df_5m_window) >= 14 else float('nan')
            atr = indicators.get('ATR').iloc[-1] if len(df_5m_window) >= 14 else float('nan')

            # بستن پوزیشن
            if self.position:
                if self.position['side'] == 'Long' and (rsi >= 50 or (stoch_k > 50 and stoch_d > 50)):
                    profit = (price - self.position['entry_price']) * self.position['quantity']
                    fee = (price + self.position['entry_price']) * self.position['quantity'] * self.fee_rate
                    self.balance += profit - fee
                    self.trades.append({
                        'type': 'Close Long',
                        'entry_price': self.position['entry_price'],
                        'exit_price': price,
                        'quantity': self.position['quantity'],
                        'profit': profit,
                        'fee': fee,
                        'balance': self.balance,
                        'timestamp': timestamp
                    })
                    logger.info(f"Closed Long at {price}, Profit: {profit:.2f}, Fee: {fee:.2f}, Balance: {self.balance:.2f}")
                    self.position = None
                elif self.position['side'] == 'Short' and (rsi <= 50 or (stoch_k < 50 and stoch_d < 50)):
                    profit = (self.position['entry_price'] - price) * self.position['quantity']
                    fee = (price + self.position['entry_price']) * self.position['quantity'] * self.fee_rate
                    self.balance += profit - fee
                    self.trades.append({
                        'type': 'Close Short',
                        'entry_price': self.position['entry_price'],
                        'exit_price': price,
                        'quantity': self.position['quantity'],
                        'profit': profit,
                        'fee': fee,
                        'balance': self.balance,
                        'timestamp': timestamp
                    })
                    logger.info(f"Closed Short at {price}, Profit: {profit:.2f}, Fee: {fee:.2f}, Balance: {self.balance:.2f}")
                    self.position = None

            # باز کردن پوزیشن
            if not self.position and not any(pd.isna([rsi, stoch_k, stoch_d, atr])):
                higher_signal = self.check_higher_timeframe(timestamp)
                signal = None
                if (rsi < 40 and stoch_k < 30 and stoch_d < 30 and
                    (higher_signal == 'Long' or higher_signal == 'Neutral')):
                    signal = 'Long'
                elif (rsi > 60 and stoch_k > 70 and stoch_d > 70 and
                      (higher_signal == 'Short' or higher_signal == 'Neutral')):
                    signal = 'Short'

                if signal:
                    quantity = self.calculate_position_size(price)
                    self.position = {
                        'side': signal,
                        'entry_price': price,
                        'quantity': quantity
                    }
                    self.trades.append({
                        'type': f'Open {signal}',
                        'entry_price': price,
                        'quantity': quantity,
                        'balance': self.balance,
                        'timestamp': timestamp
                    })
                    logger.info(f"Opened {signal} at {price}, Quantity: {quantity:.4f}, Balance: {self.balance:.2f}")

        # محاسبه HODL
        final_price = self.df_5m['close'].iloc[-1]
        self.hodl_value = self.hodl_btc * final_price

        logger.info(f"Backtest completed!")
        logger.info(f"Final Balance (Strategy): {self.balance:.2f} USDT")
        logger.info(f"Final Value (HODL): {self.hodl_value:.2f} USDT")
        logger.info(f"Number of Trades: {len(self.trades)}")

if __name__ == "__main__":
    backtest = BacktestBot(initial_balance=500)
    backtest.run_backtest()