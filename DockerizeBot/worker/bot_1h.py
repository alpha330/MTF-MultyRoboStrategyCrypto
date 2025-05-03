import time
import requests

# پیکربندی آدرس API Django
API_BASE_URL = "http://django:8000/api"

# تابع تستی برای بررسی روند (اینجا فرضی، بعداً با اندیکاتور واقعی جایگزین می‌کنیم)
def get_trend():
    # این قسمت با استفاده از اندیکاتورها مثل EMA, RSI, MACD مقداردهی میشه
    # فرض کنیم روند تصادفی باشه فعلاً:
    import random
    return random.choice(["uptrend", "downtrend", "sideways"])

def post_trend_to_api(trend):
    try:
        response = requests.post(f"{API_BASE_URL}/trend/", json={"trend": trend})
        print("Trend posted:", response.json())
    except Exception as e:
        print("Error posting trend:", e)

def run():
    while True:
        trend = get_trend()
        print("Detected trend:", trend)
        post_trend_to_api(trend)
        time.sleep(60 * 60)  # هر 1 ساعت

if __name__ == "__main__":
    run()
