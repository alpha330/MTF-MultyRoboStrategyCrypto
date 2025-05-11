import pandas as pd
import ta
import logging
import numpy as np
import matplotlib.pyplot as plt

# تنظیم لاگ
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('backtest_log_scalping_hedging.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class BacktestScalpingHedging:
    def __init__(self, initial_balance=100, leverage=3, fee_rate=0.0002, symbol='BTCUSDT'):
        self.initial_balance = initial_balance
        self.balance = initial_balance
        self.leverage = leverage
        self.fee_rate = fee_rate
        self.trades = []
        self.positions = []
        self.equity_history = []
        self.symbol = symbol
        self.risk_percent = 0.1  # ریسک ۱٪
        self.last_trade_time = None
        self.min_trade_interval = pd.Timedelta(minutes=5)
        self.min_quantity = 0.0001  # حداقل مقدار پوزیشن
        self.adjust_interval = 5  # تنظیم مارجین هر ۵ کندل
        self.candle_count = 0

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
            indicators['EMA9'] = ta.trend.EMAIndicator(df['close'], window=9).ema_indicator()
            indicators['EMA21'] = ta.trend.EMAIndicator(df['close'], window=21).ema_indicator()
            indicators['ATR'] = ta.volatility.AverageTrueRange(df['high'], df['low'], df['close'], window=14).average_true_range()
            return indicators
        except Exception as e:
            logger.error(f"Error calculating indicators: {e}")
            return None

    def calculate_position_size(self, price):
        risk_amount = self.balance * self.risk_percent
        atr = self.indicators['ATR'].iloc[-1] if self.indicators else price * 0.015
        stop_loss_distance = max(price * 0.015, atr)  # ۱.۵٪ یا ۱×ATR
        position_value = risk_amount * self.leverage
        quantity = position_value / price
        quantity = max(self.min_quantity, quantity)
        if quantity <= 0:
            logger.warning(f"Invalid quantity: {quantity}")
            return 0
        return round(quantity, 4)

    def close_position(self, position, exit_price, reason='Manual'):
        try:
            quantity = position['quantity']
            entry_price = position['entry_price']
            side = position['side']
            if quantity <= 0:
                logger.error(f"Invalid quantity: {quantity} for {side} position")
                return
            # محاسبه PnL با لوریج
            if side == 'Long':
                pnl = (exit_price - entry_price) * quantity * self.leverage
            else:  # Short
                pnl = (entry_price - exit_price) * quantity * self.leverage
            # محاسبه کارمزد ورود و خروج
            entry_fee = entry_price * quantity * self.fee_rate
            exit_fee = exit_price * quantity * self.fee_rate
            total_pnl = pnl - entry_fee - exit_fee
            # به‌روزرسانی موجودی
            self.balance += total_pnl
            if self.balance < 0:
                logger.warning(f"Balance became negative: {self.balance:.2f}")
                self.balance = 0
            # ثبت معامله
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
            logger.info(f"Closed {side} at {exit_price}, Qty: {quantity:.4f}, PnL: {total_pnl:.2f}, Reason: {reason}, Balance: {self.balance:.2f}")
        except Exception as e:
            logger.error(f"Error closing position: {e}")
            raise

    def adjust_margin(self, current_price):
        long_pos = next((p for p in self.positions if p['side'] == 'Long'), None)
        short_pos = next((p for p in self.positions if p['side'] == 'Short'), None)
        if not long_pos or not short_pos:
            return

        # محاسبه PnL فعلی
        long_pnl = (current_price - long_pos['entry_price']) * long_pos['quantity'] * self.leverage
        short_pnl = (long_pos['entry_price'] - current_price) * short_pos['quantity'] * self.leverage

        if long_pnl > 0 and short_pnl < 0:
            # لانگ سودده، شورت ضررده
            long_pos['quantity'] *= 1.01  # افزایش ۱٪
            short_pos['quantity'] *= 0.99  # کاهش ۱٪
            long_pos['quantity'] = max(self.min_quantity, round(long_pos['quantity'], 4))
            short_pos['quantity'] = max(self.min_quantity, round(short_pos['quantity'], 4))
            logger.info(f"Adjusted: Long Qty={long_pos['quantity']:.4f}, Short Qty={short_pos['quantity']:.4f}")
        elif short_pnl > 0 and long_pnl < 0:
            # شورت سودده، لانگ ضررده
            short_pos['quantity'] *= 1.01  # افزایش ۱٪
            long_pos['quantity'] *= 0.99  # کاهش ۱٪
            short_pos['quantity'] = max(self.min_quantity, round(short_pos['quantity'], 4))
            long_pos['quantity'] = max(self.min_quantity, round(long_pos['quantity'], 4))
            logger.info(f"Adjusted: Long Qty={long_pos['quantity']:.4f}, Short Qty={short_pos['quantity']:.4f}")

    def check_tp_sl_trailing(self, current_price, atr):
        for pos in self.positions[:]:
            stop_loss = pos['stop_loss']
            take_profit = pos['take_profit']
            side = pos['side']
            if side == 'Long':
                if current_price <= stop_loss:
                    self.close_position(pos, stop_loss, reason='Stop Loss Hit')
                    continue
                if current_price >= take_profit:
                    pos['take_profit'] = current_price + min(current_price * 0.03, 2 * atr)
                    pos['stop_loss'] = max(pos['stop_loss'], current_price - min(current_price * 0.0075, 0.5 * atr))
                    pos['first_target_hit'] = True
                if pos.get('first_target_hit', False):
                    pos['trailing_stop'] = max(pos['trailing_stop'], current_price - min(current_price * 0.0075, 0.5 * atr))
                    if current_price <= pos['trailing_stop']:
                        self.close_position(pos, pos['trailing_stop'], reason='Trailing Stop Hit')
            else:
                if current_price >= stop_loss:
                    self.close_position(pos, stop_loss, reason='Stop Loss Hit')
                    continue
                if current_price <= take_profit:
                    pos['take_profit'] = current_price - min(current_price * 0.03, 2 * atr)
                    pos['stop_loss'] = min(pos['stop_loss'], current_price + min(current_price * 0.0075, 0.5 * atr))
                    pos['first_target_hit'] = True
                if pos.get('first_target_hit', False):
                    pos['trailing_stop'] = min(pos['trailing_stop'], current_price + min(current_price * 0.0075, 0.5 * atr))
                    if current_price >= pos['trailing_stop']:
                        self.close_position(pos, pos['trailing_stop'], reason='Trailing Stop Hit')

    def check_total_pnl(self, current_price):
        total_pnl = 0
        for pos in self.positions:
            if pos['side'] == 'Long':
                pnl = (current_price - pos['entry_price']) * pos['quantity'] * self.leverage
            else:
                pnl = (pos['entry_price'] - current_price) * pos['quantity'] * self.leverage
            total_pnl += pnl
        if total_pnl >= self.initial_balance * 0.05:  # ۵٪ سود
            for pos in self.positions[:]:
                self.close_position(pos, current_price, reason='Total Profit Target')
        elif total_pnl <= -self.initial_balance * 0.03:  # ۳٪ ضرر
            for pos in self.positions[:]:
                self.close_position(pos, current_price, reason='Total Loss Limit')

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
        mean_return = returns.mean() * (365 * 24 * 60)
        std_return = returns.std() * np.sqrt(365 * 24 * 60) if returns.std() != 0 else 1.0
        sharpe_ratio = mean_return / std_return if std_return != 0 else 0.0
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
        logger.info("Starting Scalping Hedging backtest on 1m timeframe...")
        self.indicators = self.calculate_indicators(self.df_1m)
        if self.indicators is None:
            logger.error("Failed to calculate indicators")
            return

        min_data_length = 21  # برای EMA21
        for index, row in self.df_1m.iterrows():
            if index < min_data_length:
                continue
            current_price = row['close']
            timestamp = row['timestamp']
            self.candle_count += 1

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

            rsi = self.indicators['RSI'].iloc[index]
            ema9 = self.indicators['EMA9'].iloc[index]
            ema21 = self.indicators['EMA21'].iloc[index]
            atr = self.indicators['ATR'].iloc[index]

            # فیلتر ATR
            atr_threshold = current_price * 0.001  # ۰.۱٪ قیمت
            if atr < atr_threshold:
                logger.debug(f"No signal: ATR={atr:.2f} < {atr_threshold:.2f}")
                continue

            # تنظیم مارجین هر ۵ کندل
            if self.candle_count % self.adjust_interval == 0:
                self.adjust_margin(current_price)

            # بررسی استاپ‌لاس، تیک پروفیت و Trailing Stop
            self.check_tp_sl_trailing(current_price, atr)

            # بررسی مجموع PnL
            self.check_total_pnl(current_price)

            # بررسی شرایط ورود
            long_pos = next((p for p in self.positions if p['side'] == 'Long'), None)
            short_pos = next((p for p in self.positions if p['side'] == 'Short'), None)

            if not long_pos and not short_pos:
                if rsi < 45 or rsi > 55:
                    # باز کردن هر دو پوزیشن
                    quantity = self.calculate_position_size(current_price)
                    if quantity == 0:
                        logger.warning("Cannot open position: Zero quantity")
                        continue

                    # پوزیشن لانگ
                    stop_loss_distance = max(current_price * 0.015, atr)
                    take_profit_distance = min(current_price * 0.03, 2 * atr)
                    long_pos = {
                        'side': 'Long',
                        'quantity': quantity,
                        'entry_price': current_price,
                        'stop_loss': current_price - stop_loss_distance,
                        'take_profit': current_price + take_profit_distance,
                        'trailing_stop': current_price - stop_loss_distance,
                        'timestamp': timestamp,
                        'first_target_hit': False
                    }
                    self.positions.append(long_pos)
                    fee = self.fee_rate * (quantity * current_price)
                    self.balance -= fee
                    logger.info(f"Opened Long at {current_price}, Qty: {quantity:.4f}, SL: {long_pos['stop_loss']:.2f}, TP: {long_pos['take_profit']:.2f}, Fee: {fee:.4f}, Balance: {self.balance:.2f}")

                    # پوزیشن شورت
                    short_pos = {
                        'side': 'Short',
                        'quantity': quantity,
                        'entry_price': current_price,
                        'stop_loss': current_price + stop_loss_distance,
                        'take_profit': current_price - take_profit_distance,
                        'trailing_stop': current_price + stop_loss_distance,
                        'timestamp': timestamp,
                        'first_target_hit': False
                    }
                    self.positions.append(short_pos)
                    fee = self.fee_rate * (quantity * current_price)
                    self.balance -= fee
                    self.last_trade_time = timestamp
                    logger.info(f"Opened Short at {current_price}, Qty: {quantity:.4f}, SL: {short_pos['stop_loss']:.2f}, TP: {short_pos['take_profit']:.2f}, Fee: {fee:.4f}, Balance: {self.balance:.2f}")

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
    
    

    def plot_equity_comparison(timestamps, strategy_equity, hodl_values, title="Strategy vs HODL Equity Curve"):
        """
        Plot a comparison of strategy equity and HODL value over time.

        Parameters:
        - timestamps: List or Series of timestamps (e.g., from backtest data)
        - strategy_equity: List or Series of strategy equity values (in USDT)
        - hodl_values: List or Series of HODL values (in USDT)
        - title: Plot title (default: "Strategy vs HODL Equity Curve")
        """
        # Ensure inputs are pandas Series for consistent handling
        timestamps = pd.to_datetime(timestamps)
        strategy_equity = pd.Series(strategy_equity, index=timestamps)
        hodl_values = pd.Series(hodl_values, index=timestamps)

        # Create the plot
        plt.figure(figsize=(10, 6))
        plt.plot(timestamps, strategy_equity, label="Strategy Equity", color="blue", linewidth=1.5)
        plt.plot(timestamps, hodl_values, label="HODL Value", color="orange", linestyle="--", linewidth=1.5)

        # Customize the plot
        plt.title(title, fontsize=14, pad=10)
        plt.xlabel("Time", fontsize=12)
        plt.ylabel("Value (USDT)", fontsize=12)
        plt.grid(True, linestyle="--", alpha=0.7)
        plt.legend(fontsize=10)

        # Rotate x-axis labels for readability
        plt.xticks(rotation=45)

        # Adjust layout to prevent label cutoff
        plt.tight_layout()

        # Save the plot
        plt.savefig("equity_comparison.png", dpi=300, bbox_inches="tight")
        plt.close()

    # Example usage (assuming data from backtest):
    # plot_equity_comparison(df['timestamp'], df['equity'], df['hodl_value'])

if __name__ == "__main__":
    backtest = BacktestScalpingHedging(initial_balance=100, leverage=3, symbol='BTCUSDT')
    backtest.run_backtest()
    backtest.plot_equity_comparison()
