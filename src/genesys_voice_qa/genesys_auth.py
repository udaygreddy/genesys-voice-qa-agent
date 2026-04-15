from __future__ import annotations

import time
import threading
import logging
from dataclasses import dataclass, field

import httpx

logger = logging.getLogger(__name__)

# Genesys region → base domain mapping.  Add more as needed.
REGION_DOMAINS: dict[str, str] = {
    "us-east-1":    "mypurecloud.com",
    "us-west-2":    "usw2.pure.cloud",
    "eu-west-1":    "mypurecloud.ie",
    "eu-west-2":    "euw2.pure.cloud",
    "ap-southeast-2": "mypurecloud.com.au",
    "ap-northeast-1": "mypurecloud.jp",
    "ca-central-1": "cac1.pure.cloud",
}


@dataclass
class GenesysToken:
    access_token: str
    expires_at: float          # epoch seconds
    token_type: str = "Bearer"

    def is_expired(self, buffer_s: float = 60.0) -> bool:
        return time.monotonic() >= self.expires_at - buffer_s


class GenesysAuthClient:
    """Fetches and auto-refreshes Genesys Cloud OAuth2 client-credentials tokens.

    Usage::

        auth = GenesysAuthClient(region="us-east-1", client_id="...", client_secret="...")
        token = auth.get_token()   # always valid; refreshes transparently
    """

    def __init__(
        self,
        *,
        region: str,
        client_id: str,
        client_secret: str,
        timeout_s: float = 15.0,
    ) -> None:
        domain = REGION_DOMAINS.get(region)
        if not domain:
            raise ValueError(
                f"Unknown Genesys region '{region}'. "
                f"Add it to REGION_DOMAINS or pass the domain directly."
            )
        self._token_url = f"https://login.{domain}/oauth/token"
        self._api_base = f"https://api.{domain}"
        self._client_id = client_id
        self._client_secret = client_secret
        self._timeout = timeout_s
        self._token: GenesysToken | None = None
        self._lock = threading.Lock()

    @property
    def api_base(self) -> str:
        return self._api_base

    def get_token(self) -> GenesysToken:
        with self._lock:
            if self._token is None or self._token.is_expired():
                self._token = self._fetch()
            return self._token

    def bearer(self) -> str:
        return f"Bearer {self.get_token().access_token}"

    def _fetch(self) -> GenesysToken:
        logger.debug("Fetching new Genesys OAuth token from %s", self._token_url)
        with httpx.Client(timeout=self._timeout) as client:
            response = client.post(
                self._token_url,
                data={"grant_type": "client_credentials"},
                auth=(self._client_id, self._client_secret),
            )
            response.raise_for_status()
            body = response.json()

        expires_in = int(body.get("expires_in", 86400))
        token = GenesysToken(
            access_token=body["access_token"],
            expires_at=time.monotonic() + expires_in,
            token_type=body.get("token_type", "Bearer"),
        )
        logger.info("Genesys token acquired, expires in %ds", expires_in)
        return token
