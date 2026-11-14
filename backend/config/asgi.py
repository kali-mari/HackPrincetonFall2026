"""
ASGI config for config project.

HTTP goes to Django; WS /ws/input/ goes to the Channels input relay.
"""

import os

from django.core.asgi import get_asgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

# Initialize Django before importing consumers (they import settings/models)
django_asgi_app = get_asgi_application()

from channels.routing import ProtocolTypeRouter, URLRouter  # noqa: E402

from aac.routing import websocket_urlpatterns  # noqa: E402

# No AllowedHostsOriginValidator: it rejects the serial bridge, which sends no
# Origin header. InputConsumer checks browser origins itself.
application = ProtocolTypeRouter({
    'http': django_asgi_app,
    'websocket': URLRouter(websocket_urlpatterns),
})
