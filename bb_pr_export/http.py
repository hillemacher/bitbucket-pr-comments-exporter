"""Small urllib-based HTTP helpers for Bitbucket APIs."""

from __future__ import annotations

import base64
import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Iterable


class BitbucketExportError(Exception):
    """Base error raised by the exporter."""


@dataclass(slots=True)
class HttpError(BitbucketExportError):
    status: int
    message: str
    url: str

    def __str__(self) -> str:
        return f"HTTP {self.status} for {self.url}: {self.message}"


class AuthError(HttpError):
    """Authentication or authorization failed."""


class NotFoundError(HttpError):
    """The requested resource was not found."""


class NetworkError(BitbucketExportError):
    """A network-level error occurred."""

    def __init__(self, message: str, url: str) -> None:
        self.message = message
        self.url = url
        super().__init__(f"Network error for {url}: {message}")


class TransientHttpError(HttpError):
    """A retryable server-side HTTP error."""


def auth_headers(token: str, username: str | None = None) -> dict[str, str]:
    """Build Bitbucket auth headers without persisting credentials."""
    if username:
        raw = f"{username}:{token}".encode("utf-8")
        encoded = base64.b64encode(raw).decode("ascii")
        return {"Authorization": f"Basic {encoded}"}
    return {"Authorization": f"Bearer {token}"}


def fetch_json(
    url: str,
    headers: dict[str, str] | None = None,
    *,
    retry_5xx: bool = True,
    sleep_seconds: float = 2.0,
) -> Any:
    """Fetch JSON from a URL, retrying one transient 5xx failure."""
    request_headers = {"Accept": "application/json"}
    request_headers.update(headers or {})
    request = urllib.request.Request(url, headers=request_headers)

    try:
        with urllib.request.urlopen(request) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        error = _to_http_error(exc)
        if retry_5xx and isinstance(error, TransientHttpError):
            time.sleep(sleep_seconds)
            return fetch_json(url, headers, retry_5xx=False, sleep_seconds=sleep_seconds)
        raise error from exc
    except urllib.error.URLError as exc:
        raise NetworkError(str(exc.reason), url) from exc

    if not body:
        return None
    return json.loads(body)


def paginate_cloud(first_url: str, headers: dict[str, str]) -> list[dict[str, Any]]:
    """Collect all values from a Bitbucket Cloud paginated endpoint."""
    values: list[dict[str, Any]] = []
    url: str | None = first_url
    while url:
        page = fetch_json(url, headers)
        if not isinstance(page, dict):
            raise BitbucketExportError(f"Expected JSON object from {url}")
        values.extend(_ensure_dict_items(page.get("values", [])))
        url = page.get("next")
    return values


def paginate_server(first_url: str, headers: dict[str, str]) -> list[dict[str, Any]]:
    """Collect all values from a Bitbucket Server/Data Center paginated endpoint."""
    values: list[dict[str, Any]] = []
    url = first_url
    while True:
        page = fetch_json(url, headers)
        if not isinstance(page, dict):
            raise BitbucketExportError(f"Expected JSON object from {url}")
        values.extend(_ensure_dict_items(page.get("values", [])))
        if page.get("isLastPage", True):
            break
        separator = "&" if "?" in first_url else "?"
        url = f"{first_url}{separator}start={page['nextPageStart']}"
    return values


def _ensure_dict_items(items: Iterable[Any]) -> list[dict[str, Any]]:
    return [item for item in items if isinstance(item, dict)]


def _to_http_error(exc: urllib.error.HTTPError) -> HttpError:
    message = _read_error_message(exc)
    if exc.code in {401, 403}:
        return AuthError(exc.code, message, exc.url)
    if exc.code == 404:
        return NotFoundError(exc.code, message, exc.url)
    if 500 <= exc.code <= 599:
        return TransientHttpError(exc.code, message, exc.url)
    return HttpError(exc.code, message, exc.url)


def _read_error_message(exc: urllib.error.HTTPError) -> str:
    try:
        body = exc.read().decode("utf-8")
    except Exception:
        return exc.reason or "request failed"
    if not body:
        return exc.reason or "request failed"
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError:
        return body
    if isinstance(parsed, dict):
        error = parsed.get("error")
        if isinstance(error, dict) and isinstance(error.get("message"), str):
            return error["message"]
        if isinstance(parsed.get("message"), str):
            return parsed["message"]
        if isinstance(parsed.get("errors"), list) and parsed["errors"]:
            first = parsed["errors"][0]
            if isinstance(first, dict) and isinstance(first.get("message"), str):
                return first["message"]
    return body
