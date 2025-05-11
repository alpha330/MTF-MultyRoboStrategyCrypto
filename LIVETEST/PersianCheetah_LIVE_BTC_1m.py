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
        logging.FileHandler('backtest_log_persian_cheetah_optimized_1m.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class BacktestPersianCheetahOptimized:
    def __init__(self, initial_balance=100, leverage=15, risk_percent=1, fee_rate=0.0002, symbol='BTCUSDT'):
        self.initial_balance = initial_balance
        self.balance = initial_balance
        self.leverage = leverage
        self.risk_percent = risk_percent
        self.fee_rate = fee_rate
        self.btc_held = 0
        self.trades = []
        self.position = None
        self.positions = []
        self.equity_history = []
        self.symbol = symbol
        self.trailing_stop_percent = 0.015  # 1.5% برای Trailing Stop
        self.last_trade_time = None
        self.min_trade_interval = pd.Timedelta(minutes=5)

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
            indicators['RSI'] = ta.momentum.RSIIndicator(df['close'], window=14).rsi()
            bb = ta.volatility.BollingerBands(df['close'], window=20, window_dev=2)
            indicators['BB_upper'] = bb.bollinger_hband()
            indicators['BB_middle'] = bb.bollinger_mavg()
            indicators['BB_lower'] = bb.bollinger_lband()
            indicators['Volume'] = df['volume']
            indicators['Volume_MA'] = ta.trend.SMAIndicator(df['volume'], window=20).sma_indicator()
            indicators['ATR'] = ta.volatility.AverageTrueRange(df['high'], df['low'], df['close'], window=14).average_true_range()
            indicators['EMA_50'] = ta.trend.EMAIndicator(df['close'], window=50).ema_indicator()
            return indicators
        except Exception as e:
            logger.error(f"Error calculating indicators: {e}")
            return None

    def calculate_position_size(self, price, atr):
        risk_amount = self.balance * self.risk_percent
        stop_loss_distance = 1.5 * atr  # استاپ‌لاس ۱.۵ برابر ATR
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

    def check_tp_sl_trailing(self, current_price, atr, index):
        for pos in self.positions[:]:
            stop_loss = pos['stop_loss']
            take_profit = pos['take_profit']
            side = pos['side']
            if side == 'Long':
                if current_price <= stop_loss:
                    self.close_position(pos, stop_loss, reason='Stop Loss Hit')
                    continue
                if current_price >= take_profit:
                    pos['take_profit'] = current_price + 3 * atr
                    pos['stop_loss'] = max(pos['stop_loss'], current_price - 1.5 * atr)
                    pos['first_target_hit'] = True
                if pos.get('first_target_hit', False):
                    pos['trailing_stop'] = max(pos['trailing_stop'], current_price - 1.5 * atr)
                    if current_price <= pos['trailing_stop']:
                        self.close_position(pos, pos['trailing_stop'], reason='Trailing Stop Hit')
            else:
                if current_price >= stop_loss:
                    self.close_position(pos, stop_loss, reason='Stop Loss Hit')
                    continue
                if current_price <= take_profit:
                    pos['take_profit'] = current_price - 3 * atr
                    pos['stop_loss'] = min(pos['stop_loss'], current_price + 1.5 * atr)
                    pos['first_target_hit'] = True
                if pos.get('first_target_hit', False):
                    pos['trailing_stop'] = min(pos['trailing_stop'], current_price + 1.5 * atr)
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
        logger.info("Starting optimized backtest for PersianCheetah strategy on 1m timeframe...")
        indicators = self.calculate_indicators(self.df_1m)
        if indicators is None:
            logger.error("Failed to calculate indicators")
            return

        min_data_length = 50
        for index, row in self.df_1m.iterrows():
            if index < min_data_length - 1:
                continue
            current_price = row['close']
            current_volume = row['volume']
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

            rsi = indicators['RSI'].iloc[index]
            bb_upper = indicators['BB_upper'].iloc[index]
            bb_middle = indicators['BB_middle'].iloc[index]
            bb_lower = indicators['BB_lower'].iloc[index]
            volume = indicators['Volume'].iloc[index]
            volume_ma = indicators['Volume_MA'].iloc[index]
            atr = indicators['ATR'].iloc[index]
            ema_50 = indicators['EMA_50'].iloc[index]

            atr_threshold = current_price * 0.0005
            rsi_long = 30
            rsi_short = 70
            rsi_neutral_low = 45
            rsi_neutral_high = 55

            long_conditions = {
                f'RSI < {rsi_long}': rsi < rsi_long,
                'Price <= BB Lower': current_price <= bb_lower,
                'Price - BB Lower > ATR': (bb_lower - current_price) >= atr,
                'Volume > Volume MA': volume > volume_ma,
                'ATR > Threshold': atr > atr_threshold,
                'Price > EMA 50': current_price > ema_50
            }
            short_conditions = {
                f'RSI > {rsi_short}': rsi > rsi_short,
                'Price >= BB Upper': current_price >= bb_upper,
                'Price - BB Upper > ATR': (current_price - bb_upper) >= atr,
                'Volume > Volume MA': volume > volume_ma,
                'ATR > Threshold': atr > atr_threshold,
                'Price < EMA 50': current_price < ema_50
            }

            self.check_tp_sl_trailing(current_price, atr, index)

            long_position = next((p for p in self.positions if p['side'] == 'Long'), None)
            short_position = next((p for p in self.positions if p['side'] == 'Short'), None)

            # خروج در منطقه خنثی RSI
            if long_position and rsi >= rsi_neutral_high:
                self.close_position(long_position, current_price, reason=f'RSI in neutral zone ({rsi_neutral_high})')
                continue
            if short_position and rsi <= rsi_neutral_low:
                self.close_position(short_position, current_price, reason=f'RSI in neutral zone ({rsi_neutral_low})')
                continue

            signal = None
            if all(long_conditions.values()):
                signal = 'Long'
            elif all(short_conditions.values()):
                signal = 'Short'

            if signal and not long_position and not short_position:
                if self.balance <= 0:
                    logger.warning("Balance is zero or negative, cannot open new position.")
                    break
                stop_loss = current_price - (1.5 * atr) if signal == 'Long' else current_price + (1.5 * atr)
                take_profit = current_price + (3 * atr) if signal == 'Long' else current_price - (3 * atr)
                quantity = self.calculate_position_size(current_price, atr)
                if quantity == 0:
                    logger.warning("Cannot open position: Zero quantity")
                    continue
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
                logger.info(f"Opened {signal} at {current_price}, Qty: {quantity:.4f}, SL: {stop_loss:.4f}, TP: {take_profit:.4f}, Fee: {fee:.4f}, Balance: {self.balance:.2f}")

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
    backtest = BacktestPersianCheetahOptimized(initial_balance=100, leverage=5, symbol='BTCUSDT')
    backtest.run_backtest()
