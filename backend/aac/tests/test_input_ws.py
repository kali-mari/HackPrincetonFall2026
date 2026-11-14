"""WS /ws/input/ relay through the real ASGI application; in-memory channel layer, no DB."""

from unittest import IsolatedAsyncioTestCase

from channels.layers import channel_layers
from channels.testing import WebsocketCommunicator
from jsonschema import Draft202012Validator

from aac.openapi import SCHEMAS
from config.asgi import application

BROWSER = [(b'origin', b'http://localhost:5173')]


# IsolatedAsyncioTestCase, not SimpleTestCase: Django's async tests skip asyncTearDown,
# which closes the communicators.
class InputRelayTests(IsolatedAsyncioTestCase):
    def setUp(self):
        # Fresh in-memory layer per test so group members never leak between tests
        channel_layers.backends.clear()
        self.open = []

    async def asyncTearDown(self):
        for ws in self.open:
            await ws.disconnect()

    async def connect(self, headers=()):
        ws = WebsocketCommunicator(application, '/ws/input/', headers=list(headers))
        connected, _ = await ws.connect()
        if connected:
            self.open.append(ws)
        return ws, connected

    async def bridge_and_board(self):
        bridge, ok1 = await self.connect()  # no Origin, like hardware/bridge.py
        board, ok2 = await self.connect(BROWSER)
        self.assertTrue(ok1 and ok2)
        return bridge, board

    async def test_every_action_reaches_the_board_once(self):
        bridge, board = await self.bridge_and_board()
        validator = Draft202012Validator(SCHEMAS['InputMessage'])
        for action in ('PREV', 'NEXT', 'SELECT', 'DELETE', 'SPEAK', 'LISTEN'):
            message = {'action': action, 'source': 'button'}
            await bridge.send_json_to(message)
            received = await board.receive_json_from()
            self.assertEqual(received, message)
            validator.validate(received)
            self.assertTrue(await board.receive_nothing())

    async def test_voice_and_touch_sources(self):
        bridge, board = await self.bridge_and_board()
        for source in ('voice', 'touch'):
            await bridge.send_json_to({'action': 'SELECT', 'source': source})
            self.assertEqual(await board.receive_json_from(), {'action': 'SELECT', 'source': source})

    async def test_broadcasts_to_every_other_client_without_echo(self):
        bridge, board = await self.bridge_and_board()
        dashboard, connected = await self.connect(BROWSER)
        self.assertTrue(connected)
        await bridge.send_json_to({'action': 'NEXT', 'source': 'button'})
        self.assertEqual(await board.receive_json_from(), {'action': 'NEXT', 'source': 'button'})
        self.assertEqual(await dashboard.receive_json_from(), {'action': 'NEXT', 'source': 'button'})
        self.assertTrue(await bridge.receive_nothing())

    async def test_invalid_messages_are_dropped_and_connection_stays_open(self):
        bridge, board = await self.bridge_and_board()
        with self.assertLogs('aac.consumers', 'WARNING') as logs:
            await self.send_bad(bridge)
            self.assertTrue(await board.receive_nothing())
        self.assertEqual(len(logs.records), 10)
        # Still connected: a later valid press goes through
        await bridge.send_json_to({'action': 'SPEAK', 'source': 'button'})
        self.assertEqual(await board.receive_json_from(), {'action': 'SPEAK', 'source': 'button'})

    async def send_bad(self, bridge):
        for bad in ('not json', '[]', '"NEXT"', '{}', '{"action": "NEXT"}',
                    '{"action": "JUMP", "source": "button"}', '{"action": "next", "source": "button"}',
                    '{"action": "NEXT", "source": "keyboard"}',
                    '{"action": "NEXT", "source": "button", "extra": 1}'):
            await bridge.send_to(text_data=bad)
        await bridge.send_to(bytes_data=b'NEXT')

    async def test_foreign_browser_origin_is_rejected(self):
        for origin in (b'http://evil.example', b'http://localhost:5174', b'null'):
            with self.assertLogs('aac.consumers', 'WARNING'):
                _, connected = await self.connect([(b'origin', origin)])
            self.assertFalse(connected, origin)

    async def test_disconnected_client_leaves_the_group(self):
        bridge, board = await self.bridge_and_board()
        await board.disconnect()
        self.open.remove(board)
        late, _ = await self.connect(BROWSER)
        await bridge.send_json_to({'action': 'NEXT', 'source': 'button'})
        self.assertEqual(await late.receive_json_from(), {'action': 'NEXT', 'source': 'button'})
        layer = channel_layers['default']
        self.assertEqual(len(layer.groups['input']), 2)

    async def test_other_paths_are_not_routed(self):
        ws = WebsocketCommunicator(application, '/ws/other/')
        with self.assertRaises(ValueError):
            await ws.connect()
