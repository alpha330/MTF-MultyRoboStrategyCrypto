from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/', include('trend_api.urls')),
    path('api/ocilators/', include('ocilators.urls')),
]
