"""
ASGI config for config project.

HTTP goes to Django; WS /ws/input/ goes to the Channels input relay and
WS /ws/conversation/ to caregiver listen mode.
"""

import os

from django.core.asgi import get_asgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

# Initialize Django before importing consumers (they import settings/models)
django_asgi_app = get_asgi_application()

from channels.routing import ProtocolTypeRouter, URLRouter  # noqa: E402

from aac.routing import websocket_urlpatterns  # noqa: E402

# No AllowedHostsOriginValidator: it rejects the serial bridge, which sends no
# Origin header. The consumers check browser origins themselves.
application = ProtocolTypeRouter({
    'http': django_asgi_app,
    'websocket': URLRouter(websocket_urlpatterns),
})
