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
        logging.FileHandler('backtest_log_sma_crossover_macd_1m.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class BacktestSMACrossoverMACD:
    def __init__(self, initial_balance=100, leverage=3, fee_rate=0.0002, symbol='BTCUSDT'):
        self.initial_balance = initial_balance
        self.balance = initial_balance
        self.leverage = leverage
        self.fee_rate = fee_rate
        self.btc_held = 0
        self.trades = []
        self.positions = []
        self.equity_history = []
        self.symbol = symbol
        self.take_profit_percent = 0.08  # ۸٪ تیک پروفیت
        self.stop_loss_percent = 0.04   # ۴٪ استاپ‌لاس
        self.trailing_stop_percent = 0.02  # ۲٪ Trailing Stop
        self.risk_percent = 0.01  # ریسک ۱٪ در هر معامله
        self.last_trade_time = None
        self.min_trade_interval = pd.Timedelta(minutes=3)

        # لود داده‌ها
        try:
            self.df_1m = pd.read_csv('./BTCUSDT_1m_historical.csv')
            self.df_1m['timestamp'] = pd.to_datetime(self.df_1m['timestamp'], format='%Y-%m-%d %H:%M:%S', errors='coerce')
            self.df_1m = self.df_1m.dropna(subset=['timestamp'])
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
        indicators = {}
        try:
            indicators['SMA9'] = ta.trend.SMAIndicator(df['close'], window=9).sma_indicator()
            indicators['SMA14'] = ta.trend.SMAIndicator(df['close'], window=14).sma_indicator()
            indicators['SMA28'] = ta.trend.SMAIndicator(df['close'], window=28).sma_indicator()
            indicators['ATR'] = ta.volatility.AverageTrueRange(df['high'], df['low'], df['close'], window=14).average_true_range()
            indicators['ADX'] = ta.trend.ADXIndicator(df['high'], df['low'], df['close'], window=14).adx()
            macd = ta.trend.MACD(df['close'], window_slow=26, window_fast=12, window_sign=9)
            indicators['MACD'] = macd.macd()
            indicators['MACD_signal'] = macd.macd_signal()
            return indicators
        except Exception as e:
            logger.error(f"Error calculating indicators: {e}")
            return None

    def calculate_position_size(self, price):
        risk_amount = self.balance * self.risk_percent
        stop_loss_distance = price * self.stop_loss_percent
        position_value = risk_amount * self.leverage
        quantity = position_value / price
        if quantity <= 0:
            logger.warning(f"Invalid quantity: {quantity}")
            return 0
        return quantity

    def close_position(self, position, exit_price, reason='Manual'):
        try:
            quantity = position['quantity']
            entry_price = position['entry_price']
            side = position['side']
            if side == 'Long':
                pnl = (exit_price - entry_price) * quantity
            else:
                pnl = (entry_price - exit_price) * quantity
            entry_fee = entry_price * quantity * self.fee_rate
            exit_fee = exit_price * quantity * self.fee_rate
            total_pnl = pnl - entry_fee - exit_fee
            self.balance += total_pnl
            status = 'Win' if total_pnl > 0 else 'Loss'
            trade_record = {
                'type': side,
                'profit': total_pnl,
                'entry_price': entry_price,
                'exit_price': exit_price,
                'reason': reason
            }
            self.trades.append(trade_record)
            self.positions.remove(position)
            logger.info(f"Closed {side} at {exit_price}, PnL: {total_pnl:.2f}, Reason: {reason}, Balance: {self.balance:.2f}")
        except Exception as e:
            logger.error(f"Error closing position: {e}")

    def check_tp_sl_trailing(self, current_price):
        for pos in self.positions[:]:
            stop_loss = pos['stop_loss']
            take_profit = pos['take_profit']
            side = pos['side']
            if side == 'Long':
                if current_price <= stop_loss:
                    self.close_position(pos, stop_loss, reason='Stop Loss Hit')
                    continue
                if current_price >= take_profit:
                    pos['take_profit'] = current_price * (1 + self.take_profit_percent)
                    pos['stop_loss'] = max(pos['stop_loss'], current_price * (1 - self.trailing_stop_percent))
                    pos['first_target_hit'] = True
                if pos.get('first_target_hit', False):
                    pos['trailing_stop'] = max(pos['trailing_stop'], current_price * (1 - self.trailing_stop_percent))
                    if current_price <= pos['trailing_stop']:
                        self.close_position(pos, pos['trailing_stop'], reason='Trailing Stop Hit')
            else:
                if current_price >= stop_loss:
                    self.close_position(pos, stop_loss, reason='Stop Loss Hit')
                    continue
                if current_price <= take_profit:
                    pos['take_profit'] = current_price * (1 - self.take_profit_percent)
                    pos['stop_loss'] = min(pos['stop_loss'], current_price * (1 + self.trailing_stop_percent))
                    pos['first_target_hit'] = True
                if pos.get('first_target_hit', False):
                    pos['trailing_stop'] = min(pos['trailing_stop'], current_price * (1 + self.trailing_stop_percent))
                    if current_price >= pos['trailing_stop']:
                        self.close_position(pos, pos['trailing_stop'], reason='Trailing Stop Hit')

    def calculate_metrics(self):
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
        equity_series = pd.Series(self.equity_history)
        rolling_max = equity_series.cummax()
        drawdowns = (rolling_max - equity_series) / rolling_max
        max_drawdown = drawdowns.max() * 100 if not drawdowns.empty else 0.0
        returns = pd.Series([trade['profit'] / self.initial_balance for trade in self.trades])
        sharpe_ratio = (returns.mean() / returns.std()) * np.sqrt(365 * 24 * 60) if returns.std() != 0 else 0.0
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
        logger.info("Starting SMA Crossover with MACD backtest on 1m timeframe...")
        indicators = self.calculate_indicators(self.df_1m)
        if indicators is None:
            logger.error("Failed to calculate indicators")
            return

        min_data_length = 28  # برای محاسبه SMA28 و MACD
        for index, row in self.df_1m.iterrows():
            if index < min_data_length:
                continue
            current_price = row['close']
            timestamp = row['timestamp']

            # بررسی فاصله زمانی از آخرین معامله
            if self.last_trade_time and (timestamp - self.last_trade_time) < self.min_trade_interval:
                continue

            # محاسبه equity
            unrealized_pnl = 0
            for pos in self.positions:
                if pos['side'] == 'Long':
                    unrealized_pnl += (current_price - pos['entry_price']) * pos['quantity'] * self.leverage
                else:
                    unrealized_pnl += (pos['entry_price'] - current_price) * pos['quantity'] * self.leverage
            current_equity = self.balance + unrealized_pnl
            self.equity_history.append(current_equity)

            sma9 = indicators['SMA9'].iloc[index]
            sma14 = indicators['SMA14'].iloc[index]
            sma28 = indicators['SMA28'].iloc[index]
            atr = indicators['ATR'].iloc[index]
            adx = indicators['ADX'].iloc[index]
            macd = indicators['MACD'].iloc[index]
            macd_signal = indicators['MACD_signal'].iloc[index]
            prev_close = self.df_1m['close'].iloc[index - 1] if index > 0 else current_price
            prev_sma9 = indicators['SMA9'].iloc[index - 1] if index > 0 else sma9
            prev_macd = indicators['MACD'].iloc[index - 1] if index > 0 else macd
            prev_macd_signal = indicators['MACD_signal'].iloc[index - 1] if index > 0 else macd_signal

            # فیلتر ATR و ADX
            atr_threshold = current_price * 0.003  # حداقل ۰.۳٪ قیمت
            if atr < atr_threshold or adx < 25:
                continue

            # بررسی استاپ‌لاس، تیک پروفیت و Trailing Stop
            self.check_tp_sl_trailing(current_price)

            long_position = next((p for p in self.positions if p['side'] == 'Long'), None)
            short_position = next((p for p in self.positions if p['side'] == 'Short'), None)

            # شرایط ورود Long
            long_conditions = {
                'Price breaks SMA9 upward': prev_close <= prev_sma9 and current_price > sma9,
                'SMA9 > SMA14 > SMA28': sma9 > sma14 > sma28,
                'MACD crossover': prev_macd <= prev_macd_signal and macd > macd_signal
            }

            # شرایط ورود Short
            short_conditions = {
                'Price breaks SMA9 downward': prev_close >= prev_sma9 and current_price < sma9,
                'SMA9 < SMA14 < SMA28': sma9 < sma14 < sma28,
                'MACD crossunder': prev_macd >= prev_macd_signal and macd < macd_signal
            }

            signal = None
            if all(long_conditions.values()):
                signal = 'Long'
            elif all(short_conditions.values()):
                signal = 'Short'

            if signal and not long_position and not short_position:
                if self.balance <= 0:
                    logger.warning("Balance is zero or negative, cannot open new position.")
                    break
                quantity = self.calculate_position_size(current_price)
                if quantity == 0:
                    logger.warning("Cannot open position: Zero quantity")
                    continue
                # محاسبه استاپ‌لاس و تیک پروفیت
                if signal == 'Long':
                    stop_loss = current_price * (1 - self.stop_loss_percent)
                    take_profit = current_price * (1 + self.take_profit_percent)
                else:
                    stop_loss = current_price * (1 + self.stop_loss_percent)
                    take_profit = current_price * (1 - self.take_profit_percent)
                position = {
                    'side': signal,
                    'quantity': quantity,
                    'entry_price': current_price,
                    'stop_loss': stop_loss,
                    'take_profit': take_profit,
                    'trailing_stop': stop_loss,
                    'timestamp': timestamp,
                    'first_target_hit': False
                }
                self.positions.append(position)
                fee = self.fee_rate * (quantity * current_price)
                self.balance -= fee
                self.last_trade_time = timestamp
                logger.info(f"Opened {signal} at {current_price}, Qty: {quantity:.4f}, SL: {stop_loss:.2f}, TP: {take_profit:.2f}, Fee: {fee:.4f}, Balance: {self.balance:.2f}")

        # محاسبه ارزش نهایی HODL
        initial_price = self.df_1m['close'].iloc[0]
        final_price = self.df_1m['close'].iloc[-1]
        self.hodl_value = (self.initial_balance / initial_price) * final_price

        # گزارش معیارها
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
    backtest = BacktestSMACrossoverMACD(initial_balance=100, leverage=3, symbol='BTCUSDT')
    backtest.run_backtest()