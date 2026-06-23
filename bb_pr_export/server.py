"""Bitbucket Server/Data Center API client and normalizer."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from .http import auth_headers, fetch_json, paginate_server


def export_pull_request(
    server_url: str,
    project: str,
    repo: str,
    pr_id: str,
    token: str,
    username: str | None = None,
) -> dict[str, Any]:
    headers = auth_headers(token, username)
    base_url = server_url.rstrip("/")
    base = (
        f"{base_url}/rest/api/1.0/projects/{quote(project)}/repos/{quote(repo)}"
        f"/pull-requests/{quote(str(pr_id))}"
    )
    pr = fetch_json(base, headers)
    activities = paginate_server(f"{base}/activities?limit=100", headers)

    return {
        "provider": "server",
        "pr": _normalize_pr(pr),
        "reviewers": _normalize_reviewers(pr),
        "comments": _normalize_comments_from_activities(activities),
    }


def _normalize_pr(pr: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": pr.get("id"),
        "title": pr.get("title"),
        "state": pr.get("state"),
        "author": _display_user((pr.get("author") or {}).get("user")),
        "source_branch": ((pr.get("fromRef") or {}).get("displayId") or (pr.get("fromRef") or {}).get("id")),
        "destination_branch": ((pr.get("toRef") or {}).get("displayId") or (pr.get("toRef") or {}).get("id")),
        "created": _millis_to_iso(pr.get("createdDate")),
        "description": pr.get("description"),
    }


def _normalize_reviewers(pr: dict[str, Any]) -> list[dict[str, str]]:
    reviewers: list[dict[str, str]] = []
    for reviewer in pr.get("reviewers") or []:
        status = reviewer.get("status")
        if status and status != "UNAPPROVED":
            reviewers.append({"reviewer": _display_user(reviewer.get("user")), "decision": status.lower()})
    return reviewers


def _normalize_comments_from_activities(activities: list[dict[str, Any]]) -> list[dict[str, Any]]:
    comments: list[dict[str, Any]] = []
    for activity in activities:
        comment = activity.get("comment")
        if isinstance(comment, dict):
            comments.append(_normalize_comment(comment, activity))
    return comments


def _normalize_comment(comment: dict[str, Any], activity: dict[str, Any]) -> dict[str, Any]:
    anchor = comment.get("anchor") if isinstance(comment.get("anchor"), dict) else {}
    parent = comment.get("parent") if isinstance(comment.get("parent"), dict) else None
    return {
        "id": comment.get("id"),
        "parent_id": parent.get("id") if parent else None,
        "author": _display_user(comment.get("author") or activity.get("user")),
        "created": _millis_to_iso(comment.get("createdDate") or activity.get("createdDate")),
        "body": comment.get("text") or "",
        "deleted": bool(comment.get("deleted")),
        "inline": bool(anchor),
        "location": _anchor_location(anchor),
        "review_outcome": None,
    }


def _anchor_location(anchor: dict[str, Any]) -> dict[str, Any] | None:
    if not anchor:
        return None
    line = anchor.get("line")
    line_type = (anchor.get("lineType") or "").upper()
    side = "old" if line_type == "REMOVED" else "new" if line_type else None
    return {
        "path": _anchor_path(anchor),
        "line": line,
        "side": side,
    }


def _anchor_path(anchor: dict[str, Any]) -> Any:
    path = anchor.get("path")
    if isinstance(path, dict):
        return path.get("toString") or path.get("displayId") or anchor.get("filePath")
    if isinstance(path, str):
        return path
    return anchor.get("filePath")


def _display_user(user: Any) -> str:
    if not isinstance(user, dict):
        return "Unknown"
    return user.get("displayName") or user.get("name") or user.get("emailAddress") or "Unknown"


def _millis_to_iso(value: Any) -> str | None:
    if value is None:
        return None
    try:
        import datetime as _dt

        return _dt.datetime.fromtimestamp(int(value) / 1000, tz=_dt.UTC).isoformat()
    except (TypeError, ValueError, OSError):
        return str(value)
