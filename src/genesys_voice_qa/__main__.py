"""CLI entry point.

Usage::

    # using installed script
    genesys-voice-qa

    # or directly
    python -m genesys_voice_qa

Environment variables (see .env.example):
    GENESYS_REGION, GENESYS_CLIENT_ID, GENESYS_CLIENT_SECRET
    LLM_BACKEND (azure | gateway)
    AZURE_OPENAI_* or AI_GATEWAY_*
    NOTIFICATION_WEBHOOK_URL (optional — logs to stdout if absent)
    ANALYSIS_UTTERANCE_WINDOW (optional, default 20)
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys

from dotenv import load_dotenv

from genesys_voice_qa.analyzer import CallQualityAnalyzer
from genesys_voice_qa.bootstrap import completion_client_from_env
from genesys_voice_qa.genesys_auth import GenesysAuthClient
from genesys_voice_qa.genesys_listener import GenesysNotificationsListener
from genesys_voice_qa.notifications import (
    LoggingNotificationSink,
    NotificationSink,
    WebhookNotificationSink,
)


def _build_sink() -> NotificationSink:
    webhook_url = os.getenv("NOTIFICATION_WEBHOOK_URL", "").strip()
    if webhook_url:
        return WebhookNotificationSink(url=webhook_url)
    return LoggingNotificationSink()


def main() -> None:
    load_dotenv()

    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
        stream=sys.stdout,
    )
    logger = logging.getLogger("genesys_voice_qa")

    region = os.environ["GENESYS_REGION"]
    client_id = os.environ["GENESYS_CLIENT_ID"]
    client_secret = os.environ["GENESYS_CLIENT_SECRET"]
    utterance_window = int(os.getenv("ANALYSIS_UTTERANCE_WINDOW", "20"))

    auth = GenesysAuthClient(
        region=region,
        client_id=client_id,
        client_secret=client_secret,
    )

    completion = completion_client_from_env()
    analyzer = CallQualityAnalyzer(completion=completion)
    sink = _build_sink()

    listener = GenesysNotificationsListener(
        auth=auth,
        analyzer=analyzer,
        sink=sink,
        utterance_window=utterance_window,
    )

    logger.info(
        "Starting Genesys Voice QA Agent | region=%s | backend=%s | window=%d utterances",
        region,
        os.getenv("LLM_BACKEND", "azure"),
        utterance_window,
    )
    asyncio.run(listener.run_forever())


if __name__ == "__main__":
    main()
