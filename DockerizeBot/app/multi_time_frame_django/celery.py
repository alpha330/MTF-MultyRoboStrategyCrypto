import os
from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "multi_time_frame_django.settings")

app = Celery("multi_time_frame_django")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
