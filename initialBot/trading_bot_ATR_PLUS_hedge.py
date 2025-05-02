import ccxt
import pandas as pd
import pandas_ta as ta
import time
import logging
from datetime import datetime

# تنظیمات لاگ
logging.basicConfig(
    filename='/root/MTF-MultyRoboStrategyCrypto/initialBot/trading_bot_ATR_PLUS.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

class TradingBot:
    def __init__(self, api_key, api_secret):
        # تنظیمات صرافی (Bybit Testnet)
        self.exchange = ccxt.bybit({
            'apiKey': api_key,
            'secret': api_secret,
            'enableRateLimit': True,
            'test': True  # برای تست‌نت Bybit
        })
        
        # فعال‌سازی حالت Hedged
        self.exchange.set_position_mode(hedged=True)
        
        # تنظیمات عمومی
        self.symbol = 'BTC/USDT:USDT'
        self.leverage = 5
        self.risk_percent = 0.005  # حجم معاملات
        self.min_position_interval = 15 * 60  # حداقل 15 دقیقه فاصله بین پوزیشن‌ها (به ثانیه)
        
        # تنظیمات اندیکاتورها
        self.rsi_long_threshold = 25
        self.rsi_short_threshold = 75
        self.stoch_k_long = 10
        self.stoch_d_long = 10
        self.stoch_k_short = 90
        self.stoch_d_short = 90
        
        # تنظیمات مدیریت ریسک
        self.atr_sl_multiplier = 3  # برای Stop Loss
        self.atr_tp_multiplier = 5  # برای Take Profit
        
        # تنظیمات ایچیموکو
        self.ichimoku_tf = "1h"
        
        # متغیر برای مدیریت فاصله زمانی
        self.last_position_time = 0
        
        # تنظیم لِوِرج
        self.set_leverage()

    def set_leverage(self):
        try:
            self.exchange.set_leverage(self.leverage, self.symbol)
            self.log(f"LEVERAGE {self.leverage}x FOR {self.symbol} SET BEFORE")
        except Exception as e:
            self.log(f"Error setting leverage: {str(e)}", level="ERROR")

    def log(self, message, level="INFO"):
        if level == "INFO":
            logging.info(message)
            print(f"\033[96m{message}\033[0m")
        elif level == "ERROR":
            logging.error(message)
            print(f"\033[91m{message}\033[0m")
        elif level == "INDICATORS":
            logging.info(message)
            print(f"\033[94m{message}\033[0m")

    def run(self):
        self.log(f"ALGOBOT {self.symbol} IN TIME FRAME 5m HAS BEEN STARTED")
        self.log(f"ALGOBOT {self.symbol} IN TIME FRAME 15m HAS BEEN STARTED")

        while True:
            try:
                # دریافت داده‌ها (تایم‌فریم 5 دقیقه)
                data_5m = self.exchange.fetch_ohlcv(self.symbol, timeframe="5m", limit=200)
                df_5m = pd.DataFrame(data_5m, columns=["timestamp", "open", "high", "low", "close", "volume"])
                self.log(f"FOR OHLCV DATA {self.symbol} IN 5m CANDLES ARE GET: {len(df_5m)}")

                # دریافت داده‌های ایچیموکو (تایم‌فریم 1 ساعته)
                data_1h = self.exchange.fetch_ohlcv(self.symbol, timeframe=self.ichimoku_tf, limit=200)
                df_1h = pd.DataFrame(data_1h, columns=["timestamp", "open", "high", "low", "close", "volume"])
                self.log(f"FOR OHLCV DATA {self.symbol} IN {self.ichimoku_tf} CANDLES ARE GET: {len(df_1h)}")

                # محاسبه اندیکاتورهای ایچیموکو
                ichimoku = df_1h.ta.ichimoku()
                price = df_1h["close"].iloc[-1]
                span_a = ichimoku[0]["ISA_9"].iloc[-1]  # Span A
                span_b = ichimoku[0]["ISB_26"].iloc[-1]  # Span B

                # محاسبه اندیکاتورها (تایم‌فریم 5 دقیقه)
                df_5m["rsi"] = ta.rsi(df_5m["close"], length=14)
                stoch = ta.stoch(df_5m["high"], df_5m["low"], df_5m["close"], k=14, d=3)
                df_5m["stoch_k"] = stoch["STOCHk_14_3_3"]
                df_5m["stoch_d"] = stoch["STOCHd_14_3_3"]
                atr = ta.atr(df_5m["high"], df_5m["low"], df_5m["close"], length=14)
                current_atr = atr.iloc[-1]

                # اندیکاتورهای فعلی
                current_rsi = df_5m["rsi"].iloc[-1]
                current_stoch_k = df_5m["stoch_k"].iloc[-1]
                current_stoch_d = df_5m["stoch_d"].iloc[-1]
                self.log(f"Current RSI: {current_rsi:.2f}, Stochastic K: {current_stoch_k:.2f}, D: {current_stoch_d:.2f}", level="INDICATORS")

                # دریافت موقعیت فعلی
                positions = self.exchange.fetch_positions([self.symbol])
                long_position = None
                short_position = None
                for pos in positions:
                    if pos["side"] == "long":
                        long_position = pos
                    elif pos["side"] == "short":
                        short_position = pos

                # محاسبه فاصله زمانی از آخرین پوزیشن
                current_time = time.time()
                time_since_last_position = current_time - self.last_position_time

                # تشخیص روند با ایچیموکو
                trend = "neutral"
                if price > max(span_a, span_b):
                    trend = "bullish"  # فقط Long
                elif price < min(span_a, span_b):
                    trend = "bearish"  # فقط Short

                # منطق سیگنال
                if time_since_last_position >= self.min_position_interval:  # شرط فاصله زمانی
                    # سیگنال Long
                    if (current_rsi < self.rsi_long_threshold and 
                        current_stoch_k < self.stoch_k_long and 
                        current_stoch_d < self.stoch_d_long and 
                        trend != "bearish"):
                        if not long_position:
                            self.open_position("long", current_atr)
                            self.last_position_time = current_time

                    # سیگنال Short
                    if (current_rsi > self.rsi_short_threshold and 
                        current_stoch_k > self.stoch_k_short and 
                        current_stoch_d > self.stoch_d_short and 
                        trend != "bullish"):
                        if not short_position:
                            self.open_position("short", current_atr)
                            self.last_position_time = current_time

            except Exception as e:
                self.log(f"Error in run loop: {str(e)}", level="ERROR")
            
            time.sleep(60)  # هر 60 ثانیه چک کن

    def open_position(self, side, atr):
        try:
            # محاسبه حجم
            balance = self.exchange.fetch_balance()["total"]["USDT"]
            risk_amount = balance * self.risk_percent
            price = self.exchange.fetch_ticker(self.symbol)["last"]
            quantity = risk_amount / price

            # محاسبه Stop Loss و Take Profit
            sl_price = price + (atr * self.atr_sl_multiplier) if side == "short" else price - (atr * self.atr_sl_multiplier)
            tp_price = price - (atr * self.atr_tp_multiplier) if side == "short" else price + (atr * self.atr_tp_multiplier)

            # باز کردن پوزیشن
            if side == "long":
                self.exchange.create_market_buy_order(self.symbol, quantity)
                self.log(f"Opened Long position at {price} with quantity {quantity}")
            else:
                self.exchange.create_market_sell_order(self.symbol, quantity)
                self.log(f"Opened Short position at {price} with quantity {quantity}")

            # تنظیم Stop Loss و Take Profit
            self.exchange.create_order(
                symbol=self.symbol,
                type="stop",
                side="sell" if side == "long" else "buy",
                amount=quantity,
                price=sl_price,
                params={"stopLossPrice": sl_price, "positionIdx": 1 if side == "long" else 2}
            )
            self.exchange.create_order(
                symbol=self.symbol,
                type="limit",
                side="sell" if side == "long" else "buy",
                amount=quantity,
                price=tp_price,
                params={"takeProfitPrice": tp_price, "positionIdx": 1 if side == "long" else 2}
            )

        except Exception as e:
            self.log(f"Error opening position: {str(e)}", level="ERROR")

if __name__ == "__main__":
    # وارد کردن API Key و Secret (اینجا باید API خودت رو وارد کنی)
    api_key = "YOUR_API_KEY"
    api_secret = "YOUR_API_SECRET"

    bot = TradingBot(api_key, api_secret)
    bot.run()