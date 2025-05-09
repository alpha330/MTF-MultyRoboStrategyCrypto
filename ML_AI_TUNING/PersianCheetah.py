import pandas as pd
import vectorbt as vbt
import numpy as np
import optuna
from ta.momentum import RSIIndicator
from ta.trend import IchimokuIndicator, SMAIndicator
from ta.volatility import BollingerBands, AverageTrueRange
from ta.volume import OnBalanceVolumeIndicator
import ccxt.async_support as ccxt_async
import asyncio
import logging

# تنظیم لاگ
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# تابع گرفتن دیتا از Bybit
async def fetch_bybit_data(symbol='BTC/USDT', timeframe='1m', start_date='2022-05-01'):
    exchange = ccxt_async.bybit({'enableRateLimit': True})
    since = int(pd.to_datetime(start_date).timestamp() * 1000)
    ohlcv = await exchange.fetch_ohlcv(symbol, timeframe, since=since, limit=1000, params={'category': 'linear'})
    df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    df.set_index('timestamp', inplace=True)
    await exchange.close()
    return df

# تابع محاسبه اندیکاتورها
def calculate_indicators(df, rsi_window, macd_fast, macd_slow, macd_signal, bb_window, bb_alpha, tenkan_window, kijun_window):
    indicators = {}
    indicators['rsi'] = RSIIndicator(df['close'], window=rsi_window).rsi()
    macd = vbt.MACD.run(df['close'], fast_window=macd_fast, slow_window=macd_slow, signal_window=macd_signal)
    indicators['macd'] = macd.macd
    indicators['macd_signal'] = macd.signal
    bb = BollingerBands(df['close'], window=bb_window, window_dev=bb_alpha)
    indicators['bb_upper'] = bb.bollinger_hband()
    indicators['bb_middle'] = bb.bollinger_mavg()
    indicators['bb_lower'] = bb.bollinger_lband()
    indicators['obv'] = OnBalanceVolumeIndicator(df['close'], df['volume']).on_balance_volume()
    indicators['obv_ma'] = SMAIndicator(indicators['obv'], window=20).sma_indicator()
    ichimoku = IchimokuIndicator(df['high'], df['low'], tenkan_window=tenkan_window, kijun_window=kijun_window)
    # استفاده از ichimoku_a به جای tenkan_sen و kijun_sen
    indicators['tenkan_sen'] = ichimoku.ichimoku_a()  # این خطا داره، باید اصلاح بشه
    indicators['kijun_sen'] = ichimoku.ichimoku_b()   # این خطا داره، باید اصلاح بشه
    indicators['atr'] = AverageTrueRange(df['high'], df['low'], df['close'], window=14).average_true_range()
    return indicators

# تابع استراتژی
def strategy(df, rsi_window, rsi_overbought, rsi_oversold, macd_fast, macd_slow, macd_signal,
             bb_window, bb_alpha, tenkan_window, kijun_window, stop_loss, take_profit):
    indicators = calculate_indicators(df, rsi_window, macd_fast, macd_slow, macd_signal,
                                     bb_window, bb_alpha, tenkan_window, kijun_window)
    
    # سیگنال‌های ورود
    entries_long = (
        (indicators['rsi'] < rsi_oversold) &
        (indicators['macd'] > indicators['macd_signal']) &
        (df['close'] > indicators['tenkan_sen']) &
        (df['close'] > indicators['kijun_sen']) &
        (indicators['obv'] > indicators['obv_ma']) &
        (df['close'] <= indicators['bb_lower'])
    )
    entries_short = (
        (indicators['rsi'] > rsi_overbought) &
        (indicators['macd'] < indicators['macd_signal']) &
        (df['close'] < indicators['tenkan_sen']) &
        (df['close'] < indicators['kijun_sen']) &
        (indicators['obv'] < indicators['obv_ma']) &
        (df['close'] >= indicators['bb_upper'])
    )
    
    # شبیه‌سازی پورتفولیو
    portfolio = vbt.Portfolio.from_signals(
        df['close'],
        entries_long,
        entries_short,
        sl_stop=stop_loss,
        tp_stop=take_profit,
        fees=0.00075,  # کارمزد Bybit
        freq='1min'
    )
    
    return portfolio.sharpe_ratio()

# تابع بهینه‌سازی با Optuna
def objective(trial):
    rsi_window = trial.suggest_int('rsi_window', 7, 20)
    rsi_overbought = trial.suggest_int('rsi_overbought', 60, 80)
    rsi_oversold = trial.suggest_int('rsi_oversold', 20, 40)
    macd_fast = trial.suggest_int('macd_fast', 6, 18)
    macd_slow = trial.suggest_int('macd_slow', 13, 39)
    macd_signal = trial.suggest_int('macd_signal', 5, 12)
    bb_window = trial.suggest_int('bb_window', 10, 30)
    bb_alpha = trial.suggest_float('bb_alpha', 1.5, 2.5)
    tenkan_window = trial.suggest_int('tenkan_window', 7, 12)
    kijun_window = trial.suggest_int('kijun_window', 20, 30)
    stop_loss = trial.suggest_float('stop_loss', 0.003, 0.01)
    take_profit = trial.suggest_float('take_profit', 0.01, 0.02)
    
    return strategy(df, rsi_window, rsi_overbought, rsi_oversold, macd_fast, macd_slow, macd_signal,
                    bb_window, bb_alpha, tenkan_window, kijun_window, stop_loss, take_profit)

# اجرای کد
async def main():
    global df
    df = await fetch_bybit_data()
    study = optuna.create_study(direction='maximize')
    study.optimize(objective, n_trials=200)
    print("Best parameters:", study.best_params)
    print("Best Sharpe Ratio:", study.best_value)

if __name__ == "__main__":
    asyncio.run(main())