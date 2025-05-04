import pandas as pd
import ta
import logging
import numpy as np
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
        self.equity_history = []  # برای محاسبه معیارهای عملکرد

        # لود داده‌ها و تبدیل تایم‌استمپ‌ها
        try:
            self.df_1m = pd.read_csv('./BTCUSDT_1m_historical.csv')
            self.df_15m = pd.read_csv('./BTCUSDT_15m_historical.csv')
            self.df_1h = pd.read_csv('./BTCUSDT_1h_historical.csv')

            # تبدیل تایم‌استمپ به datetime
            self.df_1m['timestamp'] = pd.to_datetime(self.df_1m['timestamp'], errors='coerce')
            self.df_15m['timestamp'] = pd.to_datetime(self.df_15m['timestamp'], errors='coerce')
            self.df_1h['timestamp'] = pd.to_datetime(self.df_1h['timestamp'], errors='coerce')

            # حذف ردیف‌هایی که تایم‌استمپ نادرست دارن
            self.df_1m = self.df_1m.dropna(subset=['timestamp'])
            self.df_15m = self.df_15m.dropna(subset=['timestamp'])
            self.df_1h = self.df_1h.dropna(subset=['timestamp'])

            logger.info(f"Loaded 1m data: {len(self.df_1m)} rows")
            logger.info(f"Loaded 15m data: {len(self.df_15m)} rows")
            logger.info(f"Loaded 1h data: {len(self.df_1h)} rows")
        except Exception as e:
            logger.error(f"Error loading data: {e}")
            raise

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
            indicators_data['SMA10'] = pd.Series([float('nan')] * len(df), index=df.index)
            indicators_data['SMA30'] = pd.Series([float('nan')] * len(df), index=df.index)

        # EMA 50 و EMA 200
        if len(df) >= 200:
            indicators_data['EMA50'] = ta.trend.EMAIndicator(df['close'], window=50).ema_indicator()
            indicators_data['EMA200'] = ta.trend.EMAIndicator(df['close'], window=200).ema_indicator()
        else:
            indicators_data['EMA50'] = pd.Series([float('nan')] * len(df), index=df.index)
            indicators_data['EMA200'] = pd.Series([float('nan')] * len(df), index=df.index)

        # ATR
        if len(df) >= 14:
            indicators_data['ATR'] = ta.volatility.AverageTrueRange(df['high'], df['low'], df['close'], window=14).average_true_range()
        else:
            indicators_data['ATR'] = pd.Series([float('nan')] * len(df), index=df.index)

        # ADX و +DI/-DI
        if len(df) >= 14:
            adx_indicator = ta.trend.ADXIndicator(df['high'], df['low'], df['close'], window=14)
            indicators_data['ADX'] = adx_indicator.adx()
            indicators_data['Plus_DI'] = adx_indicator.adx_pos()
            indicators_data['Minus_DI'] = adx_indicator.adx_neg()
        else:
            indicators_data['ADX'] = pd.Series([float('nan')] * len(df), index=df.index)
            indicators_data['Plus_DI'] = pd.Series([float('nan')] * len(df), index=df.index)
            indicators_data['Minus_DI'] = pd.Series([float('nan')] * len(df), index=df.index)

        # Ichimoku Cloud
        if len(df) >= 52:
            ichimoku = ta.trend.IchimokuIndicator(df['high'], df['low'], window1=9, window2=26, window3=52)
            indicators_data['Tenkan_sen'] = ichimoku.ichimoku_conversion_line()
            indicators_data['Kijun_sen'] = ichimoku.ichimoku_base_line()
            indicators_data['Senkou_Span_A'] = ichimoku.ichimoku_a()
            indicators_data['Senkou_Span_B'] = ichimoku.ichimoku_b()
            indicators_data['Chikou_Span'] = df['close'].shift(-26)
        else:
            indicators_data['Tenkan_sen'] = pd.Series([float('nan')] * len(df), index=df.index)
            indicators_data['Kijun_sen'] = pd.Series([float('nan')] * len(df), index=df.index)
            indicators_data['Senkou_Span_A'] = pd.Series([float('nan')] * len(df), index=df.index)
            indicators_data['Senkou_Span_B'] = pd.Series([float('nan')] * len(df), index=df.index)
            indicators_data['Chikou_Span'] = pd.Series([float('nan')] * len(df), index=df.index)

        # میانگین حجم 20 کندل
        if len(df) >= 20:
            indicators_data['Volume_MA20'] = df['volume'].rolling(window=20).mean()
        else:
            indicators_data['Volume_MA20'] = pd.Series([float('nan')] * len(df), index=df.index)

        # RSI
        if len(df) >= 14:
            indicators_data['RSI'] = ta.momentum.RSIIndicator(df['close'], window=14).rsi()
        else:
            indicators_data['RSI'] = pd.Series([float('nan')] * len(df), index=df.index)

        return indicators_data

    def check_higher_timeframe(self, timestamp):
        df_15m = self.df_15m[self.df_15m['timestamp'] <= timestamp].tail(200)
        df_1h = self.df_1h[self.df_1h['timestamp'] <= timestamp].tail(200)

        if len(df_1h) < 52 or len(df_15m) < 200:
            logger.warning(f"Not enough data for higher timeframes at {timestamp}")
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

    def calculate_metrics(self):
        # محاسبه معیارهای عملکرد
        if not self.trades:
            return {
                'total_trades': 0,
                'win_rate': 0.0,
                'max_drawdown': 0.0,
                'sharpe_ratio': 0.0,
                'profit_factor': 0.0
            }

        total_trades = len(self.trades)
        wins = sum(1 for trade in self.trades if trade['profit'] > 0)
        win_rate = (wins / total_trades) * 100 if total_trades > 0 else 0.0

        # محاسبه حداکثر drawdown
        equity_series = pd.Series(self.equity_history)
        rolling_max = equity_series.cummax()
        drawdowns = (rolling_max - equity_series) / rolling_max
        max_drawdown = drawdowns.max() * 100 if not drawdowns.empty else 0.0

        # محاسبه Sharpe Ratio (با فرض نرخ بدون ریسک 0)
        returns = pd.Series([trade['profit'] / self.initial_balance for trade in self.trades])
        sharpe_ratio = (returns.mean() / returns.std()) * np.sqrt(365 * 24 * 60) if returns.std() != 0 else 0.0

        # محاسبه Profit Factor
        gross_profit = sum(trade['profit'] for trade in self.trades if trade['profit'] > 0)
        gross_loss = abs(sum(trade['profit'] for trade in self.trades if trade['profit'] < 0))
        profit_factor = gross_profit / gross_loss if gross_loss != 0 else float('inf')

        return {
            'total_trades': total_trades,
            'win_rate': win_rate,
            'max_drawdown': max_drawdown,
            'sharpe_ratio': sharpe_ratio,
            'profit_factor': profit_factor
        }

    def run_backtest(self):
        logger.info("Starting backtest...")
        position = None
        entry_price = 0.0
        quantity = 0.0
        stop_loss = 0.0
        take_profit = 0.0

        for index, row in self.df_1m.iterrows():
            timestamp = row['timestamp']
            current_price = row['close']
            current_volume = row['volume']

            # به‌روزرسانی equity history
            if position == 'Long':
                unrealized_pnl = (current_price - entry_price) * quantity * self.leverage
            elif position == 'Short':
                unrealized_pnl = (entry_price - current_price) * quantity * self.leverage
            else:
                unrealized_pnl = 0.0
            current_equity = self.balance + unrealized_pnl
            self.equity_history.append(current_equity)

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
                if self.balance <= 0:
                    logger.warning("Balance is zero or negative, cannot open new position.")
                    break
                position_size = (self.balance * self.risk_percent) * self.leverage
                quantity = position_size / current_price
                entry_price = current_price
                position = signal
                stop_loss = entry_price - (5 * atr_1m) if signal == 'Long' else entry_price + (5 * atr_1m)
                take_profit = entry_price + (6 * atr_1m) if signal == 'Long' else entry_price - (6 * atr_1m)
                self.highest_price = entry_price if signal == 'Long' else float('inf')
                self.lowest_price = entry_price if signal == 'Short' else 0
                self.trailing_stop = stop_loss
                fee = self.fee_rate * position_size
                self.balance -= fee
                logger.info(f"Opened {position} at {entry_price}, Quantity: {quantity:.4f}, Stop Loss: {stop_loss:.2f}, Take Profit: {take_profit:.2f}, Fee: {fee:.4f}, Balance: {self.balance:.2f}")
            elif position is not None:
                # به‌روزرسانی Trailing Stop
                if position == 'Long':
                    self.highest_price = max(self.highest_price, current_price)
                    self.trailing_stop = max(self.trailing_stop, self.highest_price - (5 * atr_1m))
                elif position == 'Short':
                    self.lowest_price = min(self.lowest_price, current_price)
                    self.trailing_stop = min(self.trailing_stop, self.lowest_price + (5 * atr_1m))

                # محاسبه سود فعلی (درصد)
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
                        position_size = quantity * entry_price
                        profit = (current_price - entry_price) * quantity * self.leverage
                        fee = self.fee_rate * (position_size + (quantity * current_price))
                        net_profit = profit - fee
                        self.balance += profit - fee
                        self.trades.append({'type': 'Long', 'profit': net_profit, 'entry_price': entry_price, 'exit_price': current_price})
                        logger.info(f"Closed Long at {current_price}, Profit: {profit:.2f}, Fee: {fee:.4f}, Net Profit: {net_profit:.2f}, Balance: {self.balance:.2f}")
                        position = None
                elif position == 'Short':
                    if (exit_position or current_price >= self.trailing_stop or 
                        current_price <= take_profit or signal == 'Long'):
                        position_size = quantity * entry_price
                        profit = (entry_price - current_price) * quantity * self.leverage
                        fee = self.fee_rate * (position_size + (quantity * current_price))
                        net_profit = profit - fee
                        self.balance += profit - fee
                        self.trades.append({'type': 'Short', 'profit': net_profit, 'entry_price': entry_price, 'exit_price': current_price})
                        logger.info(f"Closed Short at {current_price}, Profit: {profit:.2f}, Fee: {fee:.4f}, Net Profit: {net_profit:.2f}, Balance: {self.balance:.2f}")
                        position = None

        # محاسبه ارزش نهایی HODL
        initial_price = self.df_1m['close'].iloc[0]
        final_price = self.df_1m['close'].iloc[-1]
        hodl_value = (self.initial_balance / initial_price) * final_price

        # محاسبه معیارهای عملکرد
        metrics = self.calculate_metrics()

        logger.info("Backtest completed!")
        logger.info(f"Initial Balance: {self.initial_balance:.2f} USDT")
        logger.info(f"Final Balance (Strategy): {self.balance:.2f} USDT")
        logger.info(f"Final Value (HODL): {hodl_value:.2f} USDT")
        logger.info(f"Total Trades: {metrics['total_trades']}")
        logger.info(f"Win Rate: {metrics['win_rate']:.2f}%")
        logger.info(f"Maximum Drawdown: {metrics['max_drawdown']:.2f}%")
        logger.info(f"Sharpe Ratio: {metrics['sharpe_ratio']:.2f}")
        logger.info(f"Profit Factor: {metrics['profit_factor']:.2f}")

if __name__ == "__main__":
    backtest = BacktestBot(initial_balance=500, leverage=3)
    backtest.run_backtest()