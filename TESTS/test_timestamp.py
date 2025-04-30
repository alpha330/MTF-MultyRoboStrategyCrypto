
import time
import datetime
print("System Timestamp:", int(time.time() * 1000))
utc_now = datetime.datetime.now(datetime.timezone.utc)
print("UTC Timestamp:", int(utc_now.timestamp() * 1000))
print("DIFFERENT TimeStamp",int(time.time() * 1000) - int(utc_now.timestamp() * 1000))
