import pandas as pd
import ta
import logging
from datetime import datetime

# تنظیم لاگ
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('backtest_log_SMA_ADX_Ichimoku_1m.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class BacktestBot:
    def __init__(self, initial_balance=500, leverage=3, risk_percent=0.2, fee_rate=0.0006):
        self.initial_balance = initial_balance
        self.balance = initial_balance
        self.leverage = leverage
        self.risk_percent = risk_percent
        self.fee_rate = fee_rate
        self.btc_held = 0
        self.trades = []
        self.position = None
        self.trailing_stop = 0.0
        self.highest_price = 0.0
        self.lowest_price = float('inf')

        # لود داده‌ها (تایم‌فریم ۱ دقیقه)
        self.df_1m = pd.read_csv('./BTCUSDT_1m_historical.csv')
        self.df_15m = pd.read_csv('./BTCUSDT_15m_historical.csv')
        self.df_1h = pd.read_csv('./BTCUSDT_1h_historical.csv')

        # محاسبه HODL
        self.hodl_btc = initial_balance / self.df_1m['close'].iloc[0]
        self.hodl_value = 0

    def calculate_indicators(self, df, timeframe='1m'):
        indicators_data = {}
        # SMA 10 و SMA 30
        if len(df) >= 30:
            indicators_data['SMA10'] = ta.trend.SMAIndicator(df['close'], window=10).sma_indicator()
            indicators_data['SMA30'] = ta.trend.SMAIndicator(df['close'], window=30).sma_indicator()
        else:
            indicators_data['SMA10'] = pd.Series([float('nan')] * len(df))
            indicators_data['SMA30'] = pd.Series([float('nan')] * len(df))

        # EMA 50 و EMA 200
        if len(df) >= 200:
            indicators_data['EMA50'] = ta.trend.EMAIndicator(df['close'], window=50).ema_indicator()
            indicators_data['EMA200'] = ta.trend.EMAIndicator(df['close'], window=200).ema_indicator()
        else:
            indicators_data['EMA50'] = pd.Series([float('nan')] * len(df))
            indicators_data['EMA200'] = pd.Series([float('nan')] * len(df))

        # ATR
        if len(df) >= 14:
            indicators_data['ATR'] = ta.volatility.AverageTrueRange(df['high'], df['low'], df['close'], window=14).average_true_range()
        else:
            indicators_data['ATR'] = pd.Series([float('nan')] * len(df))

        # ADX و +DI/-DI
        if len(df) >= 14:
            adx_indicator = ta.trend.ADXIndicator(df['high'], df['low'], df['close'], window=14)
            indicators_data['ADX'] = adx_indicator.adx()
            indicators_data['Plus_DI'] = adx_indicator.adx_pos()
            indicators_data['Minus_DI'] = adx_indicator.adx_neg()
        else:
            indicators_data['ADX'] = pd.Series([float('nan')] * len(df))
            indicators_data['Plus_DI'] = pd.Series([float('nan')] * len(df))
            indicators_data['Minus_DI'] = pd.Series([float('nan')] * len(df))

        # Ichimoku Cloud
        if len(df) >= 52:
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

        # میانگین حجم 20 کندل
        if len(df) >= 20:
            indicators_data['Volume_MA20'] = df['volume'].rolling(window=20).mean()
        else:
            indicators_data['Volume_MA20'] = pd.Series([float('nan')] * len(df))

        # RSI
        if len(df) >= 14:
            indicators_data['RSI'] = ta.momentum.RSIIndicator(df['close'], window=14).rsi()
        else:
            indicators_data['RSI'] = pd.Series([float('nan')] * len(df))

        return indicators_data

    def check_higher_timeframe(self, timestamp):
        df_15m = self.df_15m[self.df_15m['timestamp'] <= timestamp].tail(200)
        df_1h = self.df_1h[self.df_1h['timestamp'] <= timestamp].tail(200)

        if len(df_1h) < 52 or len(df_15m) < 200:
            return 'Neutral'

        indicators_1h = self.calculate_indicators(df_1h, timeframe='1h')
        tenkan_sen = indicators_1h['Tenkan_sen'].iloc[-1]
        kijun_sen = indicators_1h['Kijun_sen'].iloc[-1]
        senkou_span_a = indicators_1h['Senkou_Span_A'].iloc[-1]
        senkou_span_b = indicators_1h['Senkou_Span_B'].iloc[-1]
        chikou_span = indicators_1h['Chikou_Span'].iloc[-1]
        close = df_1h['close'].iloc[-1]
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

        indicators_15m = self.calculate_indicators(df_15m, timeframe='15m')
        ema50 = indicators_15m['EMA50'].iloc[-1]
        ema200 = indicators_15m['EMA200'].iloc[-1]
        adx = indicators_15m['ADX'].iloc[-1]
        plus_di = indicators_15m['Plus_DI'].iloc[-1]
        minus_di = indicators_15m['Minus_DI'].iloc[-1]
        atr = indicators_15m['ATR'].iloc[-1]

        signal_15m = signal_1h
        if signal_1h == 'Neutral' and not any(pd.isna([adx, ema50, ema200, plus_di, minus_di, atr])):
            if adx > 30 and ema50 > ema200 and plus_di > minus_di:
                signal_15m = 'Long'
            elif adx > 30 and ema50 < ema200 and minus_di > plus_di:
                signal_15m = 'Short'

        return signal_15m

    def run_backtest(self):
        logger.info("Starting backtest...")
        position = None
        entry_price = 0.0
        quantity = 0.0
        trades = 0
        stop_loss = 0.0
        take_profit = 0.0

        for index, row in self.df_1m.iterrows():
            timestamp = row['timestamp']
            current_price = row['close']
            current_volume = row['volume']

            df_1m = self.df_1m[self.df_1m['timestamp'] <= timestamp].tail(200)
            if len(df_1m) < 30:
                continue

            indicators_1m = self.calculate_indicators(df_1m, timeframe='1m')
            sma10_1m = indicators_1m['SMA10'].iloc[-1]
            sma30_1m = indicators_1m['SMA30'].iloc[-1]
            sma10_prev_1m = indicators_1m['SMA10'].iloc[-2] if len(indicators_1m['SMA10']) > 1 else float('nan')
            sma30_prev_1m = indicators_1m['SMA30'].iloc[-2] if len(indicators_1m['SMA30']) > 1 else float('nan')
            atr_1m = indicators_1m['ATR'].iloc[-1]
            adx_1m = indicators_1m['ADX'].iloc[-1]
            rsi_1m = indicators_1m['RSI'].iloc[-1]

            higher_tf_signal = self.check_higher_timeframe(timestamp)

            signal = 'Neutral'
            if (not pd.isna(sma10_1m) and not pd.isna(sma30_1m) and not pd.isna(sma10_prev_1m) and 
                not pd.isna(sma30_prev_1m) and not pd.isna(adx_1m)):
                if (sma10_prev_1m <= sma30_prev_1m and sma10_1m > sma30_1m and 
                    adx_1m > 15 and higher_tf_signal == 'Long'):
                    signal = 'Long'
                elif (sma10_prev_1m >= sma30_prev_1m and sma10_1m < sma30_1m and 
                      adx_1m > 15 and higher_tf_signal == 'Short'):
                    signal = 'Short'

            if position is None and signal != 'Neutral':
                position_size = (self.balance * self.risk_percent) * self.leverage
                quantity = position_size / current_price
                entry_price = current_price
                position = signal
                stop_loss = entry_price - (5 * atr_1m) if signal == 'Long' else entry_price + (5 * atr_1m)
                take_profit = entry_price + (6 * atr_1m) if signal == 'Long' else entry_price - (6 * atr_1m)
                self.highest_price = entry_price if signal == 'Long' else float('inf')
                self.lowest_price = entry_price if signal == 'Short' else 0
                self.trailing_stop = stop_loss
                trades += 1
                logger.info(f"Opened {position} at {entry_price}, Quantity: {quantity:.4f}, Stop Loss: {stop_loss:.2f}, Take Profit: {take_profit:.2f}, Balance: {self.balance:.2f}")
            elif position is not None:
                # به‌روزرسانی Trailing Stop
                if position == 'Long':
                    self.highest_price = max(self.highest_price, current_price)
                    self.trailing_stop = max(self.trailing_stop, self.highest_price - (5 * atr_1m))
                elif position == 'Short':
                    self.lowest_price = min(self.lowest_price, current_price)
                    self.trailing_stop = min(self.trailing_stop, self.lowest_price + (5 * atr_1m))

                # محاسبه سود فعلی
                current_profit = 0.0
                if position == 'Long':
                    current_profit = ((current_price - entry_price) / entry_price) * 100
                elif position == 'Short':
                    current_profit = ((entry_price - current_price) / entry_price) * 100

                exit_position = False
                if position == 'Long' and not pd.isna(rsi_1m) and rsi_1m > 80 and current_profit >= 1.0:
                    exit_position = True
                    logger.info(f"Closing Long due to RSI overbought: {rsi_1m}")
                elif position == 'Short' and not pd.isna(rsi_1m) and rsi_1m < 20 and current_profit >= 1.0:
                    exit_position = True
                    logger.info(f"Closing Short due to RSI oversold: {rsi_1m}")

                if position == 'Long':
                    if (exit_position or current_price <= self.trailing_stop or 
                        current_price >= take_profit or signal == 'Short'):
                        profit = (current_price - entry_price) * quantity * self.leverage - (self.fee_rate * position_size)
                        self.balance += profit
                        logger.info(f"Closed Long at {current_price}, Profit: {profit:.2f}, Fee: {self.fee_rate*position_size:.4f}, Balance: {self.balance:.2f}")
                        position = None
                        trades += 1
                elif position == 'Short':
                    if (exit_position or current_price >= self.trailing_stop or 
                        current_price <= take_profit or signal == 'Long'):
                        profit = (entry_price - current_price) * quantity * self.leverage - (self.fee_rate * position_size)
                        self.balance += profit
                        logger.info(f"Closed Short at {current_price}, Profit: {profit:.2f}, Fee: {self.fee_rate*position_size:.4f}, Balance: {self.balance:.2f}")
                        position = None
                        trades += 1

        initial_price = self.df_1m['close'].iloc[0]
        final_price = self.df_1m['close'].iloc[-1]
        hodl_value = (self.initial_balance / initial_price) * final_price

        logger.info("Backtest completed!")
        logger.info(f"Final Balance (Strategy): {self.balance:.2f} USDT")
        logger.info(f"Final Value (HODL): {hodl_value:.2f} USDT")
        logger.info(f"Number of Trades: {trades}")

if __name__ == "__main__":
    backtest = BacktestBot(initial_balance=500, leverage=3)
    backtest.run_backtest()