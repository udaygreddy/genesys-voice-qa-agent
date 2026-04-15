from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

import httpx

from genesys_voice_qa.analyzer import CallQualityReport

logger = logging.getLogger(__name__)

# Severity → Slack colour for the attachment side-bar
_SEVERITY_COLOUR = {
    "high": "#E01E5A",    # red
    "medium": "#ECB22E",  # yellow
    "low": "#2EB67D",     # green
}

_CATEGORY_EMOJI = {
    "headset": ":headphones:",
    "background_noise": ":loud_sound:",
    "other": ":warning:",
}


@dataclass(frozen=True)
class QualityNotification:
    title: str
    body: str
    metadata: dict[str, Any]


class NotificationSink(ABC):
    @abstractmethod
    def send(self, notification: QualityNotification) -> None:
        raise NotImplementedError


class LoggingNotificationSink(NotificationSink):
    def send(self, notification: QualityNotification) -> None:
        print(f"[quality-alert] {notification.title}\n{notification.body}")


class WebhookNotificationSink(NotificationSink):
    def __init__(self, *, url: str, timeout_s: float = 15.0) -> None:
        self._url = url
        self._timeout = timeout_s

    def send(self, notification: QualityNotification) -> None:
        payload = {
            "title": notification.title,
            "body": notification.body,
            "metadata": notification.metadata,
        }
        with httpx.Client(timeout=self._timeout) as client:
            response = client.post(self._url, content=json.dumps(payload))
            response.raise_for_status()


class SlackNotificationSink(NotificationSink):
    """Send call quality alerts to a Slack user (looked up by email) via a Bot token.

    The sink resolves the email → Slack user ID on first use and caches it for the
    lifetime of the process, so ``users.lookupByEmail`` is only called once.

    Required Slack App Bot Token Scopes:
        users:read.email  — resolve email → user ID
        chat:write        — open a DM and post messages

    Parameters
    ----------
    bot_token:
        Slack Bot OAuth token (starts with ``xoxb-``).
    recipient_email:
        Work email address of the person who should receive the DM alert.
        Typically the supervisor or QA lead on duty.
    timeout_s:
        HTTP request timeout in seconds.
    """

    _LOOKUP_URL = "https://slack.com/api/users.lookupByEmail"
    _POST_URL   = "https://slack.com/api/chat.postMessage"

    def __init__(
        self,
        *,
        bot_token: str,
        recipient_email: str,
        timeout_s: float = 15.0,
    ) -> None:
        self._token = bot_token
        self._email = recipient_email
        self._timeout = timeout_s
        self._user_id: str | None = None   # resolved lazily and cached

    # ------------------------------------------------------------------
    # User resolution
    # ------------------------------------------------------------------

    def _resolve_user_id(self) -> str:
        """Look up the Slack user ID for the configured email (cached after first call)."""
        if self._user_id:
            return self._user_id

        headers = {"Authorization": f"Bearer {self._token}"}
        with httpx.Client(timeout=self._timeout) as client:
            response = client.get(
                self._LOOKUP_URL,
                headers=headers,
                params={"email": self._email},
            )
            response.raise_for_status()
            body = response.json()

        if not body.get("ok"):
            error = body.get("error", "unknown_error")
            logger.error(
                "Slack users.lookupByEmail failed for %s: %s", self._email, error
            )
            raise RuntimeError(
                f"Could not resolve Slack user for email '{self._email}': {error}"
            )

        user_id: str = body["user"]["id"]
        display_name: str = (
            body["user"].get("profile", {}).get("display_name")
            or body["user"].get("real_name", "")
        )
        logger.info(
            "Resolved Slack user: %s → %s (%s)", self._email, user_id, display_name
        )
        self._user_id = user_id
        return user_id

    # ------------------------------------------------------------------
    # Send
    # ------------------------------------------------------------------

    def send(self, notification: QualityNotification) -> None:
        user_id = self._resolve_user_id()
        blocks = self._build_blocks(notification)

        issues = notification.metadata.get("issues", [])
        severities = [i.get("severity", "low") for i in issues]
        colour = _SEVERITY_COLOUR.get(
            "high" if "high" in severities else ("medium" if "medium" in severities else "low"),
            "#ECB22E",
        )

        payload = {
            "channel": user_id,           # Slack opens a DM when channel = user ID
            "text": notification.title,   # plain-text fallback for push notifications
            "attachments": [
                {
                    "color": colour,
                    "blocks": blocks,
                }
            ],
        }

        headers = {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json; charset=utf-8",
        }

        with httpx.Client(timeout=self._timeout) as client:
            response = client.post(
                self._POST_URL,
                headers=headers,
                content=json.dumps(payload),
            )
            response.raise_for_status()
            body = response.json()

        if not body.get("ok"):
            error = body.get("error", "unknown_error")
            logger.error("Slack chat.postMessage error: %s | body: %s", error, body)
            raise RuntimeError(f"Slack chat.postMessage failed: {error}")

        logger.info(
            "Slack DM sent to %s (%s) | ts=%s",
            self._email,
            user_id,
            body.get("ts"),
        )

    # ------------------------------------------------------------------
    # Block Kit builder
    # ------------------------------------------------------------------

    @staticmethod
    def _build_blocks(notification: QualityNotification) -> list[dict]:
        issues: list[dict] = notification.metadata.get("issues", [])
        conversation_id: str = notification.metadata.get("conversation_id", "unknown")
        confidence: float = notification.metadata.get("confidence", 0.0)

        blocks: list[dict] = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": ":rotating_light: Call Quality Alert",
                    "emoji": True,
                },
            },
            {
                "type": "section",
                "fields": [
                    {
                        "type": "mrkdwn",
                        "text": f"*Conversation ID*\n`{conversation_id}`",
                    },
                    {
                        "type": "mrkdwn",
                        "text": f"*Confidence*\n{confidence:.0%}",
                    },
                ],
            },
            {"type": "divider"},
        ]

        for issue in issues:
            category: str = issue.get("category", "other")
            severity: str = issue.get("severity", "low")
            summary: str = issue.get("summary", "")
            evidence: list[str] = issue.get("evidence", [])

            emoji = _CATEGORY_EMOJI.get(category, ":warning:")
            sev_label = severity.upper()

            issue_block: dict = {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f"{emoji} *{category.replace('_', ' ').title()}* — `{sev_label}`\n"
                        f"{summary}"
                    ),
                },
            }
            blocks.append(issue_block)

            if evidence:
                quotes = "\n".join(f"> _{e}_" for e in evidence[:3])
                blocks.append(
                    {
                        "type": "section",
                        "text": {"type": "mrkdwn", "text": quotes},
                    }
                )

        blocks.append({"type": "divider"})
        blocks.append(
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": ":robot_face: Genesys Voice QA Agent",
                    }
                ],
            }
        )
        return blocks


def build_notification(report: CallQualityReport) -> QualityNotification | None:
    if not report.analysis.has_problem:
        return None

    title = f"Call quality issue: {report.conversation_id}"
    lines = []
    for issue in report.analysis.issues:
        lines.append(f"- [{issue.severity}] {issue.category}: {issue.summary}")
        for quote in issue.evidence[:3]:
            lines.append(f"  · {quote}")
    if report.analysis.notes:
        lines.append(f"Notes: {report.analysis.notes}")

    return QualityNotification(
        title=title,
        body="\n".join(lines),
        metadata={
            "conversation_id": report.conversation_id,
            "confidence": report.analysis.confidence,
            "issues": [issue.model_dump() for issue in report.analysis.issues],
        },
    )


def notify_if_needed(
    *,
    report: CallQualityReport,
    sink: NotificationSink,
) -> bool:
    notification = build_notification(report)
    if notification is None:
        return False
    sink.send(notification)
    return True
