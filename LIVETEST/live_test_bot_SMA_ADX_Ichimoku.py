import ccxt
import pandas as pd
import ta
import logging
import time
from datetime import datetime, timezone, timedelta
import os
from dotenv import load_dotenv

# تنظیم لاگ
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('live_test_log_SMA_ADX_Ichimoku.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# لود متغیرهای محیطی (API Key و Secret)
load_dotenv()
API_KEY = os.getenv('BYBIT_TESTNET_API_KEY')
API_SECRET = os.getenv('BYBIT_TESTNET_API_SECRET')

def get_utc_timestamp():
    utc_now = datetime.now(timezone.utc)
    return int(utc_now.timestamp() * 1000)

def wait_for_next_minute():
    """صبر کردن تا شروع دقیقه بعدی"""
    now = datetime.now(timezone.utc)
    seconds_until_next_minute = 60 - now.second
    logger.debug(f"Waiting {seconds_until_next_minute} seconds until next minute")
    time.sleep(seconds_until_next_minute)

class LiveTestBot:
    def __init__(self, symbol='BTC/USDT:USDT', initial_balance=500, leverage=3, risk_percent=0.2, fee_rate=0.0006):
        self.symbol = symbol
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
        self.equity_history = []

        # تنظیم صرافی Bybit
        self.exchange = ccxt.bybit({
            'apiKey': API_KEY,
            'secret': API_SECRET,
            'enableRateLimit': True,
        })
        self.exchange.set_sandbox_mode(True)  # استفاده از تست‌نت
        self.exchange.nonce = get_utc_timestamp
        self.exchange.load_markets()

        if self.symbol not in self.exchange.markets:
            logger.error(f"Symbol {self.symbol} does not exist on Bybit")
            raise ValueError(f"Symbol {self.symbol} does not exist on Bybit")

        # دیتافریم‌ها برای ذخیره داده‌ها
        self.df_1m = pd.DataFrame(columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        self.df_15m = pd.DataFrame(columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        self.df_1h = pd.DataFrame(columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])

        # لود داده‌های تاریخی یک ماه
        self.load_historical_data()

        # محاسبه HODL با قیمت اولیه
        initial_price = self.df_1m['close'].iloc[0]  # قیمت اولین کندل
        self.hodl_btc = initial_balance / initial_price
        self.hodl_value = 0
        logger.info(f"Initial price for HODL calculation: {initial_price}")

    def fetch_ohlcv(self, timeframe, limit=1000, since=None):
        try:
            ohlcv = self.exchange.fetch_ohlcv(self.symbol, timeframe, since=since, limit=limit)
            df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            logger.info(f"Fetched {len(df)} candles for {timeframe} since {since}")
            if not df.empty:
                logger.debug(f"Last candle timestamp for {timeframe}: {df['timestamp'].iloc[-1]}")
            return df
        except Exception as e:
            logger.error(f"Error fetching OHLCV for {timeframe}: {e}")
            return pd.DataFrame()

    def load_historical_data(self):
        # محاسبه زمان یک ماه قبل
        now = datetime.now(timezone.utc)
        one_month_ago = now - timedelta(days=30)
        since_timestamp = int(one_month_ago.timestamp() * 1000)

        # لود داده‌های تاریخی برای هر تایم‌فریم
        self.df_1m = self.fetch_ohlcv('1m', since=since_timestamp)
        self.df_15m = self.fetch_ohlcv('15m', since=since_timestamp)
        self.df_1h = self.fetch_ohlcv('1h', since=since_timestamp)

        # مرتب‌سازی و حذف داده‌های تکراری
        for df in [self.df_1m, self.df_15m, self.df_1h]:
            if not df.empty:
                df.sort_values('timestamp', inplace=True)
                df.drop_duplicates(subset='timestamp', keep='last', inplace=True)
                logger.info(f"Loaded {len(df)} historical candles")

    def update_dataframes(self):
        # گرفتن داده‌های جدید و آپدیت دیتافریم‌ها
        for timeframe, df in [('1m', self.df_1m), ('15m', self.df_15m), ('1h', self.df_1h)]:
            new_data = self.fetch_ohlcv(timeframe, limit=1, since=int(df['timestamp'].iloc[-1].timestamp() * 1000) if not df.empty else None)
            if not new_data.empty:
                new_timestamp = new_data.iloc[-1]['timestamp']
                if df.empty or new_timestamp > df['timestamp'].iloc[-1]:
                    df.loc[len(df)] = new_data.iloc[-1]
                    if len(df) > 200:
                        df.drop(df.index[0], inplace=True)
                        df.reset_index(drop=True, inplace=True)
                    logger.info(f"Updated {timeframe} dataframe with new candle at {new_timestamp}")
                else:
                    logger.debug(f"No new candle for {timeframe} at {new_timestamp}")

    def calculate_indicators(self, df, timeframe='1m'):
        indicators_data = {}
        if len(df) >= 30:
            indicators_data['SMA10'] = ta.trend.SMAIndicator(df['close'], window=10).sma_indicator()
            indicators_data['SMA30'] = ta.trend.SMAIndicator(df['close'], window=30).sma_indicator()
        else:
            indicators_data['SMA10'] = pd.Series([float('nan')] * len(df), index=df.index)
            indicators_data['SMA30'] = pd.Series([float('nan')] * len(df), index=df.index)

        if len(df) >= 200:
            indicators_data['EMA50'] = ta.trend.EMAIndicator(df['close'], window=50).ema_indicator()
            indicators_data['EMA200'] = ta.trend.EMAIndicator(df['close'], window=200).ema_indicator()
        else:
            indicators_data['EMA50'] = pd.Series([float('nan')] * len(df), index=df.index)
            indicators_data['EMA200'] = pd.Series([float('nan')] * len(df), index=df.index)

        if len(df) >= 14:
            indicators_data['ATR'] = ta.volatility.AverageTrueRange(df['high'], df['low'], df['close'], window=14).average_true_range()
            adx_indicator = ta.trend.ADXIndicator(df['high'], df['low'], df['close'], window=14)
            indicators_data['ADX'] = adx_indicator.adx()
            indicators_data['Plus_DI'] = adx_indicator.adx_pos()
            indicators_data['Minus_DI'] = adx_indicator.adx_neg()
        else:
            indicators_data['ATR'] = pd.Series([float('nan')] * len(df), index=df.index)
            indicators_data['ADX'] = pd.Series([float('nan')] * len(df), index=df.index)
            indicators_data['Plus_DI'] = pd.Series([float('nan')] * len(df), index=df.index)
            indicators_data['Minus_DI'] = pd.Series([float('nan')] * len(df), index=df.index)

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

    def run_live_test(self):
        logger.info("Starting live test with historical data from one month ago...")

        # پیش‌محاسبه شاخص‌ها برای کل دیتافریم
        indicators_1m = self.calculate_indicators(self.df_1m, timeframe='1m')

        position = None
        entry_price = 0.0
        quantity = 0.0
        stop_loss = 0.0
        take_profit = 0.0

        # اجرای تست روی داده‌های تاریخی
        min_data_length = 52  # حداقل تعداد کندل برای Ichimoku
        for index, row in self.df_1m.iterrows():
            if index < min_data_length - 1:  # صبر تا وقتی که داده‌ها کافی باشه
                continue
            timestamp = row['timestamp']
            current_price = row['close']
            current_volume = row['volume']

            # محاسبه equity
            if position == 'Long':
                unrealized_pnl = (current_price - entry_price) * quantity * self.leverage
            elif position == 'Short':
                unrealized_pnl = (entry_price - current_price) * quantity * self.leverage
            else:
                unrealized_pnl = 0.0
            current_equity = self.balance + unrealized_pnl
            self.equity_history.append(current_equity)

            sma10_1m = indicators_1m['SMA10'].iloc[index]
            sma30_1m = indicators_1m['SMA30'].iloc[index]
            sma10_prev_1m = indicators_1m['SMA10'].iloc[index - 1] if index > 0 else float('nan')
            sma30_prev_1m = indicators_1m['SMA30'].iloc[index - 1] if index > 0 else float('nan')
            atr_1m = indicators_1m['ATR'].iloc[index]
            adx_1m = indicators_1m['ADX'].iloc[index]
            rsi_1m = indicators_1m['RSI'].iloc[index]

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
                if position == 'Long':
                    self.highest_price = max(self.highest_price, current_price)
                    self.trailing_stop = max(self.trailing_stop, self.highest_price - (5 * atr_1m))
                elif position == 'Short':
                    self.lowest_price = min(self.lowest_price, current_price)
                    self.trailing_stop = min(self.trailing_stop, self.lowest_price + (5 * atr_1m))

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

        # ادامه با داده‌های لایو
        while True:
            try:
                wait_for_next_minute()
                self.update_dataframes()

                if self.df_1m.empty:
                    logger.warning("No data in 1m dataframe, retrying...")
                    continue

                timestamp = self.df_1m['timestamp'].iloc[-1]
                current_price = self.df_1m['close'].iloc[-1]
                current_volume = self.df_1m['volume'].iloc[-1]

                # محاسبه equity
                if position == 'Long':
                    unrealized_pnl = (current_price - entry_price) * quantity * self.leverage
                elif position == 'Short':
                    unrealized_pnl = (entry_price - current_price) * quantity * self.leverage
                else:
                    unrealized_pnl = 0.0
                current_equity = self.balance + unrealized_pnl
                self.equity_history.append(current_equity)

                indicators_1m = self.calculate_indicators(self.df_1m, timeframe='1m')
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
                    if position == 'Long':
                        self.highest_price = max(self.highest_price, current_price)
                        self.trailing_stop = max(self.trailing_stop, self.highest_price - (5 * atr_1m))
                    elif position == 'Short':
                        self.lowest_price = min(self.lowest_price, current_price)
                        self.trailing_stop = min(self.trailing_stop, self.lowest_price + (5 * atr_1m))

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

                # گزارش معیارها هر 5 دقیقه
                if len(self.equity_history) % 300 == 0:
                    metrics = self.calculate_metrics()
                    logger.info(f"--- Live Test Metrics ---")
                    logger.info(f"Current Balance: {self.balance:.2f} USDT")
                    logger.info(f"Total Trades: {metrics['total_trades']}")
                    logger.info(f"Win Rate: {metrics['win_rate']:.2f}%")
                    logger.info(f"Maximum Drawdown: {metrics['max_drawdown']:.2f}%")
                    logger.info(f"Sharpe Ratio: {metrics['sharpe_ratio']:.2f}")
                    logger.info(f"Profit Factor: {metrics['profit_factor']:.2f}")

            except Exception as e:
                logger.error(f"Error in live test: {e}")
                time.sleep(60)

if __name__ == "__main__":
    live_test = LiveTestBot(initial_balance=500, leverage=3)
    try:
        live_test.run_live_test()
    except KeyboardInterrupt:
        logger.info("Live test stopped by user.")
        metrics = live_test.calculate_metrics()
        logger.info("--- Final Live Test Metrics ---")
        logger.info(f"Final Balance: {live_test.balance:.2f} USDT")
        logger.info(f"Total Trades: {metrics['total_trades']}")
        logger.info(f"Win Rate: {metrics['win_rate']:.2f}%")
        logger.info(f"Maximum Drawdown: {metrics['max_drawdown']:.2f}%")
        logger.info(f"Sharpe Ratio: {metrics['sharpe_ratio']:.2f}")
        logger.info(f"Profit Factor: {metrics['profit_factor']:.2f}")