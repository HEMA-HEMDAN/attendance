from django.urls import re_path
from .consumers import AttendanceSessionConsumer

websocket_urlpatterns = [
    re_path(r'^ws/sessions/(?P<session_id>\d+)/$', AttendanceSessionConsumer.as_asgi()),
]
