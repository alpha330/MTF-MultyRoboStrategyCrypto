import pandas as pd
import ta
import logging
import numpy as np
import matplotlib.pyplot as plt

# تنظیم لاگ با انکودینگ UTF-8
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('MTF_O1M_BACKTEST.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class BacktestBot:
    def __init__(
        self,
        initial_balance=500,
        leverage=3,
        risk_percent=0.2,
        fee_rate=0.0006,
        max_positions=5,
        ema_fast=8,
        ema_slow=21,
        adx_threshold=20,
        rsi_overbought=80,
        rsi_oversold=20
    ):
        self.initial_balance = initial_balance
        self.balance = initial_balance
        self.leverage = leverage
        self.risk_percent = risk_percent
        self.fee_rate = fee_rate
        self.max_positions = max_positions
        self.ema_fast = ema_fast
        self.ema_slow = ema_slow
        self.adx_threshold = adx_threshold
        self.rsi_overbought = rsi_overbought
        self.rsi_oversold = rsi_oversold
        self.btc_held = 0
        self.trades = []
        self.positions = []
        self.equity_history = []

        # لود و اعتبارسنجی داده‌ها
        try:
            self.df_1m = pd.read_csv('./BTCUSDT_1m_historical.csv')
            self.df_5m = pd.read_csv('./BTCUSDT_5m_historical.csv')
            self.df_15m = pd.read_csv('./BTCUSDT_15m_historical.csv')
            self.df_30m = pd.read_csv('./BTCUSDT_30m_historical.csv')
            self.df_1h = pd.read_csv('./BTCUSDT_1h_historical.csv')
            self.df_4h = pd.read_csv('./BTCUSDT_4h_historical.csv')

            # تبدیل تایم‌استمپ و پر کردن داده‌های گم‌شده
            for df, tf in [
                (self.df_1m, '1m'), (self.df_5m, '5m'), (self.df_15m, '15m'),
                (self.df_30m, '30m'), (self.df_1h, '1h'), (self.df_4h, '4h')
            ]:
                df['timestamp'] = pd.to_datetime(df['timestamp'], errors='coerce')
                df.dropna(subset=['timestamp'], inplace=True)
                df.sort_values('timestamp', inplace=True)
                df.ffill(inplace=True)  # پر کردن داده‌های گم‌شده
                self.validate_data(df, tf)

            logger.info(f"Loaded 1m data: {len(self.df_1m)} rows")
            logger.info(f"Loaded 5m data: {len(self.df_5m)} rows")
            logger.info(f"Loaded 15m data: {len(self.df_15m)} rows")
            logger.info(f"Loaded 30m data: {len(self.df_30m)} rows")
            logger.info(f"Loaded 1h data: {len(self.df_1h)} rows")
            logger.info(f"Loaded 4h data: {len(self.df_4h)} rows")

            # محاسبه اندیکاتورها یک‌بار برای همه
            self.calculate_all_indicators()

            # محاسبه HODL
            self.hodl_btc = initial_balance / self.df_1m['close'].iloc[0]
            self.hodl_value = 0
        except Exception as e:
            logger.error(f"Error loading data: {e}")
            raise

    def validate_data(self, df, timeframe):
        """اعتبارسنجی داده‌ها"""
        required_columns = ['timestamp', 'open', 'high', 'low', 'close', 'volume']
        if not all(col in df.columns for col in required_columns):
            raise ValueError(f"Missing required columns in {timeframe} data")
        if df['close'].isnull().any() or (df['close'] <= 0).any():
            raise ValueError(f"Invalid price data in {timeframe} (null or negative prices)")
        if df['volume'].isnull().any() or (df['volume'] < 0).any():
            raise ValueError(f"Invalid volume data in {timeframe} (null or negative volumes)")

    def calculate_all_indicators(self):
        """محاسبه یک‌باره اندیکاتورها برای همه تایم‌فریم‌ها"""
        for df, tf in [
            (self.df_1m, '1m'), (self.df_5m, '5m'), (self.df_15m, '15m'),
            (self.df_30m, '30m'), (self.df_1h, '1h'), (self.df_4h, '4h')
        ]:
            indicators = self.calculate_indicators(df, timeframe=tf)
            for key, value in indicators.items():
                df[key] = value
            logger.info(f"Calculated indicators for {tf}")

    def calculate_indicators(self, df, timeframe='1m'):
        indicators_data = {}
        # EMA 8 و EMA 21 (برای 1m)
        if len(df) >= self.ema_slow and timeframe == '1m':
            indicators_data['EMA_fast'] = ta.trend.EMAIndicator(df['close'], window=self.ema_fast).ema_indicator()
            indicators_data['EMA_slow'] = ta.trend.EMAIndicator(df['close'], window=self.ema_slow).ema_indicator()
        else:
            indicators_data['EMA_fast'] = pd.Series([float('nan')] * len(df), index=df.index)
            indicators_data['EMA_slow'] = pd.Series([float('nan')] * len(df), index=df.index)

        # EMA 50 و EMA 200
        if len(df) >= 200:
            indicators_data['EMA50'] = ta.trend.EMAIndicator(df['close'], window=50).ema_indicator()
            indicators_data['EMA200'] = ta.trend.EMAIndicator(df['close'], window=200).ema_indicator()
        else:
            indicators_data['EMA50'] = pd.Series([float('nan')] * len(df), index=df.index)
            indicators_data['EMA200'] = pd.Series([float('nan')] * len(df), index=df.index)

        # ATR (برای 1m)
        if len(df) >= 14 and timeframe == '1m':
            indicators_data['ATR'] = ta.volatility.AverageTrueRange(df['high'], df['low'], df['close'], window=14).average_true_range()
        else:
            indicators_data['ATR'] = pd.Series([float('nan')] * len(df), index=df.index)

        # ADX و +DI/-DI
        if len(df) >= 14:
            try:
                adx_indicator = ta.trend.ADXIndicator(df['high'], df['low'], df['close'], window=14)
                indicators_data['ADX'] = adx_indicator.adx()
                indicators_data['Plus_DI'] = adx_indicator.adx_pos()
                indicators_data['Minus_DI'] = adx_indicator.adx_neg()
            except Exception as e:
                logger.error(f"Error calculating ADX for {timeframe}: {e}")
                indicators_data['ADX'] = pd.Series([float('nan')] * len(df), index=df.index)
                indicators_data['Plus_DI'] = pd.Series([float('nan')] * len(df), index=df.index)
                indicators_data['Minus_DI'] = pd.Series([float('nan')] * len(df), index=df.index)
        else:
            indicators_data['ADX'] = pd.Series([float('nan')] * len(df), index=df.index)
            indicators_data['Plus_DI'] = pd.Series([float('nan')] * len(df), index=df.index)
            indicators_data['Minus_DI'] = pd.Series([float('nan')] * len(df), index=df.index)

        # Ichimoku Cloud (برای 4h)
        if len(df) >= 52 and timeframe == '4h':
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

        # RSI (برای 1m)
        if len(df) >= 9 and timeframe == '1m':
            indicators_data['RSI'] = ta.momentum.RSIIndicator(df['close'], window=9).rsi()
        else:
            indicators_data['RSI'] = pd.Series([float('nan')] * len(df), index=df.index)

        # Volume SMA10 (برای 1m)
        if len(df) >= 10 and timeframe == '1m':
            indicators_data['Volume_SMA10'] = ta.trend.SMAIndicator(df['volume'], window=10).sma_indicator()
        else:
            indicators_data['Volume_SMA10'] = pd.Series([float('nan')] * len(df), index=df.index)

        return indicators_data

    def check_higher_timeframe(self, timestamp):
        """بررسی تایم‌فریم‌های بالاتر برای سیگنال روند"""
        dfs = {
            '4h': self.df_4h[self.df_4h['timestamp'] <= timestamp].tail(400),
            '1h': self.df_1h[self.df_1h['timestamp'] <= timestamp].tail(400),
            '30m': self.df_30m[self.df_30m['timestamp'] <= timestamp].tail(400),
            '15m': self.df_15m[self.df_15m['timestamp'] <= timestamp].tail(400),
            '5m': self.df_5m[self.df_5m['timestamp'] <= timestamp].tail(400)
        }

        if any(len(df) < 200 for df in dfs.values()):
            logger.warning(f"Insufficient data for higher timeframes at {timestamp}")
            return 'Neutral'

        # تایم‌فریم 4 ساعته (Ichimoku)
        df_4h = dfs['4h']
        signal_4h = 'Neutral'
        if not df_4h.empty:
            tenkan_sen = df_4h['Tenkan_sen'].iloc[-1]
            kijun_sen = df_4h['Kijun_sen'].iloc[-1]
            senkou_span_a = df_4h['Senkou_Span_A'].iloc[-1]
            senkou_span_b = df_4h['Senkou_Span_B'].iloc[-1]
            chikou_span = df_4h['Chikou_Span'].iloc[-1]
            close_4h = df_4h['close'].iloc[-1]
            close_26_ago = df_4h['close'].iloc[-27] if len(df_4h) > 27 else close_4h

            if not any(pd.isna([close_4h, senkou_span_a, senkou_span_b, tenkan_sen, kijun_sen, chikou_span, close_26_ago])):
                if (close_4h > senkou_span_a and close_4h > senkou_span_b and
                    tenkan_sen > kijun_sen and chikou_span > close_26_ago and
                    senkou_span_a > senkou_span_b):
                    signal_4h = 'Long'
                elif (close_4h < senkou_span_a and close_4h < senkou_span_b and
                      tenkan_sen < kijun_sen and chikou_span < close_26_ago and
                      senkou_span_a < senkou_span_b):
                    signal_4h = 'Short'

        if signal_4h == 'Neutral':
            return 'Neutral'

        # بررسی تایم‌فریم‌های میانی
        for tf, df in dfs.items():
            if tf == '4h':
                continue
            ema50 = df['EMA50'].iloc[-1]
            ema200 = df['EMA200'].iloc[-1]
            adx = df['ADX'].iloc[-1]
            plus_di = df['Plus_DI'].iloc[-1]
            minus_di = df['Minus_DI'].iloc[-1]

            if any(pd.isna([ema50, ema200, adx, plus_di, minus_di])):
                logger.info(f"Indicator data incomplete for {tf} at {timestamp}")
                return 'Neutral'

            if signal_4h == 'Long' and not (ema50 > ema200 and adx > self.adx_threshold and plus_di > minus_di):
                logger.info(f"Long trend not confirmed in {tf} at {timestamp}")
                return 'Neutral'
            elif signal_4h == 'Short' and not (ema50 < ema200 and adx > self.adx_threshold and minus_di > plus_di):
                logger.info(f"Short trend not confirmed in {tf} at {timestamp}")
                return 'Neutral'

        return signal_4h

    def calculate_metrics(self):
        """محاسبه معیارهای عملکرد"""
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
        sharpe_ratio = (returns.mean() / returns.std()) * np.sqrt(365) if returns.std() != 0 else 0.0

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

    def plot_equity_curve(self):
        """رسم نمودار Equity Curve"""
        plt.figure(figsize=(10, 6))
        plt.plot(self.equity_history, label='Equity Curve')
        plt.title('Equity Curve')
        plt.xlabel('Trade Number')
        plt.ylabel('Equity (USDT)')
        plt.legend()
        plt.grid()
        plt.savefig('equity_curve.png')
        plt.close()
        logger.info("Equity curve saved as equity_curve.png")

    def save_trades(self):
        """ذخیره معاملات در فایل CSV"""
        trades_df = pd.DataFrame(self.trades)
        trades_df.to_csv('trades_history.csv', index=False, encoding='utf-8')
        logger.info("Trades saved to trades_history.csv")

    def run_backtest(self):
        """اجرای بک‌تست"""
        logger.info("Starting backtest...")
        for index, row in self.df_1m.iterrows():
            timestamp = row['timestamp']
            current_price = row['close']
            current_volume = row['volume']

            # محاسبه سود/زیان غیرواقعی
            unrealized_pnl = 0.0
            for pos in self.positions:
                if pos['type'] == 'Long':
                    unrealized_pnl += (current_price - pos['entry_price']) * pos['quantity'] * self.leverage
                elif pos['type'] == 'Short':
                    unrealized_pnl += (pos['entry_price'] - current_price) * pos['quantity'] * self.leverage
            current_equity = self.balance + unrealized_pnl
            self.equity_history.append(current_equity)

            # دسترسی به اندیکاتورهای از پیش محاسبه‌شده
            df_1m = self.df_1m[self.df_1m['timestamp'] <= timestamp].tail(200)
            if len(df_1m) < self.ema_slow:
                logger.debug(f"Skipping timestamp {timestamp}: insufficient candles")
                continue

            ema_fast = df_1m['EMA_fast'].iloc[-1]
            ema_slow = df_1m['EMA_slow'].iloc[-1]
            ema_fast_prev = df_1m['EMA_fast'].iloc[-2] if len(df_1m) > 1 else float('nan')
            ema_slow_prev = df_1m['EMA_slow'].iloc[-2] if len(df_1m) > 1 else float('nan')
            atr_1m = df_1m['ATR'].iloc[-1]
            adx_1m = df_1m['ADX'].iloc[-1]
            rsi_1m = df_1m['RSI'].iloc[-1]
            volume_sma10 = df_1m['Volume_SMA10'].iloc[-1]

            higher_tf_signal = self.check_higher_timeframe(timestamp)

            # تولید سیگنال
            signal = 'Neutral'
            if (not pd.isna(ema_fast) and not pd.isna(ema_slow) and not pd.isna(ema_fast_prev) and
                not pd.isna(ema_slow_prev) and not pd.isna(adx_1m) and not pd.isna(rsi_1m) and
                not pd.isna(volume_sma10)):
                if (ema_fast_prev <= ema_slow_prev and ema_fast > ema_slow and
                    adx_1m > self.adx_threshold and rsi_1m > 50 and current_volume > volume_sma10 and
                    higher_tf_signal == 'Long'):
                    signal = 'Long'
                elif (ema_fast_prev >= ema_slow_prev and ema_fast < ema_slow and
                      adx_1m > self.adx_threshold and rsi_1m < 50 and current_volume > volume_sma10 and
                      higher_tf_signal == 'Short'):
                    signal = 'Short'

            # باز کردن پوزیشن جدید
            if signal != 'Neutral' and len(self.positions) < self.max_positions:
                if self.balance <= 0:
                    logger.warning("Balance is zero or negative, cannot open new position.")
                    break
                position_size = (self.balance * self.risk_percent) * self.leverage
                quantity = position_size / current_price
                entry_price = current_price
                stop_loss = entry_price - (5 * atr_1m) if signal == 'Long' else entry_price + (5 * atr_1m)
                take_profit = entry_price + (6 * atr_1m) if signal == 'Long' else entry_price - (6 * atr_1m)
                highest_price = entry_price if signal == 'Long' else float('inf')
                lowest_price = entry_price if signal == 'Short' else 0
                trailing_stop = stop_loss
                fee = self.fee_rate * position_size
                self.balance -= fee

                self.positions.append({
                    'type': signal,
                    'entry_price': entry_price,
                    'quantity': quantity,
                    'stop_loss': stop_loss,
                    'take_profit': take_profit,
                    'highest_price': highest_price,
                    'lowest_price': lowest_price,
                    'trailing_stop': trailing_stop,
                    'entry_timestamp': timestamp
                })
                logger.info(f"Opened {signal} at {entry_price}, qty: {quantity:.4f}, SL: {stop_loss:.2f}, TP: {take_profit:.2f}, fee: {fee:.4f}, balance: {self.balance:.2f}")

            # بررسی پوزیشن‌های باز برای خروج
            positions_to_close = []
            for pos in self.positions:
                # به‌روزرسانی Trailing Stop
                if pos['type'] == 'Long':
                    pos['highest_price'] = max(pos['highest_price'], current_price)
                    pos['trailing_stop'] = max(pos['trailing_stop'], pos['highest_price'] - (5 * atr_1m))
                elif pos['type'] == 'Short':
                    pos['lowest_price'] = min(pos['lowest_price'], current_price)
                    pos['trailing_stop'] = min(pos['trailing_stop'], pos['lowest_price'] + (5 * atr_1m))

                # محاسبه سود فعلی (درصد)
                current_profit = 0.0
                if pos['type'] == 'Long':
                    current_profit = ((current_price - pos['entry_price']) / pos['entry_price']) * 100
                elif pos['type'] == 'Short':
                    current_profit = ((pos['entry_price'] - current_price) / pos['entry_price']) * 100

                # شرایط خروج
                exit_position = False
                if pos['type'] == 'Long' and not pd.isna(rsi_1m) and rsi_1m > self.rsi_overbought and current_profit >= 1.0:
                    exit_position = True
                    logger.info(f"Closing Long due to overbought RSI: {rsi_1m}")
                elif pos['type'] == 'Short' and not pd.isna(rsi_1m) and rsi_1m < self.rsi_oversold and current_profit >= 1.0:
                    exit_position = True
                    logger.info(f"Closing Short due to oversold RSI: {rsi_1m}")

                should_close = False
                if pos['type'] == 'Long':
                    if (exit_position or current_price <= pos['trailing_stop'] or
                        current_price >= pos['take_profit']):
                        should_close = True
                elif pos['type'] == 'Short':
                    if (exit_position or current_price >= pos['trailing_stop'] or
                        current_price <= pos['take_profit']):
                        should_close = True

                if should_close:
                    position_size = pos['quantity'] * pos['entry_price']
                    if pos['type'] == 'Long':
                        profit = (current_price - pos['entry_price']) * pos['quantity'] * self.leverage
                    else:
                        profit = (pos['entry_price'] - current_price) * pos['quantity'] * self.leverage
                    fee = self.fee_rate * (position_size + (pos['quantity'] * current_price))
                    net_profit = profit - fee
                    self.balance += profit - fee
                    self.trades.append({
                        'type': pos['type'],
                        'profit': net_profit,
                        'entry_price': pos['entry_price'],
                        'exit_price': current_price,
                        'entry_timestamp': pos['entry_timestamp'],
                        'exit_timestamp': timestamp
                    })
                    logger.info(f"Closed {pos['type']} at {current_price}, profit: {profit:.2f}, fee: {fee:.4f}, net profit: {net_profit:.2f}, balance: {self.balance:.2f}")
                    positions_to_close.append(pos)

            self.positions = [pos for pos in self.positions if pos not in positions_to_close]

        # محاسبه ارزش نهایی HODL
        initial_price = self.df_1m['close'].iloc[0]
        final_price = self.df_1m['close'].iloc[-1]
        hodl_value = (self.initial_balance / initial_price) * final_price

        # محاسبه معیارها
        metrics = self.calculate_metrics()

        # ذخیره و رسم نتایج
        self.save_trades()
        self.plot_equity_curve()

        logger.info("Backtest completed!")
        logger.info(f"Initial balance: {self.initial_balance:.2f} USDT")
        logger.info(f"Final balance (strategy): {self.balance:.2f} USDT")
        logger.info(f"Final value (HODL): {hodl_value:.2f} USDT")
        logger.info(f"Total trades: {metrics['total_trades']}")
        logger.info(f"Win rate: {metrics['win_rate']:.2f}%")
        logger.info(f"Max drawdown: {metrics['max_drawdown']:.2f}%")
        logger.info(f"Sharpe ratio: {metrics['sharpe_ratio']:.2f}")
        logger.info(f"Profit factor: {metrics['profit_factor']:.2f}")

if __name__ == "__main__":
    backtest = BacktestBot(
        initial_balance=500,
        leverage=3,
        risk_percent=0.2,
        fee_rate=0.0006,
        max_positions=5,
        ema_fast=8,
        ema_slow=21,
        adx_threshold=20,
        rsi_overbought=80,
        rsi_oversold=20
    )
    backtest.run_backtest()