"""
ASGI configuration for Bio Attendance.
Supports both HTTP (DRF) and WebSocket (Channels) protocols.
"""

import os
import django
from django.core.asgi import get_asgi_application
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.security.websocket import AllowedHostsOriginValidator

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from apps.attendance.routing import websocket_urlpatterns  # noqa: E402 — after django.setup()
from apps.attendance.middleware import JWTAuthMiddlewareStack  # noqa: E402

application = ProtocolTypeRouter({
    'http': get_asgi_application(),
    'websocket': AllowedHostsOriginValidator(
        JWTAuthMiddlewareStack(
            URLRouter(websocket_urlpatterns)
        )
    ),
})
