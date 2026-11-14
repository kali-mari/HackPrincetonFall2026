"""WS /ws/input/: relays switch input (InputMessage) between the bridge and the board."""

import logging

from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.conf import settings

log = logging.getLogger(__name__)

GROUP = "input"
ACTIONS = {"PREV", "NEXT", "SELECT", "DELETE", "SPEAK", "LISTEN"}
SOURCES = {"button", "touch", "voice"}


def valid_input(message):
    return (
        isinstance(message, dict)
        and set(message) == {"action", "source"}
        and message["action"] in ACTIONS
        and message["source"] in SOURCES
    )


class InputConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        # Browsers always send Origin, so a page must come from the frontend. The
        # serial bridge is not a browser and sends none. Channels'
        # AllowedHostsOriginValidator rejects a missing Origin, so check here instead.
        origin = dict(self.scope["headers"]).get(b"origin")
        if origin is not None and origin.decode("latin-1") not in settings.CORS_ALLOWED_ORIGINS:
            log.warning("Rejected /ws/input/ connection from origin %r", origin)
            await self.close()
            return
        await self.channel_layer.group_add(GROUP, self.channel_name)
        await self.accept()

    async def disconnect(self, code):
        await self.channel_layer.group_discard(GROUP, self.channel_name)

    async def receive_json(self, content, **kwargs):
        if not valid_input(content):
            log.warning("Dropped invalid input message: %r", content)
            return
        await self.channel_layer.group_send(GROUP, {
            "type": "input.message",
            "message": {"action": content["action"], "source": content["source"]},
            "sender": self.channel_name,
        })

    async def receive(self, text_data=None, bytes_data=None, **kwargs):
        if text_data is None:
            log.warning("Dropped binary input frame")
            return
        await super().receive(text_data=text_data, **kwargs)

    async def decode_json(self, text_data):
        # Malformed JSON is dropped like any other invalid message, not a disconnect
        try:
            return await super().decode_json(text_data)
        except ValueError:
            return None

    async def input_message(self, event):
        # No echo: the sender already acted on (or produced) this input
        if event["sender"] != self.channel_name:
            await self.send_json(event["message"])
