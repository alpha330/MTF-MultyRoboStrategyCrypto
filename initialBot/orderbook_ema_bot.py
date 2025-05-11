
import ccxt
import pandas as pd
import ta
import time
import datetime
import logging
import os
from dotenv import load_dotenv
import requests
import hashlib
import hmac
import urllib.parse

# لاگ‌ها
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Define color codes for logs
class bcolors:
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKCYAN = '\033[96m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('trading_bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# بارگزاری متغیرهای محیطی
load_dotenv()
API_KEY = os.getenv("BYBIT_TESTNET_API_KEY")
API_SECRET = os.getenv("BYBIT_TESTNET_API_SECRET")

class OrderBookEMABot:
    def __init__(self, symbol="BTC/USDT:USDT", timeframe="5m", leverage=3, risk_percent=0.01):
        self.symbol = symbol
        self.timeframe = timeframe
        self.leverage = leverage
        self.risk_percent = risk_percent
        self.min_quantity = 0.001

        self.exchange = ccxt.bybit({
            'apiKey': API_KEY,
            'secret': API_SECRET,
            'enableRateLimit': True,
        })
        self.exchange.set_sandbox_mode(True)
        self.exchange.set_position_mode(hedged=True)
        self.exchange.load_markets()
        self._set_leverage()

    def _set_leverage(self):
        try:
            self.exchange.set_leverage(self.leverage, self.symbol, params={'category': 'linear'})
            logger.info(f"{bcolors.OKCYAN}Leverage set to {bcolors.BOLD}{self.leverage}{bcolors.ENDC}{bcolors.OKCYAN}x{bcolors.ENDC}")
        except Exception as e:
            logger.warning(f"{bcolors.WARNING}Set leverage warning:{bcolors.BOLD} {e}{bcolors.ENDC}")

    def fetch_ohlcv(self):
        try:
            ohlcv = self.exchange.fetch_ohlcv(self.symbol, self.timeframe, limit=100)
            df = pd.DataFrame(ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
            df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
            return df
        except Exception as e:
            logger.error(f"{bcolors.FAIL}Error fetching OHLCV: {bcolors.BOLD}{e}{bcolors.ENDC}")
            return None

    def fetch_order_book_pressure(self):
        try:
            order_book = self.exchange.fetch_order_book(self.symbol, limit=10)
            bid_volume = sum([b[1] for b in order_book["bids"]])
            ask_volume = sum([a[1] for a in order_book["asks"]])
            if ask_volume == 0:
                return 1
            return bid_volume / ask_volume
        except Exception as e:
            logger.error(f"{bcolors.FAIL}Error fetching order book: {bcolors.BOLD}{e}{bcolors.ENDC}")
            return 1

    def calculate_indicators(self, df):
        ema_8 = ta.trend.ema_indicator(df["close"], window=8)
        ema_21 = ta.trend.ema_indicator(df["close"], window=21)
        return ema_8.iloc[-1], ema_21.iloc[-1]

    def calculate_position_size(self, balance, price, stop_loss_pct=0.005):
        risk_amount = balance * self.risk_percent
        stop_loss_distance = price * stop_loss_pct
        if stop_loss_distance == 0:
            return 0
        quantity = risk_amount / stop_loss_distance
        return max(self.min_quantity, float(self.exchange.amount_to_precision(self.symbol, quantity)))
    
    def place_order(self, side, quantity, stop_loss, take_profit):
        try:
            order_func = self.exchange.create_market_buy_order if side == "buy" else self.exchange.create_market_sell_order
            position_idx = 1 if side == "buy" else 2
            order = order_func(
                self.symbol,
                quantity,
                params={
                    "category": "linear",
                    "stopLoss": str(stop_loss),
                    "takeProfit": str(take_profit),
                    "positionIdx": position_idx
                }
            )
            order_id = order["id"]

            # بررسی وضعیت سفارش
            time.sleep(1)  # کمی صبر برای ثبت در سرور
            order_info = self.exchange.fetch_order(order_id, self.symbol)
            avg_price = order_info.get("average")
            if order_info.get("filled", 0) > 0:
                logger.info(f"{bcolors.OKCYAN}{bcolors.BOLD}{side.upper()}{bcolors.ENDC} "
                            f"{bcolors.OKCYAN}order FILLED: {bcolors.BOLD}{order_info['filled']}{bcolors.ENDC} "
                            f"{bcolors.OKCYAN}@ avg price {bcolors.BOLD}{avg_price}{bcolors.ENDC}")

                if avg_price:
                    self.set_trailing_stop(side, avg_price)
                else:
                    logger.warning(f"{bcolors.WARNING}Cannot set trailing stop: avg price not available{bcolors.ENDC}")

            else:
                logger.warning(f"{bcolors.WARNING}{bcolors.BOLD}{side.upper()}{bcolors.ENDC}"
                               f"{bcolors.WARNING} order NOT filled yet: status={bcolors.BOLD}{order_info.get('status')}{bcolors.ENDC}")
        except Exception as e:
            logger.error(f"{bcolors.FAIL}Error placing{bcolors.BOLD} {side}{bcolors.ENDC}{bcolors.FAIL} order: {bcolors.BOLD}{e}{bcolors.ENDC}")

    def set_trailing_stop(self, side, price):
        try:
            position_idx = 1 if side == "buy" else 2
            trailing_distance = round(price * 0.007, 2)  # 0.7 درصد از قیمت

            url = 'https://api-testnet.bybit.com/v5/position/trading-stop'
            timestamp = str(int(time.time() * 1000))
            params = {
                "category": "linear",
                "symbol": self.symbol.replace('/', ''),
                "positionIdx": position_idx,
                "trailingStop": str(trailing_distance),
                "recvWindow": "60000",
                "timestamp": timestamp
            }

            # ساخت امضا
            query_string = '&'.join([f"{k}={v}" for k, v in sorted(params.items())])
            signature = hmac.new(
                bytes(API_SECRET, "utf-8"),
                msg=bytes(query_string, "utf-8"),
                digestmod=hashlib.sha256
            ).hexdigest()

            headers = {
                "X-BAPI-API-KEY": API_KEY,
                "Content-Type": "application/json"
            }

            params["sign"] = signature
            res = requests.post(url, headers=headers, json=params)

            if res.status_code == 200:
                logger.info(f"Trailing stop set for {side.upper()} at distance: {trailing_distance}")
            else:
                logger.error(f"Failed to set trailing stop: {res.text}")

        except Exception as e:
            logger.error(f"Error in set_trailing_stop: {e}")

    def get_open_positions(self):
        try:
            positions = self.exchange.fetch_positions([self.symbol], params={'category': 'linear'})
            result = {'long': None, 'short': None}
            for pos in positions:
                if pos['contracts'] > 0:
                    if pos['side'] == 'long':
                        result['long'] = pos
                    elif pos['side'] == 'short':
                        result['short'] = pos
            return result
        except Exception as e:
            logger.error(f"Error fetching positions: {e}")
            return {'long': None, 'short': None}


    def run(self):
        logger.info(f"{bcolors.OKGREEN}Running OrderBookEMABot on {bcolors.BOLD}{self.symbol} | {self.timeframe}{bcolors.ENDC}")
        while True:
            try:
                df = self.fetch_ohlcv()
                if df is None:
                    time.sleep(60)
                    continue

                price = df["close"].iloc[-1]
                pressure = self.fetch_order_book_pressure()
                ema_8, ema_21 = self.calculate_indicators(df)

                balance = self.exchange.fetch_balance(params={'recv_window': 60000})["USDT"]["free"]
                quantity = self.calculate_position_size(balance, price)

                if quantity < self.min_quantity:
                    logger.warning(f"{bcolors.WARNING}Insufficient margin to place order{bcolors.ENDC}")
                    time.sleep(60)
                    continue

                if pressure > 1.5 and ema_8 > ema_21:
                    # سیگنال Long
                    sl = price * (1 - 0.004)
                    tp = price * (1 + 0.008)
                    self.place_order("buy", quantity, sl, tp)

                elif pressure < 0.67 and ema_8 < ema_21:
                    # سیگنال Short
                    sl = price * (1 + 0.004)
                    tp = price * (1 - 0.008)
                    self.place_order("sell", quantity, sl, tp)

                time.sleep(60)
            except Exception as e:
                logger.error(f"Main loop error: {e}")
                time.sleep(60)

    def close_position(self, side):
        try:
            position_idx = 1 if side == "long" else 2
            pos = self.get_open_positions()[side]
            if not pos:
                logger.info(f"No {side.upper()} position to close")
                return
            qty = pos['contracts']
            close_side = 'sell' if side == "long" else 'buy'
            order = self.exchange.create_market_order(
                self.symbol,
                close_side,
                qty,
                params={
                    "category": "linear",
                    "reduceOnly": True,
                    "positionIdx": position_idx
                }
            )
            logger.info(f"{bcolors.OKBLUE}Closed {side.upper()} position with qty={qty}, order ID: {order.get('id', 'N/A')}{bcolors.ENDC}")
        except Exception as e:
            logger.error(f"Error closing {side} position: {e}")
            logger.error(f"Error closing {side} position: {e}")

def main():
    bot = OrderBookEMABot(symbol="BTC/USDT:USDT", timeframe="5m", leverage=3, risk_percent=0.01)
    bot.run()

if __name__ == "__main__":
    main()
