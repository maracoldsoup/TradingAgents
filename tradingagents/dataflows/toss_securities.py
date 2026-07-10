"""Read-only Toss Securities Open API probe utilities.

Toss Securities uses OAuth 2.0 Client Credentials Grant. This module only
supports market/stock read-only endpoints and refuses account, asset, order, and
conditional-order paths so the content pipeline cannot accidentally trade.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

API_KEY_ENV = "TOSS_SECURITIES_API_KEY"
SECRET_KEY_ENV = "TOSS_SECURITIES_SECRET_KEY"
CLIENT_ID_ENV = "TOSS_SECURITIES_CLIENT_ID"
CLIENT_SECRET_ENV = "TOSS_SECURITIES_CLIENT_SECRET"
BASE_URL_ENV = "TOSS_SECURITIES_BASE_URL"
DEFAULT_BASE_URL = "https://openapi.tossinvest.com"
TOKEN_PATH = "/oauth2/token"

SENSITIVE_PATH_PARTS = (
    "account",
    "accounts",
    "balance",
    "balances",
    "buy",
    "cash",
    "deposit",
    "order",
    "orders",
    "portfolio",
    "sell",
    "sellable-quantity",
    "transfer",
    "withdraw",
)
READ_ONLY_PREFIXES = (
    "/api/v1/orderbook",
    "/api/v1/prices",
    "/api/v1/trades",
    "/api/v1/price-limits",
    "/api/v1/candles",
    "/api/v1/stocks",
    "/api/v1/exchange-rate",
    "/api/v1/market-calendar/KR",
    "/api/v1/market-calendar/US",
    "/api/v1/rankings",
    "/api/v1/market-indicators/prices",
    "/api/v1/market-indicators/",
)


@dataclass(frozen=True)
class TossCredentialStatus:
    client_id_present: bool
    client_secret_present: bool
    base_url_present: bool
    base_url: str
    client_id_hint: str
    client_secret_hint: str

    @property
    def ready_for_probe(self) -> bool:
        return self.client_id_present and self.client_secret_present

    def to_dict(self) -> dict[str, Any]:
        return {
            "client_id_present": self.client_id_present,
            "client_secret_present": self.client_secret_present,
            "base_url_present": self.base_url_present,
            "base_url": self.base_url,
            "client_id_hint": self.client_id_hint,
            "client_secret_hint": self.client_secret_hint,
            "ready_for_probe": self.ready_for_probe,
        }


def load_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def merged_env(env: Mapping[str, str] | None = None, env_file: Path | None = None) -> dict[str, str]:
    merged = dict(os.environ if env is None else env)
    if env_file:
        file_values = load_env_file(env_file)
        for key, value in file_values.items():
            merged.setdefault(key, value)
    return merged


def _mask(value: str | None) -> str:
    if not value:
        return ""
    if len(value) <= 10:
        return value[:2] + "***"
    return f"{value[:6]}...(len={len(value)})"


def credential_status(env: Mapping[str, str] | None = None) -> TossCredentialStatus:
    env = env or os.environ
    client_id = env.get(CLIENT_ID_ENV) or env.get(API_KEY_ENV, "")
    client_secret = env.get(CLIENT_SECRET_ENV) or env.get(SECRET_KEY_ENV, "")
    base_url = env.get(BASE_URL_ENV, DEFAULT_BASE_URL)
    return TossCredentialStatus(
        client_id_present=bool(client_id),
        client_secret_present=bool(client_secret),
        base_url_present=bool(env.get(BASE_URL_ENV)),
        base_url=base_url,
        client_id_hint=_mask(client_id),
        client_secret_hint=_mask(client_secret),
    )


def is_read_only_path(path: str) -> bool:
    parsed_path = urllib.parse.urlparse(path).path
    parts = [part.lower() for part in parsed_path.split("/") if part]
    if any(part in SENSITIVE_PATH_PARTS for part in parts):
        return False
    return any(parsed_path == prefix or parsed_path.startswith(prefix.rstrip("/") + "/") for prefix in READ_ONLY_PREFIXES)


def build_url(base_url: str, path: str, params: Mapping[str, Any] | None = None) -> str:
    base_url = base_url or DEFAULT_BASE_URL
    if not path.startswith("/"):
        path = "/" + path
    url = base_url.rstrip("/") + path
    if params:
        query = urllib.parse.urlencode({key: value for key, value in params.items() if value is not None})
        if query:
            url += "?" + query
    return url


def token_request_body(env: Mapping[str, str]) -> bytes:
    client_id = env.get(CLIENT_ID_ENV) or env.get(API_KEY_ENV, "")
    client_secret = env.get(CLIENT_SECRET_ENV) or env.get(SECRET_KEY_ENV, "")
    return urllib.parse.urlencode({
        "grant_type": "client_credentials",
        "client_id": client_id,
        "client_secret": client_secret,
    }).encode("utf-8")


def issue_access_token(env: Mapping[str, str], timeout: float = 10) -> dict[str, Any]:
    status = credential_status(env)
    if not status.ready_for_probe:
        raise ValueError("Toss client_id/client_secret are required for OAuth2 token issuance.")

    url = build_url(status.base_url, TOKEN_PATH)
    request = urllib.request.Request(
        url,
        data=token_request_body(env),
        headers={
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "TradingAgents-Toss-Probe/0.1",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
            return json.loads(body)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return {
            "error": True,
            "status": exc.code,
            "body": body[:2000],
        }
    except urllib.error.URLError as exc:
        return {
            "error": True,
            "status": None,
            "body": str(exc.reason),
        }


def build_headers(access_token: str) -> dict[str, str]:
    headers = {
        "Accept": "application/json",
        "User-Agent": "TradingAgents-Toss-Probe/0.1",
        "Authorization": f"Bearer {access_token}",
    }
    return headers


def redact_headers(headers: Mapping[str, str]) -> dict[str, str]:
    redacted = {}
    for key, value in headers.items():
        if key.lower() in {"authorization", "x-api-key", "x-api-secret"}:
            redacted[key] = _mask(value)
        else:
            redacted[key] = value
    return redacted


def read_only_probe(
    *,
    env: Mapping[str, str],
    path: str,
    params: Mapping[str, Any] | None = None,
    timeout: float = 10,
) -> dict[str, Any]:
    if not is_read_only_path(path):
        raise ValueError(f"Refusing non-read-only Toss path: {path}")
    status = credential_status(env)
    if not status.ready_for_probe:
        raise ValueError("Toss client_id/client_secret are required for HTTP probes.")

    token_response = issue_access_token(env, timeout=timeout)
    access_token = token_response.get("access_token")
    if not access_token:
        return {
            "ok": False,
            "stage": "token",
            "status": token_response.get("status"),
            "url": build_url(status.base_url, TOKEN_PATH),
            "body": token_response.get("body") or token_response,
        }

    return read_only_get(
        env=env,
        access_token=access_token,
        path=path,
        params=params,
        timeout=timeout,
    )


def read_only_get(
    *,
    env: Mapping[str, str],
    access_token: str,
    path: str,
    params: Mapping[str, Any] | None = None,
    timeout: float = 10,
) -> dict[str, Any]:
    if not is_read_only_path(path):
        raise ValueError(f"Refusing non-read-only Toss path: {path}")
    status = credential_status(env)
    if not status.ready_for_probe:
        raise ValueError("Toss client_id/client_secret are required for HTTP probes.")
    if not access_token:
        raise ValueError("Toss access_token is required for read-only GET probes.")

    url = build_url(status.base_url, path, params)
    headers = build_headers(access_token)
    request = urllib.request.Request(url, headers=headers, method="GET")

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
            try:
                parsed_body: Any = json.loads(body)
            except json.JSONDecodeError:
                parsed_body = body[:2000]
            return {
                "ok": 200 <= response.status < 300,
                "stage": "read_only_get",
                "status": response.status,
                "url": url,
                "headers": redact_headers(headers),
                "body": parsed_body,
                "rate_limit": {
                    "limit": response.headers.get("X-RateLimit-Limit"),
                    "remaining": response.headers.get("X-RateLimit-Remaining"),
                    "reset": response.headers.get("X-RateLimit-Reset"),
                },
            }
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return {
            "ok": False,
            "stage": "read_only_get",
            "status": exc.code,
            "url": url,
            "headers": redact_headers(headers),
            "body": body[:2000],
        }
    except urllib.error.URLError as exc:
        return {
            "ok": False,
            "stage": "read_only_get",
            "status": None,
            "url": url,
            "headers": redact_headers(headers),
            "error": str(exc.reason),
        }
