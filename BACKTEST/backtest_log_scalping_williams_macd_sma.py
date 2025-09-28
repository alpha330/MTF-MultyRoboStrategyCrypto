import pandas as pd
import numpy as np
import logging

# --- Setup Logging ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('backtest_log_mtf_engulfing.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# --- Numpy-based Helper Functions ---
def ema_np(series, length):
    """محاسبه میانگین متحرک نمایی (EMA) با استفاده از Numpy برای سرعت بیشتر"""
    alpha = 2 / (length + 1)
    out = np.zeros_like(series, dtype=float)
    if len(series) > 0:
        out[0] = series[0]
        for i in range(1, len(series)):
            out[i] = alpha * series[i] + (1 - alpha) * out[i-1]
    return out

def atr_np(high, low, close, length):
    """محاسبه شاخص ATR (Average True Range) با استفاده از Numpy"""
    tr = np.maximum(high[1:] - low[1:], np.maximum(np.abs(high[1:] - close[:-1]), np.abs(low[1:] - close[:-1])))
    atr = np.zeros_like(close, dtype=float)
    if len(tr) >= length - 1 > 0:
        atr[length-1] = np.mean(tr[:length-1])
        for i in range(length, len(atr)):
            atr[i] = (atr[i-1] * (length - 1) + tr[i-1]) / length
    return atr

class BacktestMTFEngulfing:
    """
    یک چارچوب بک‌تست شیءگرا برای استراتژی چند تایم‌فریم 
    که از الگوی کندل پوششی برای تایید ورود در پولبک استفاده می‌کند.
    """
    def __init__(self, low_tf_file, high_tf_file, initial_balance=100, leverage=3, fee_rate=0.0002, symbol='BTCUSDT'):
        self.initial_balance = initial_balance
        self.balance = initial_balance
        self.leverage = leverage
        self.fee_rate = fee_rate
        self.positions = []
        self.trades = []
        self.equity_history = []
        self.symbol = symbol

        # پارامترهای استراتژی و مدیریت ریسک
        self.trend_ema_len = 50
        self.ema_pullback_len = 20
        self.atr_len = 14
        self.atr_mult_sl = 2.0  # ضریب ATR برای حد ضرر
        self.reward_ratio = 1.5 # نسبت ریوارد به ریسک برای حد سود

        try:
            logger.info("Loading data files...")
            df_low = pd.read_csv(low_tf_file, index_col='timestamp', parse_dates=True)
            df_high = pd.read_csv(high_tf_file, index_col='timestamp', parse_dates=True)
            self.df = self._prepare_data(df_low, df_high)
            self.df = self._calculate_indicators()
            logger.info(f"Data prepared successfully. Total rows: {len(self.df)}")
        except Exception as e:
            logger.error(f"Error during initialization: {e}")
            raise

        # محاسبه HODL
        initial_price = self.df['close'].iloc[0]
        self.hodl_value = (self.initial_balance / initial_price) * self.df['close'].iloc[-1]

    def _determine_trend_high_tf(self, df_high):
        """تشخیص روند در تایم‌فریم بالا"""
        logger.info(f"Calculating trend on high TF with Price vs EMA({self.trend_ema_len}).")
        ema_trend = ema_np(df_high['close'].values, self.trend_ema_len)
        df_high['trend'] = 0
        df_high.loc[df_high['close'] > ema_trend, 'trend'] = 1  # روند صعودی
        df_high.loc[df_high['close'] < ema_trend, 'trend'] = -1 # روند نزولی
        return df_high[['trend']]

    def _prepare_data(self, df_low, df_high):
        """آماده‌سازی و ادغام داده‌های دو تایم‌فریم"""
        df_high_trend = self._determine_trend_high_tf(df_high)
        logger.info("Merging high timeframe trend into low timeframe data...")
        df_merged = pd.merge_asof(df_low, df_high_trend, left_index=True, right_index=True, direction='backward')
        df_merged['trend'] = df_merged['trend'].fillna(0)
        return df_merged
        
    def _calculate_indicators(self):
        """محاسبه اندیکاتورهای مورد نیاز برای استراتژی"""
        df_copy = self.df.copy()
        df_copy['ema_pullback'] = ema_np(df_copy['close'].values, self.ema_pullback_len)
        df_copy['atr'] = atr_np(df_copy['high'].values, df_copy['low'].values, df_copy['close'].values, self.atr_len)
        return df_copy

    def close_position(self, position, exit_price, reason='Manual'):
        """بستن یک پوزیشن باز و ثبت معامله"""
        quantity = position['quantity']
        entry_price = position['entry_price']
        side = position['side']
        
        pnl_multiplier = 1 if side == 'Long' else -1
        pnl = (exit_price - entry_price) * quantity * pnl_multiplier * self.leverage
        
        entry_fee = entry_price * quantity * self.fee_rate * self.leverage
        exit_fee = exit_price * quantity * self.fee_rate * self.leverage
        total_pnl = pnl - entry_fee - exit_fee
        
        self.balance += total_pnl
        if self.balance < 0:
            logger.warning(f"Balance became negative: {self.balance:.2f}")
            self.balance = 0

        self.trades.append({
            'type': side, 'profit': total_pnl, 'entry_price': entry_price,
            'exit_price': exit_price, 'reason': reason
        })
        self.positions.remove(position)
        logger.info(f"Closed {side} at {exit_price:.2f}, Qty: {quantity:.4f}, PnL: {total_pnl:.2f}, Reason: {reason}, Balance: {self.balance:.2f}")

    def run_backtest(self):
        """اجرای حلقه اصلی بک‌تست"""
        logger.info("Starting MTF Engulfing Pattern backtest...")
        
        for i in range(2, len(self.df)):
            current_row = self.df.iloc[i]
            prev_row = self.df.iloc[i-1]
            prev_prev_row = self.df.iloc[i-2]

            current_price = current_row['close']

            # مدیریت پوزیشن‌های باز (حد سود و ضرر)
            for pos in self.positions[:]:
                if pos['side'] == 'Long':
                    if current_price <= pos['stop_loss']:
                        self.close_position(pos, pos['stop_loss'], reason='Stop Loss')
                    elif current_price >= pos['take_profit']:
                        self.close_position(pos, pos['take_profit'], reason='Take Profit')
                elif pos['side'] == 'Short':
                    if current_price >= pos['stop_loss']:
                        self.close_position(pos, pos['stop_loss'], reason='Stop Loss')
                    elif current_price <= pos['take_profit']:
                        self.close_position(pos, pos['take_profit'], reason='Take Profit')

            # اگر پوزیشنی باز است، به دنبال سیگنال جدید نگرد
            if self.positions:
                continue

            # شرایط سیگنال ورود
            trend = prev_row['trend']
            signal = None

            # شرایط پولبک: کندل دو تا قبل (t-2) باید به ناحیه EMA رسیده باشد.
            pullback_long_area = prev_prev_row['low'] < prev_prev_row['ema_pullback']
            pullback_short_area = prev_prev_row['high'] > prev_prev_row['ema_pullback']

            # شرایط الگوی پوششی صعودی (Bullish Engulfing)
            bullish_engulfing = (prev_row['close'] > prev_row['open']) and \
                                (prev_prev_row['open'] > prev_prev_row['close']) and \
                                (prev_row['close'] > prev_prev_row['open']) and \
                                (prev_row['open'] < prev_prev_row['close'])

            # شرایط الگوی پوششی نزولی (Bearish Engulfing)
            bearish_engulfing = (prev_row['open'] > prev_row['close']) and \
                               (prev_prev_row['close'] > prev_prev_row['open']) and \
                               (prev_row['open'] > prev_prev_row['close']) and \
                               (prev_row['close'] < prev_prev_row['open'])
            
            if trend == 1 and pullback_long_area and bullish_engulfing:
                signal = 'Long'
            elif trend == -1 and pullback_short_area and bearish_engulfing:
                signal = 'Short'

            if signal:
                if self.balance <= 0:
                    logger.warning("Balance is zero. Stopping backtest.")
                    break
                
                entry_price = current_row['open'] # ورود در ابتدای کندل بعدی
                atr_value = prev_row['atr']
                
                if signal == 'Long':
                    stop_loss = entry_price - (atr_value * self.atr_mult_sl)
                    take_profit = entry_price + ((entry_price - stop_loss) * self.reward_ratio)
                else: # Short
                    stop_loss = entry_price + (atr_value * self.atr_mult_sl)
                    take_profit = entry_price - ((stop_loss - entry_price) * self.reward_ratio)

                # مدیریت ریسک و حجم پوزیشن (مثلا ۱٪ از بالانس)
                risk_amount_per_trade = self.balance * 0.01
                position_size_usd = risk_amount_per_trade * self.leverage
                quantity = position_size_usd / entry_price
                
                position = {
                    'side': signal, 'quantity': quantity, 'entry_price': entry_price,
                    'stop_loss': stop_loss, 'take_profit': take_profit,
                }
                self.positions.append(position)
                logger.info(f"Opened {signal} at {entry_price:.2f}, Qty: {quantity:.4f}, SL: {stop_loss:.2f}, TP: {take_profit:.2f}, Balance: {self.balance:.2f}")

    def report_results(self):
        """گزارش نتایج نهایی بک‌تست"""
        if not self.trades:
            logger.warning("No trades were executed.")
            return

        df_trades = pd.DataFrame(self.trades)
        total_trades = len(df_trades)
        wins = len(df_trades[df_trades['profit'] > 0])
        win_rate = (wins / total_trades) * 100 if total_trades > 0 else 0

        logger.info("--- Backtest Results ---")
        logger.info(f"Initial Balance: {self.initial_balance:.2f} USDT")
        logger.info(f"Final Balance: {self.balance:.2f} USDT")
        logger.info(f"HODL Final Value: {self.hodl_value:.2f} USDT")
        logger.info(f"Total Trades: {total_trades}")
        logger.info(f"Win Rate: {win_rate:.2f}%")
        
        gross_profit = df_trades[df_trades['profit'] > 0]['profit'].sum()
        gross_loss = abs(df_trades[df_trades['profit'] < 0]['profit'].sum())
        profit_factor = gross_profit / gross_loss if gross_loss != 0 else float('inf')
        logger.info(f"Profit Factor: {profit_factor:.2f}")


if __name__ == "__main__":
    low_tf_file = input("Enter LOW timeframe CSV filename (e.g., 5min_data.csv): ")
    high_tf_file = input("Enter HIGH timeframe CSV filename (e.g., 15min_data.csv): ")

    backtest = BacktestMTFEngulfing(
        low_tf_file=low_tf_file,
        high_tf_file=high_tf_file,
        initial_balance=100,
        leverage=5
    )
    backtest.run_backtest()
    backtest.report_results()

