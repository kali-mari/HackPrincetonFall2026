from django.urls import path

from .consumers import InputConsumer

websocket_urlpatterns = [
    path("ws/input/", InputConsumer.as_asgi()),
]
