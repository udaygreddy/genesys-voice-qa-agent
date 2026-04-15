"""Genesys Cloud Notifications API — WebSocket listener.

Flow
----
1. POST /api/v2/notifications/channels   → get a channel with a dedicated WebSocket URI
2. Connect to that WebSocket URI
3. Subscribe to  v2.conversations.{id}.transcription  for every active conversation
4. On each transcript event: buffer utterances per conversation, then
   - every ANALYSIS_UTTERANCE_WINDOW utterances, OR
   - when the conversation ends
   run CallQualityAnalyzer and fire NotificationSink if a problem is found.

The Notifications API also sends a heartbeat ("ping") every 30 s; we reply "pong"
automatically via the websockets library.

Genesys Notifications API reference:
  https://developer.genesys.cloud/notificationsalerts/notifications/notifications-apis
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

import httpx
import websockets
import websockets.exceptions

from genesys_voice_qa.analyzer import CallQualityAnalyzer
from genesys_voice_qa.genesys_auth import GenesysAuthClient
from genesys_voice_qa.notifications import NotificationSink, notify_if_needed

logger = logging.getLogger(__name__)

# How many utterances to accumulate before triggering an analysis mid-call.
# The analyzer also runs when a conversation disconnects.
ANALYSIS_UTTERANCE_WINDOW = 20

# How often (seconds) to re-check the token and renew the WS channel subscription.
HEARTBEAT_CHECK_INTERVAL = 60

# Genesys sends a channel-expiry notification; channels last 24 h.
CHANNEL_REFRESH_BEFORE_S = 300   # refresh 5 min before expiry


@dataclass
class _ConversationBuffer:
    conversation_id: str
    utterances: list[str] = field(default_factory=list)
    last_analysis_at: float = field(default_factory=time.monotonic)
    notified: bool = False          # only notify once per conversation

    def formatted_transcript(self) -> str:
        return "\n".join(self.utterances)


class GenesysNotificationsListener:
    """Connects to the Genesys Notifications API and streams live transcripts.

    Parameters
    ----------
    auth:
        A :class:`GenesysAuthClient` that supplies fresh bearer tokens.
    analyzer:
        The :class:`CallQualityAnalyzer` to run on buffered utterances.
    sink:
        Where quality notifications are delivered (log, webhook, etc.).
    utterance_window:
        Trigger mid-call analysis every N utterances (default: 20).
    """

    def __init__(
        self,
        *,
        auth: GenesysAuthClient,
        analyzer: CallQualityAnalyzer,
        sink: NotificationSink,
        utterance_window: int = ANALYSIS_UTTERANCE_WINDOW,
    ) -> None:
        self._auth = auth
        self._analyzer = analyzer
        self._sink = sink
        self._utterance_window = utterance_window
        self._buffers: dict[str, _ConversationBuffer] = {}
        self._channel_id: str | None = None
        self._ws_url: str | None = None
        self._subscribed_topics: set[str] = set()

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    async def run_forever(self) -> None:
        """Connect, subscribe, and process events.  Reconnects on error."""
        while True:
            try:
                await self._connect_and_listen()
            except websockets.exceptions.ConnectionClosedError as exc:
                logger.warning("WebSocket closed (%s), reconnecting in 5 s …", exc)
            except Exception as exc:  # noqa: BLE001
                logger.error("Listener error: %s — reconnecting in 10 s …", exc, exc_info=True)
                await asyncio.sleep(10)
            else:
                logger.info("WebSocket closed cleanly, reconnecting …")
            await asyncio.sleep(5)

    # ------------------------------------------------------------------
    # Channel management
    # ------------------------------------------------------------------

    def _create_channel(self) -> tuple[str, str]:
        """Create a Notifications channel; returns (channel_id, ws_connect_uri)."""
        url = f"{self._auth.api_base}/api/v2/notifications/channels"
        with httpx.Client(timeout=15) as client:
            resp = client.post(url, headers={"Authorization": self._auth.bearer()})
            resp.raise_for_status()
            body = resp.json()
        channel_id: str = body["id"]
        ws_url: str = body["connectUri"]
        logger.info("Genesys channel created: %s", channel_id)
        return channel_id, ws_url

    def _subscribe(self, channel_id: str, topics: list[str]) -> None:
        """Subscribe a list of topic IDs on an existing channel."""
        url = f"{self._auth.api_base}/api/v2/notifications/channels/{channel_id}/subscriptions"
        body = [{"id": t} for t in topics]
        with httpx.Client(timeout=15) as client:
            resp = client.post(
                url,
                headers={
                    "Authorization": self._auth.bearer(),
                    "Content-Type": "application/json",
                },
                content=json.dumps(body),
            )
            resp.raise_for_status()
        logger.info("Subscribed to %d topic(s) on channel %s", len(topics), channel_id)

    def _subscribe_to_all_conversations(self, channel_id: str) -> None:
        """Subscribe to the wildcard transcription topic (all conversations)."""
        topic = "v2.conversations.{id}.transcription"
        if topic not in self._subscribed_topics:
            self._subscribe(channel_id, [topic])
            self._subscribed_topics.add(topic)

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    async def _connect_and_listen(self) -> None:
        channel_id, ws_url = self._create_channel()
        self._channel_id = channel_id
        self._ws_url = ws_url
        self._subscribe_to_all_conversations(channel_id)

        logger.info("Connecting to Genesys WebSocket …")
        async with websockets.connect(
            ws_url,
            additional_headers={"Authorization": self._auth.bearer()},
            ping_interval=30,
            ping_timeout=10,
        ) as ws:
            logger.info("WebSocket connected.")
            async for raw_message in ws:
                await self._handle_message(raw_message)

    # ------------------------------------------------------------------
    # Message dispatch
    # ------------------------------------------------------------------

    async def _handle_message(self, raw: str | bytes) -> None:
        try:
            event: dict[str, Any] = json.loads(raw)
        except json.JSONDecodeError:
            logger.debug("Non-JSON WS message: %s", raw)
            return

        topic_name: str = event.get("topicName", "")
        event_body: dict[str, Any] = event.get("eventBody", {})

        if topic_name == "channel.metadata":
            # Heartbeat / channel metadata; nothing to do.
            return

        if "transcription" in topic_name:
            self._handle_transcription_event(topic_name, event_body)
            return

        if "conversation" in topic_name:
            self._handle_conversation_event(topic_name, event_body)

    # ------------------------------------------------------------------
    # Transcript handling
    # ------------------------------------------------------------------

    def _handle_transcription_event(
        self, topic_name: str, body: dict[str, Any]
    ) -> None:
        """Parse a transcription event and buffer the utterance."""
        conversation_id = self._extract_conversation_id(topic_name, body)
        if not conversation_id:
            return

        utterance = self._extract_utterance_text(body)
        if not utterance:
            return

        buf = self._buffers.setdefault(
            conversation_id,
            _ConversationBuffer(conversation_id=conversation_id),
        )
        buf.utterances.append(utterance)
        logger.debug(
            "[%s] +utterance (%d total): %s",
            conversation_id,
            len(buf.utterances),
            utterance[:80],
        )

        if len(buf.utterances) % self._utterance_window == 0:
            self._run_analysis(buf, trigger="window")

    def _handle_conversation_event(
        self, topic_name: str, body: dict[str, Any]
    ) -> None:
        """Detect conversation disconnect and run final analysis."""
        conversation_id = self._extract_conversation_id(topic_name, body)
        if not conversation_id:
            return

        participants = body.get("participants", [])
        all_disconnected = participants and all(
            p.get("state") in ("disconnected", "terminated")
            for p in participants
        )
        if all_disconnected and conversation_id in self._buffers:
            buf = self._buffers[conversation_id]
            logger.info("[%s] Conversation ended — running final analysis.", conversation_id)
            self._run_analysis(buf, trigger="end-of-call")
            del self._buffers[conversation_id]

    # ------------------------------------------------------------------
    # Analysis + notification
    # ------------------------------------------------------------------

    def _run_analysis(self, buf: _ConversationBuffer, *, trigger: str) -> None:
        if buf.notified:
            return
        transcript = buf.formatted_transcript()
        if not transcript.strip():
            return

        logger.info(
            "[%s] Running LLM analysis (%s, %d utterances) …",
            buf.conversation_id,
            trigger,
            len(buf.utterances),
        )
        try:
            report = self._analyzer.analyze_transcript(
                conversation_id=buf.conversation_id,
                transcript_text=transcript,
            )
            notified = notify_if_needed(report=report, sink=self._sink)
            if notified:
                logger.warning(
                    "[%s] Quality issue(s) detected and notification sent.",
                    buf.conversation_id,
                )
                buf.notified = True
            else:
                logger.info("[%s] No quality issues detected.", buf.conversation_id)
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "[%s] Analysis failed: %s",
                buf.conversation_id,
                exc,
                exc_info=True,
            )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_conversation_id(
        topic_name: str, body: dict[str, Any]
    ) -> str | None:
        # Topic format:  v2.conversations.{conversationId}.transcription
        parts = topic_name.split(".")
        if len(parts) >= 3:
            candidate = parts[2]
            if candidate and candidate != "{id}":
                return candidate
        return body.get("id") or body.get("conversationId") or None

    @staticmethod
    def _extract_utterance_text(body: dict[str, Any]) -> str | None:
        """Pull readable text out of the transcription event body.

        Genesys wraps transcript alternatives in a nested structure:
        transcripts[].alternatives[].transcript
        """
        participant_type: str = body.get("participantType", "unknown")

        transcripts: list[dict] = body.get("transcripts", [])
        for segment in transcripts:
            alternatives: list[dict] = segment.get("alternatives", [])
            for alt in alternatives:
                text: str = alt.get("transcript", "").strip()
                if text:
                    return f"{participant_type}: {text}"

        # Flat fallback (some older event shapes)
        for key in ("transcript", "text", "content"):
            val = body.get(key)
            if isinstance(val, str) and val.strip():
                return f"{participant_type}: {val.strip()}"

        return None
