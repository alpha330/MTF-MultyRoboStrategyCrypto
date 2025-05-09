# PersianCheetah_Scalper_Bybit

## Overview
**PersianCheetah_Scalper_Bybit** is an automated trading bot designed for scalping on the Bybit exchange, written in Python. It operates on a 1-minute timeframe, utilizing a strategy based on RSI and Bollinger Bands. The bot supports **Hedged Mode**, **Trailing Stop**, and **Trailing Profit** features, and trades on BTC/USDT, ETH/USDT, and XRP/USDT pairs.

### Features
- **Scalping Strategy:** Uses RSI (period 14) and Bollinger Bands (period 20) for entry and exit signals.
- **Hedged Mode:** Allows simultaneous Long and Short positions.
- **Risk Management:** Limits risk to 1% of wallet balance per trade.
- **Trailing Stop and Trailing Profit:** Dynamic stop-loss and take-profit to optimize profits and minimize losses.
- **Paper Trading:** Simulates trades without real capital risk.
- **Telegram Notifications:** Sends trade reports and bot status to Telegram.
- **Supported Pairs:** BTC/USDT, ETH/USDT, XRP/USDT.
- **Leverage:** 10x for BTC and ETH, 5x for XRP.

## Prerequisites
- Python 3.8 or higher
- Bybit account with API Key and Secret
- Telegram account and bot token
- Operating System: Linux, Windows, or macOS

## Installation
1. **Clone the Repository:**
   ```bash
   git clone https://github.com/your-repo/PersianCheetah_Scalper_Bybit.git
   cd PersianCheetah_Scalper_Bybit
   ```

2. **Install Dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

3. **Create .env File:**
   Create a `.env` file in the project root and add the following variables:
   ```env
   TELEGRAM_TOKEN_PAPER1M_10=your_telegram_bot_token
   TELEGRAM_CHANAL_ID=your_telegram_chat_id
   BYBIT_LIVE_API_KEY=your_bybit_api_key
   BYBIT_LIVE_API_SECRET=your_bybit_api_secret
   ```

4. **Generate requirements.txt:**
   ```bash
   echo -e "ccxt==2.9.5\npandas==2.0.3\nta==0.10.2\npython-telegram-bot==20.3\npython-dotenv==1.0.0\ntenacity==8.2.2" > requirements.txt
   ```

## Usage
1. **Run the Bot:**
   ```bash
   python PersianCheetah_Scalper_Bybit.py
   ```

2. **Telegram Commands:**
   - `/start`: Start the bots
   - `/stop`: Stop the bots
   - `/status`: Display bot status
   - `/positions`: Show position statistics

## Important Notes
- **Backtesting:** Perform thorough backtesting with historical data before live trading.
- **Risk Management:** Ensure Trailing Stop (0.3-0.5%) and Trailing Profit (0.5%) settings align with your strategy.
- **Fees:** Maker fee (0.02%) is included in calculations. Taker orders (0.06%) may reduce profits.
- **Monitoring:** Use Telegram notifications to monitor bot performance.
- **Timeframe:** Optimized for 1-minute timeframe, performs best during high-volatility sessions (London/New York).

## Warning
- This bot is designed for paper trading. For live trading, conduct extensive backtesting first.
- Cryptocurrency trading carries high risks. No guarantees of profit are provided.

## Contributors
- Developed by: [Your Name]
- Contact: [Your Email or Telegram ID]

## License
MIT License