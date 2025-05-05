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
        logging.FileHandler('backtest_log_MACD_BB_Stoch_VWAP_1m_rev.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class BacktestBot:
    def __init__(self, initial_balance=500, leverage=3, risk_percent=0.05, fee_rate=0.0006):
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
        self.last_signal_time = None  # برای جلوگیری از سیگنال‌های مکرر

        # لود داده‌ها و تبدیل تایم‌استمپ‌ها
        try:
            self.df_1m = pd.read_csv('./BTCUSDT_1m_historical.csv')

            # تبدیل تایم‌استمپ به datetime با فرمت درست
            self.df_1m['timestamp'] = pd.to_datetime(self.df_1m['timestamp'], format='%Y-%m-%d %H:%M:%S', errors='coerce')

            # حذف ردیف‌هایی که تایم‌استمپ نادرست دارن
            self.df_1m = self.df_1m.dropna(subset=['timestamp', 'close', 'volume'])

            # چک کردن دیتافریم
            if self.df_1m.empty or 'close' not in self.df_1m.columns or 'volume' not in self.df_1m.columns:
                logger.error("Dataframe 1m is empty or missing 'close' or 'volume' column")
                raise ValueError("Invalid 1m data: empty or missing 'close' or 'volume' column")
            logger.info(f"Loaded 1m data: {len(self.df_1m)} rows, columns: {self.df_1m.columns.tolist()}")
        except Exception as e:
            logger.error(f"Error loading data: {e}")
            raise

        # محاسبه HODL
        self.hodl_btc = initial_balance / self.df_1m['close'].iloc[0]
        self.hodl_value = 0

    def calculate_indicators(self, df):
        indicators_data = {}
        # Bollinger Bands
        if len(df) >= 20:
            bb = ta.volatility.BollingerBands(close=df['close'], window=20, window_dev=2)
            indicators_data['BB_Middle'] = bb.bollinger_mavg()
            indicators_data['BB_Lower'] = bb.bollinger_lband()
            indicators_data['BB_Upper'] = bb.bollinger_hband()
        else:
            indicators_data['BB_Middle'] = pd.Series([float('nan')] * len(df), index=df.index)
            indicators_data['BB_Lower'] = pd.Series([float('nan')] * len(df), index=df.index)
            indicators_data['BB_Upper'] = pd.Series([float('nan')] * len(df), index=df.index)

        # MACD
        if len(df) >= 21:
            macd = ta.trend.MACD(df['close'], window_fast=8, window_slow=21, window_sign=5)
            indicators_data['MACD'] = macd.macd()
            indicators_data['MACD_Signal'] = macd.macd_signal()
        else:
            indicators_data['MACD'] = pd.Series([float('nan')] * len(df), index=df.index)
            indicators_data['MACD_Signal'] = pd.Series([float('nan')] * len(df), index=df.index)

        # Stochastic RSI
        if len(df) >= 14:
            stoch_rsi = ta.momentum.StochRSIIndicator(df['close'], window=14, smooth1=3, smooth2=3)
            indicators_data['StochRSI_K'] = stoch_rsi.stochrsi_k()
        else:
            indicators_data['StochRSI_K'] = pd.Series([float('nan')] * len(df), index=df.index)

        # VWAP (حجم تعدیل‌شده)
        if len(df) >= 1 and 'volume' in df.columns:
            typical_price = (df['high'] + df['low'] + df['close']) / 3
            volume_sum = df['volume'].rolling(window=1, min_periods=1).sum()
            tp_sum = (typical_price * df['volume']).rolling(window=1, min_periods=1).sum()
            indicators_data['VWAP'] = tp_sum / volume_sum
        else:
            indicators_data['VWAP'] = pd.Series([float('nan')] * len(df), index=df.index)

        # ATR
        if len(df) >= 20:
            indicators_data['ATR'] = ta.volatility.AverageTrueRange(df['high'], df['low'], df['close'], window=20).average_true_range()
        else:
            indicators_data['ATR'] = pd.Series([float('nan')] * len(df), index=df.index)

        # میانگین حجم برای فیلتر
        if len(df) >= 20:
            indicators_data['Volume_MA'] = df['volume'].rolling(window=20).mean()
        else:
            indicators_data['Volume_MA'] = pd.Series([float('nan')] * len(df), index=df.index)

        # EMA برای تأیید روند
        if len(df) >= 50:
            indicators_data['EMA_50'] = ta.trend.EMAIndicator(df['close'], window=50).ema_indicator()
        else:
            indicators_data['EMA_50'] = pd.Series([float('nan')] * len(df), index=df.index)

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
        min_data_length = 50  # حداقل تعداد کندل برای EMA 50
        for index, row in self.df_1m.iterrows():
            if index < min_data_length - 1:  # صبر تا وقتی داده‌ها کافی باشه
                continue
            timestamp = row['timestamp']
            current_price = row['close']
            current_volume = row['volume']

            # فیلتر زمان برای جلوگیری از سیگنال‌های مکرر (هر 120 کندل)
            if self.last_signal_time and (index - self.last_signal_time) < 120 and position is None:
                continue

            # به‌روزرسانی equity history
            if position == 'Short':
                unrealized_pnl = (entry_price - current_price) * quantity * self.leverage  # برای Short (سیگنال Long)
            elif position == 'Long':
                unrealized_pnl = (current_price - entry_price) * quantity * self.leverage  # برای Long (سیگنال Short)
            else:
                unrealized_pnl = 0.0
            current_equity = self.balance + unrealized_pnl
            self.equity_history.append(current_equity)

            bb_middle = indicators_1m['BB_Middle'].iloc[index]
            bb_lower = indicators_1m['BB_Lower'].iloc[index]
            bb_upper = indicators_1m['BB_Upper'].iloc[index]
            macd = indicators_1m['MACD'].iloc[index]
            macd_signal = indicators_1m['MACD_Signal'].iloc[index]
            stoch_rsi_k = indicators_1m['StochRSI_K'].iloc[index]
            vwap = indicators_1m['VWAP'].iloc[index]
            atr = indicators_1m['ATR'].iloc[index]
            volume_ma = indicators_1m['Volume_MA'].iloc[index]
            ema_50 = indicators_1m['EMA_50'].iloc[index]

            signal = 'Neutral'
            if (not pd.isna(current_price) and not pd.isna(bb_middle) and not pd.isna(bb_lower) and 
                not pd.isna(bb_upper) and not pd.isna(macd) and not pd.isna(macd_signal) and 
                not pd.isna(stoch_rsi_k) and not pd.isna(vwap) and not pd.isna(atr) and 
                not pd.isna(volume_ma) and not pd.isna(ema_50) and current_volume > 2 * volume_ma):
                if (macd > macd_signal and macd > 0 and current_price > bb_middle + 0.4 * atr and 
                    stoch_rsi_k < 60 and current_price > vwap + 0.4 * atr and current_price > ema_50):
                    signal = 'Long'
                    signal_count['Long'] += 1
                elif (macd < macd_signal and current_price < bb_middle - 0.4 * atr and 
                      stoch_rsi_k > 40 and current_price < vwap - 0.4 * atr and current_price < ema_50):
                    signal = 'Short'
                    signal_count['Short'] += 1
            else:
                logger.debug(f"Missing data at index {index}: Price={current_price}, BB_Middle={bb_middle}, MACD={macd}, MACD_Signal={macd_signal}, StochRSI_K={stoch_rsi_k}, VWAP={vwap}, ATR={atr}, Volume_MA={volume_ma}, EMA_50={ema_50}")

            if position is None and signal != 'Neutral':
                if self.balance <= 0:
                    logger.warning("Balance is zero or negative, cannot open new position.")
                    break
                position_size = (self.balance * self.risk_percent) * self.leverage
                quantity = position_size / current_price
                entry_price = current_price
                # معکوس کردن پوزیشن‌ها
                if signal == 'Long':
                    position = 'Short'  # سیگنال Long -> پوزیشن Short
                    stop_loss = entry_price + (3.5 * atr)
                    take_profit = entry_price - (4.5 * atr)
                    self.lowest_price = entry_price  # برای Short
                    self.highest_price = float('inf')
                elif signal == 'Short':
                    position = 'Long'  # سیگنال Short -> پوزیشن Long
                    stop_loss = entry_price - (3.5 * atr)
                    take_profit = entry_price + (4.5 * atr)
                    self.highest_price = entry_price  # برای Long
                    self.lowest_price = 0
                self.trailing_stop = stop_loss
                fee = self.fee_rate * position_size
                self.balance -= fee
                self.last_signal_time = index
                logger.info(f"Opened {position} (from signal {signal}) at {entry_price}, Quantity: {quantity:.4f}, Stop Loss: {stop_loss:.2f}, Take Profit: {take_profit:.2f}, Fee: {fee:.4f}, Balance: {self.balance:.2f}")
            elif position is not None:
                # به‌روزرسانی Trailing Stop
                if position == 'Short':  # سیگنال Long -> پوزیشن Short
                    self.lowest_price = min(self.lowest_price, current_price)
                    self.trailing_stop = min(self.trailing_stop, self.lowest_price + (3.5 * atr))
                elif position == 'Long':  # سیگنال Short -> پوزیشن Long
                    self.highest_price = max(self.highest_price, current_price)
                    self.trailing_stop = max(self.trailing_stop, self.highest_price - (3.5 * atr))

                # خروج از باند Bollinger (معکوس)
                exit_bb = False
                if position == 'Short' and current_price > bb_upper:  # برای Short (سیگنال Long)
                    exit_bb = True
                    logger.info(f"Closing Short due to breaking above BB_Upper: {current_price}")
                elif position == 'Long' and current_price < bb_lower:  # برای Long (سیگنال Short)
                    exit_bb = True
                    logger.info(f"Closing Long due to breaking below BB_Lower: {current_price}")

                # بستن پوزیشن‌ها
                if position == 'Short':  # سیگنال Long -> پوزیشن Short
                    if (current_price >= self.trailing_stop or 
                        current_price <= take_profit or signal == 'Short' or exit_bb):
                        position_size = quantity * entry_price
                        profit = (entry_price - current_price) * quantity * self.leverage  # سود برای Short
                        fee = self.fee_rate * (position_size + (quantity * current_price))
                        net_profit = profit - fee
                        self.balance += profit - fee
                        self.trades.append({'type': 'Short', 'profit': net_profit, 'entry_price': entry_price, 'exit_price': current_price})
                        logger.info(f"Closed Short (from Long signal) at {current_price}, Profit: {profit:.2f}, Fee: {fee:.4f}, Net Profit: {net_profit:.2f}, Balance: {self.balance:.2f}")
                        position = None
                elif position == 'Long':  # سیگنال Short -> پوزیشن Long
                    if (current_price <= self.trailing_stop or 
                        current_price >= take_profit or signal == 'Long' or exit_bb):
                        position_size = quantity * entry_price
                        profit = (current_price - entry_price) * quantity * self.leverage  # سود برای Long
                        fee = self.fee_rate * (position_size + (quantity * current_price))
                        net_profit = profit - fee
                        self.balance += profit - fee
                        self.trades.append({'type': 'Long', 'profit': net_profit, 'entry_price': entry_price, 'exit_price': current_price})
                        logger.info(f"Closed Long (from Short signal) at {current_price}, Profit: {profit:.2f}, Fee: {fee:.4f}, Net Profit: {net_profit:.2f}, Balance: {self.balance:.2f}")
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