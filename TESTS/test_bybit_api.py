import requests
import time
import hmac
import hashlib
import json

API_KEY = "gQN2wKJwbd9DTmg4rq"
API_SECRET = "d21cUa3jYZLYHNSwjYfNXd9UpkzowX7myRcX"
RECV_WINDOW = 10000
TIMESTAMP = int(time.time() * 1000)

# پارامترهای درخواست
params = {
    "api_key": API_KEY,
    "timestamp": TIMESTAMP,
    "recv_window": RECV_WINDOW,
}

# ساخت امضا
param_str = f"api_key={API_KEY}&recv_window={RECV_WINDOW}&timestamp={TIMESTAMP}"
sign = hmac.new(API_SECRET.encode('utf-8'), param_str.encode('utf-8'), hashlib.sha256).hexdigest()
params['sign'] = sign

# ارسال درخواست
url = "https://api-testnet.bybit.com/v5/account/wallet-balance"
headers = {"Content-Type": "application/json"}
response = requests.get(url, params=params, headers=headers)

print(response.status_code)
print(json.dumps(response.json(), indent=2))