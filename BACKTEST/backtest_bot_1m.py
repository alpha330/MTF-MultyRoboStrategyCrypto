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
        logging.FileHandler('backtest_log_EMA_MACD_Trend_1m.log'),
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

            # تبدیل تایم‌استمپ به datetime با فرمت درست
            self.df_1m['timestamp'] = pd.to_datetime(self.df_1m['timestamp'], format='%Y-%m-%d %H:%M:%S', errors='coerce')

            # حذف ردیف‌هایی که تایم‌استمپ نادرست دارن
            self.df_1m = self.df_1m.dropna(subset=['timestamp'])

            # چک کردن دیتافریم
            if self.df_1m.empty or 'close' not in self.df_1m.columns:
                logger.error("Dataframe 1m is empty or missing 'close' column")
                raise ValueError("Invalid 1m data: empty or missing 'close' column")
            logger.info(f"Loaded 1m data: {len(self.df_1m)} rows, columns: {self.df_1m.columns.tolist()}")
        except Exception as e:
            logger.error(f"Error loading data: {e}")
            raise

        # محاسبه HODL
        self.hodl_btc = initial_balance / self.df_1m['close'].iloc[0]
        self.hodl_value = 0

    def calculate_indicators(self, df):
        indicators_data = {}
        # EMA 5 و EMA 13
        if len(df) >= 13:
            indicators_data['EMA5'] = ta.trend.EMAIndicator(df['close'], window=5).ema_indicator()
            indicators_data['EMA13'] = ta.trend.EMAIndicator(df['close'], window=13).ema_indicator()
        else:
            indicators_data['EMA5'] = pd.Series([float('nan')] * len(df), index=df.index)
            indicators_data['EMA13'] = pd.Series([float('nan')] * len(df), index=df.index)

        # EMA 21 برای فیلتر روند
        if len(df) >= 21:
            indicators_data['EMA21'] = ta.trend.EMAIndicator(df['close'], window=21).ema_indicator()
        else:
            indicators_data['EMA21'] = pd.Series([float('nan')] * len(df), index=df.index)

        # ATR
        if len(df) >= 14:
            indicators_data['ATR'] = ta.volatility.AverageTrueRange(df['high'], df['low'], df['close'], window=14).average_true_range()
        else:
            indicators_data['ATR'] = pd.Series([float('nan')] * len(df), index=df.index)

        # MACD
        if len(df) >= 21:
            macd = ta.trend.MACD(df['close'], window_fast=8, window_slow=21, window_sign=5)
            indicators_data['MACD'] = macd.macd()
            indicators_data['MACD_Signal'] = macd.macd_signal()
        else:
            indicators_data['MACD'] = pd.Series([float('nan')] * len(df), index=df.index)
            indicators_data['MACD_Signal'] = pd.Series([float('nan')] * len(df), index=df.index)

        return indicators_data

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
        logger.info("Starting backtest for 1m timeframe...")
        position = None
        entry_price = 0.0
        quantity = 0.0
        stop_loss = 0.0
        take_profit = 0.0
        signal_count = {'Long': 0, 'Short': 0}  # برای شمارش سیگنال‌ها

        # پیش‌محاسبه شاخص‌ها برای کل دیتافریم 1 دقیقه
        indicators_1m = self.calculate_indicators(self.df_1m)

        # اجرای بک‌تست
        min_data_length = 21  # حداقل تعداد کندل برای EMA21 و MACD
        for index, row in self.df_1m.iterrows():
            if index < min_data_length - 1:  # صبر تا وقتی داده‌ها کافی باشه
                continue
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

            ema5 = indicators_1m['EMA5'].iloc[index]
            ema13 = indicators_1m['EMA13'].iloc[index]
            ema5_prev = indicators_1m['EMA5'].iloc[index - 1] if index > 0 else float('nan')
            ema13_prev = indicators_1m['EMA13'].iloc[index - 1] if index > 0 else float('nan')
            ema21 = indicators_1m['EMA21'].iloc[index]
            atr = indicators_1m['ATR'].iloc[index]
            macd = indicators_1m['MACD'].iloc[index]
            macd_signal = indicators_1m['MACD_Signal'].iloc[index]

            signal = 'Neutral'
            if (not pd.isna(ema5) and not pd.isna(ema13) and not pd.isna(ema5_prev) and 
                not pd.isna(ema13_prev) and not pd.isna(ema21) and 
                not pd.isna(macd) and not pd.isna(macd_signal)):
                # محاسبه فاصله نسبی بین EMAها
                ema_diff = abs(ema5 - ema13) / ema13 * 100  # فاصله به درصد
                if (ema5_prev <= ema13_prev and ema5 > ema13 and 
                    ema_diff >= 0.05 and macd > macd_signal and ema13 > ema21):
                    signal = 'Long'
                    signal_count['Long'] += 1
                elif (ema5_prev >= ema13_prev and ema5 < ema13 and 
                      ema_diff >= 0.05 and macd < macd_signal and ema13 < ema21):
                    signal = 'Short'
                    signal_count['Short'] += 1
            else:
                logger.debug(f"Missing data at index {index}: EMA5={ema5}, EMA13={ema13}, EMA5_prev={ema5_prev}, EMA13_prev={ema13_prev}, EMA21={ema21}, MACD={macd}, MACD_Signal={macd_signal}")

            if position is None and signal != 'Neutral':
                if self.balance <= 0:
                    logger.warning("Balance is zero or negative, cannot open new position.")
                    break
                position_size = (self.balance * self.risk_percent) * self.leverage
                quantity = position_size / current_price
                entry_price = current_price
                position = signal
                stop_loss = entry_price - (1.5 * atr) if signal == 'Long' else entry_price + (1.5 * atr)
                take_profit = entry_price + (4.5 * atr) if signal == 'Long' else entry_price - (4.5 * atr)
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
                    self.trailing_stop = max(self.trailing_stop, self.highest_price - (1.5 * atr))
                elif position == 'Short':
                    self.lowest_price = min(self.lowest_price, current_price)
                    self.trailing_stop = min(self.trailing_stop, self.lowest_price + (1.5 * atr))

                if position == 'Long':
                    if (current_price <= self.trailing_stop or 
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
                    if (current_price >= self.trailing_stop or 
                        current_price <= take_profit or signal == 'Long'):
                        position_size = quantity * entry_price
                        profit = (entry_price - current_price) * quantity * self.leverage
                        fee = self.fee_rate * (position_size + (quantity * current_price))
                        net_profit = profit - fee
                        self.balance += profit - fee
                        self.trades.append({'type': 'Short', 'profit': net_profit, 'entry_price': entry_price, 'exit_price': current_price})
                        logger.info(f"Closed Short at {current_price}, Profit: {profit:.2f}, Fee: {fee:.4f}, Net Profit: {net_profit:.2f}, Balance: {self.balance:.2f}")
                        position = None

        # گزارش تعداد سیگنال‌ها
        logger.info(f"Total Long signals: {signal_count['Long']}")
        logger.info(f"Total Short signals: {signal_count['Short']}")

        # محاسبه ارزش نهایی HODL
        initial_price = self.df_1m['close'].iloc[0]
        final_price = self.df_1m['close'].iloc[-1]
        self.hodl_value = (self.initial_balance / initial_price) * final_price

        # محاسبه معیارهای عملکرد
        metrics = self.calculate_metrics()

        logger.info("Backtest completed!")
        logger.info(f"Initial Balance: {self.initial_balance:.2f} USDT")
        logger.info(f"Final Balance (Strategy): {self.balance:.2f} USDT")
        logger.info(f"Final Value (HODL): {self.hodl_value:.2f} USDT")
        logger.info(f"Total Trades: {metrics['total_trades']}")
        logger.info(f"Win Rate: {metrics['win_rate']:.2f}%")
        logger.info(f"Maximum Drawdown: {metrics['max_drawdown']:.2f}%")
        logger.info(f"Sharpe Ratio: {metrics['sharpe_ratio']:.2f}")
        logger.info(f"Profit Factor: {metrics['profit_factor']:.2f}")

if __name__ == "__main__":
    backtest = BacktestBot(initial_balance=500, leverage=3)
    backtest.run_backtest()