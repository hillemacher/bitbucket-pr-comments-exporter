"""Small urllib-based HTTP helpers for Bitbucket APIs."""

from __future__ import annotations

import base64
import http.client
import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Iterable
from urllib.parse import urljoin, urlsplit


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


DEFAULT_TIMEOUT = 30.0


def _origin(url: str) -> tuple[str, str, int]:
    try:
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username is not None:
            raise ValueError("Expected an HTTP(S) URL without embedded credentials")
        port = parsed.port if parsed.port is not None else (443 if parsed.scheme == "https" else 80)
        return parsed.scheme, parsed.hostname.lower(), port
    except ValueError as exc:
        raise BitbucketExportError("Invalid HTTP request destination.") from exc


def _check_origin(source: str, destination: str) -> None:
    if _origin(source) != _origin(destination):
        raise BitbucketExportError("Refusing to forward credentials to a different origin. Use the final API base URL directly.")


class _SameOriginRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _check_origin(req.full_url, newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def auth_headers(token: str | None, username: str | None = None) -> dict[str, str]:
    """Build Bitbucket auth headers without persisting credentials."""
    if token is None:
        return {}
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
    _origin(url)
    request_headers = {"Accept": "application/json"}
    request_headers.update(headers or {})
    request = urllib.request.Request(url, headers=request_headers)

    try:
        with urllib.request.build_opener(_SameOriginRedirectHandler()).open(request, timeout=DEFAULT_TIMEOUT) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        error = _to_http_error(exc)
        if retry_5xx and isinstance(error, TransientHttpError):
            time.sleep(sleep_seconds)
            return fetch_json(url, headers, retry_5xx=False, sleep_seconds=sleep_seconds)
        raise error from exc
    except urllib.error.URLError as exc:
        raise NetworkError(str(exc.reason), url) from exc
    except (OSError, http.client.HTTPException) as exc:
        raise NetworkError(str(exc), url) from exc
    except UnicodeDecodeError as exc:
        raise BitbucketExportError(f"Invalid UTF-8 response from {url}") from exc

    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        raise BitbucketExportError(f"Invalid or empty JSON response from {url}") from exc


def paginate_cloud(first_url: str, headers: dict[str, str]) -> list[dict[str, Any]]:
    """Collect all values from a Bitbucket Cloud paginated endpoint."""
    values: list[dict[str, Any]] = []
    url: str | None = first_url
    while url:
        _check_origin(first_url, url)
        page = fetch_json(url, headers)
        if not isinstance(page, dict):
            raise BitbucketExportError(f"Expected JSON object from {url}")
        values.extend(_ensure_dict_items(page.get("values", [])))
        next_url = page.get("next")
        if next_url is not None and not isinstance(next_url, str):
            raise BitbucketExportError("Invalid pagination destination.")
        url = urljoin(url, next_url) if next_url else None
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
        return exc.reason or "request failed"
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
    return exc.reason or "request failed"
