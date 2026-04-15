from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

import httpx

from genesys_voice_qa.analyzer import CallQualityReport


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
