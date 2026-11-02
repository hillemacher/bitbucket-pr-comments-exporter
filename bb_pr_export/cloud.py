"""Bitbucket Cloud API client and normalizer."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from .http import BitbucketExportError, auth_headers, fetch_json, paginate_cloud


CLOUD_BASE_URL = "https://api.bitbucket.org/2.0"


def export_pull_request(workspace: str, repo: str, pr_id: str, token: str | None) -> dict[str, Any]:
    headers = auth_headers(token)
    base = f"{CLOUD_BASE_URL}/repositories/{quote(workspace)}/{quote(repo)}/pullrequests/{quote(str(pr_id))}"
    pr = fetch_json(base, headers)
    if not isinstance(pr, dict):
        raise BitbucketExportError(f"Expected JSON object from {base}")
    comments = paginate_cloud(f"{base}/comments", headers)

    return {
        "provider": "cloud",
        "pr": _normalize_pr(pr),
        "reviewers": _normalize_reviewers(pr),
        "comments": [_normalize_comment(comment) for comment in comments],
    }


def _normalize_pr(pr: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": pr.get("id"),
        "title": pr.get("title"),
        "state": pr.get("state"),
        "author": _display_name(pr.get("author")),
        "source_branch": ((pr.get("source") or {}).get("branch") or {}).get("name"),
        "destination_branch": ((pr.get("destination") or {}).get("branch") or {}).get("name"),
        "created": pr.get("created_on"),
        "description": pr.get("description"),
    }


def _normalize_reviewers(pr: dict[str, Any]) -> list[dict[str, str]]:
    reviewers: list[dict[str, str]] = []
    for participant in pr.get("participants") or []:
        state = participant.get("state")
        approved = participant.get("approved")
        decision = _cloud_decision(state, approved)
        if decision:
            reviewers.append({"reviewer": _display_name(participant.get("user")), "decision": decision})
    return reviewers


def _normalize_comment(comment: dict[str, Any]) -> dict[str, Any]:
    inline = comment.get("inline") if isinstance(comment.get("inline"), dict) else {}
    parent = comment.get("parent") if isinstance(comment.get("parent"), dict) else None
    return {
        "id": comment.get("id"),
        "parent_id": parent.get("id") if parent else None,
        "author": _display_name(comment.get("user")),
        "created": comment.get("created_on"),
        "body": _content_text(comment.get("content")),
        "deleted": bool(comment.get("deleted")),
        "inline": bool(inline),
        "location": _inline_location(inline),
        "review_outcome": None,
    }


def _inline_location(inline: dict[str, Any]) -> dict[str, Any] | None:
    if not inline:
        return None
    from_line = inline.get("from")
    to_line = inline.get("to")
    side = "old" if from_line is not None and to_line is None else "new"
    return {
        "path": inline.get("path"),
        "line": to_line if to_line is not None else from_line,
        "side": side,
    }


def _content_text(content: Any) -> str:
    if not isinstance(content, dict):
        return ""
    for key in ("raw", "markup", "html"):
        value = content.get(key)
        if isinstance(value, str):
            return value
    return ""


def _display_name(user: Any) -> str:
    if not isinstance(user, dict):
        return "Unknown"
    return user.get("display_name") or user.get("nickname") or user.get("username") or "Unknown"


def _cloud_decision(state: str | None, approved: bool | None) -> str | None:
    if approved:
        return "approved"
    match (state or "").lower():
        case "changes_requested":
            return "changes_requested"
        case "approved":
            return "approved"
        case _:
            return None
