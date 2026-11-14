from django.urls import path

from .consumers import ConversationConsumer, InputConsumer

websocket_urlpatterns = [
    path("ws/input/", InputConsumer.as_asgi()),
    path("ws/conversation/", ConversationConsumer.as_asgi()),
]
