"""WS /ws/input/ relays switch input (InputMessage) between the bridge and the board.
WS /ws/conversation/ runs caregiver listen mode for the one connection that starts it."""

import asyncio
import logging

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.conf import settings
from django.db import DatabaseError

from . import conversation
from .listen import Listener
from .models import Profile
from .predictions import recent_spoken
from .transcription import TranscriptionUnavailable
from .validation import InvalidRequest, validate_uuid

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


def allowed_origin(scope):
    # Browsers always send Origin, so a page must come from the frontend. The
    # serial bridge and command-line clients are not browsers and send none.
    # Channels' AllowedHostsOriginValidator rejects a missing Origin, so check here.
    origin = dict(scope["headers"]).get(b"origin")
    if origin is not None and origin.decode("latin-1") not in settings.CORS_ALLOWED_ORIGINS:
        log.warning("Rejected %s connection from origin %r", scope["path"], origin)
        return False
    return True


class InputConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        if not allowed_origin(self.scope):
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


RECENT_PHRASES = 50  # recent spoken phrases that may lift a matching suggestion


def suggestion_context(patient_id):
    """(preferences, recent spoken texts) for suggestions; ({}, []) without a patient.

    Raises Profile.DoesNotExist or DatabaseError when the patient cannot be read.
    """
    if patient_id is None:
        return {}, []
    patient = Profile.objects.get(pk=patient_id, role=Profile.Role.PATIENT)
    try:
        recent = [event.text for event in recent_spoken(patient)[:RECENT_PHRASES]]
    except DatabaseError:
        recent = []  # history is only a ranking boost
    return patient.preferences or {}, recent


class ConversationConsumer(AsyncJsonWebsocketConsumer):
    """Client sends {"type": "start", "patient_id"?: uuid} or {"type": "stop"}. Server
    sends {"type": "state", "listening": bool}, {"type": "transcript", "seq": n, "text": ...},
    {"type": "suggestions", "seq": n, "topic": str|null, "phrases": [six, or none]} and
    {"type": "error", "message": ...}. There is one microphone, so one connection
    listens at a time; closing the connection stops it. Transcripts and suggestions go
    only to that connection and are never stored or logged; the last few lines are kept
    in memory for follow-up questions and cleared when listening stops."""

    owner = None  # the connection currently listening (or starting to)

    async def connect(self):
        self.listener = None
        self.seq = 0
        self.lines, self.preferences, self.recent = [], {}, []
        if not allowed_origin(self.scope):
            await self.close()
            return
        await self.accept()
        await self.send_json({"type": "state", "listening": False})

    async def disconnect(self, code):
        self.stop_listening()

    async def receive(self, text_data=None, bytes_data=None, **kwargs):
        if text_data is None:
            await self.send_error("Send JSON text frames.")
            return
        await super().receive(text_data=text_data, **kwargs)

    async def decode_json(self, text_data):
        try:
            return await super().decode_json(text_data)
        except ValueError:
            return None

    async def receive_json(self, content, **kwargs):
        if isinstance(content, dict) and content.get("type") == "start" and set(content) <= {"type", "patient_id"}:
            try:
                patient_id = validate_uuid(content["patient_id"], "patient_id") if "patient_id" in content else None
            except InvalidRequest as error:
                await self.send_error(str(error))
                return
            await self.start_listening(patient_id)
        elif content == {"type": "stop"}:
            self.stop_listening()
            await self.send_json({"type": "state", "listening": False})
        else:
            await self.send_error('Send {"type": "start"} (optionally with "patient_id") or {"type": "stop"}.')

    async def start_listening(self, patient_id=None):
        owner = ConversationConsumer.owner
        if owner is not None and owner is not self:
            await self.send_error("Another connection is already listening.")
            return
        try:
            context = await database_sync_to_async(suggestion_context)(patient_id)
        except Profile.DoesNotExist:
            await self.send_error("Patient not found.")
            return
        except DatabaseError:
            await self.send_error("Profile storage is unavailable.")
            return
        if owner is self:  # already listening, or still starting: a new patient starts fresh context
            self.lines, (self.preferences, self.recent) = [], context
            if self.listener:
                await self.send_json({"type": "state", "listening": True})
            return
        if ConversationConsumer.owner is not None:  # another connection claimed it meanwhile
            await self.send_error("Another connection is already listening.")
            return
        ConversationConsumer.owner = self
        self.lines, (self.preferences, self.recent) = [], context
        conversation.warm(self.preferences)  # background: the suggestion model is ready by the first question
        loop = asyncio.get_running_loop()
        listener = Listener(
            on_text=lambda text, delay: asyncio.run_coroutine_threadsafe(
                self.send_transcript(listener, text, delay), loop),
            on_end=lambda error: asyncio.run_coroutine_threadsafe(
                self.ended(listener, error), loop),
        )
        try:
            await asyncio.to_thread(listener.start)  # loads models: seconds the first time
        except TranscriptionUnavailable as error:
            ConversationConsumer.owner = None
            await self.send_error(str(error))
            return
        if ConversationConsumer.owner is not self:  # disconnected while starting
            listener.stop()
            return
        self.listener = listener
        await self.send_json({"type": "state", "listening": True})

    def stop_listening(self):
        if self.listener:
            self.listener.stop()
            self.listener = None
        self.lines, self.preferences, self.recent = [], {}, []  # transcripts and context leave memory
        if ConversationConsumer.owner is self:
            ConversationConsumer.owner = None

    async def send_transcript(self, listener, text, delay):
        if listener is not self.listener:  # drop results from a stopped session
            return
        log.info("Listen mode phrase ready %.2f s after it ended", delay)  # never the text
        self.seq += 1
        seq = self.seq
        await self.send_json({"type": "transcript", "seq": seq, "text": text})
        self.lines = [*self.lines, text][-conversation.LINES:]
        try:
            result = await asyncio.to_thread(conversation.suggest, list(self.lines), self.preferences, self.recent)
        except Exception as error:  # a bug here must not end listening
            log.warning("Conversation suggestions failed (%s)", type(error).__name__)
            result = None
        if listener is self.listener:  # still the same session after the wait
            # No phrases means "no conversation choices": the board keeps its regular predictions.
            await self.send_json({"type": "suggestions", "seq": seq, "topic": result["label"] if result else None,
                                  "phrases": result["phrases"] if result else []})

    async def ended(self, listener, error):
        if listener is self.listener:
            self.stop_listening()
            if error:
                await self.send_error(error)
            await self.send_json({"type": "state", "listening": False})

    async def send_error(self, message):
        await self.send_json({"type": "error", "message": message})
