"""Render normalized pull request review data."""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any


InlineLocation = tuple[str | None, int | None, str | None, tuple[tuple[str, int, int], ...]]


def render_json(export: dict[str, Any], *, include_deleted: bool = False) -> str:
    filtered = {**export, "comments": _filter_comments(export.get("comments", []), include_deleted)}
    return json.dumps(filtered, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def render_markdown(export: dict[str, Any], *, include_deleted: bool = False) -> str:
    pr = export["pr"]
    comments = _filter_comments(export.get("comments", []), include_deleted)
    outcomes = export.get("reviewers", [])

    lines: list[str] = [
        f"# PR #{pr['id']}: {pr.get('title') or ''}",
        "",
        f"**Author:** {pr.get('author') or 'Unknown'}  |  **State:** {pr.get('state') or 'Unknown'}  |  **Created:** {_format_date(pr.get('created'))}",
        f"**Branch:** `{pr.get('source_branch') or 'unknown'}` → `{pr.get('destination_branch') or 'unknown'}`",
        "",
        "**Description:**",
        pr.get("description") or "_No description._",
        "",
        "---",
        "",
    ]

    if "assigned_reviewers" in export:
        assigned = export["assigned_reviewers"]
        lines.extend(["## Assigned reviewers", ""])
        if assigned is None:
            lines.append("Unknown")
        elif not assigned:
            lines.append("None reported")
        else:
            lines.extend(f"- {reviewer.get('reviewer') or 'Unknown'}" for reviewer in assigned)
        lines.extend(["", "---", ""])

    if outcomes:
        lines.extend(["## Review outcome", "", "| Reviewer | Decision |", "|---|---|"])
        for reviewer in outcomes:
            lines.append(f"| {reviewer.get('reviewer') or 'Unknown'} | {_format_decision(reviewer.get('decision'))} |")
        lines.extend(["", "---", ""])

    inline_count = sum(1 for comment in comments if comment.get("inline"))
    general_count = len(comments) - inline_count
    lines.extend(
        [
            f"## Comments ({len(comments)} total — {inline_count} inline, {general_count} general)",
            "",
        ]
    )

    roots, replies = _split_threads(comments)
    for (path, line, side, ranges), group in _group_inline_roots(roots):
        if ranges:
            labels = [
                f"line {start} ({range_side})" if start == end else f"lines {start}–{end} ({range_side})"
                for range_side, start, end in ranges
            ]
            suffix = " " + ", ".join(labels)
        else:
            suffix = f" line {line}" if line is not None else ""
            if side:
                suffix = f"{suffix} ({side})"
        lines.extend([f"### 📄 `{path or 'unknown'}`{suffix}", ""])
        for comment in group:
            _render_comment(lines, comment, replies, include_deleted)
        lines.extend(["---", ""])

    general_roots = [comment for comment in roots if not comment.get("inline")]
    if general_roots:
        lines.extend(["### 💬 General", ""])
        for comment in sorted(general_roots, key=_comment_sort_key):
            _render_comment(lines, comment, replies, include_deleted)
        lines.extend(["---", ""])

    return "\n".join(lines).rstrip() + "\n"


def _filter_comments(comments: list[dict[str, Any]], include_deleted: bool) -> list[dict[str, Any]]:
    if include_deleted:
        return comments
    return [comment for comment in comments if not comment.get("deleted")]


def _split_threads(comments: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    comment_by_id = {str(comment.get("id")): comment for comment in comments if comment.get("id") is not None}
    replies: dict[str, list[dict[str, Any]]] = defaultdict(list)
    roots: list[dict[str, Any]] = []
    for comment in comments:
        parent_id = comment.get("parent_id")
        if parent_id is not None and str(parent_id) in comment_by_id:
            replies[str(parent_id)].append(comment)
        else:
            roots.append(comment)
    for children in replies.values():
        children.sort(key=_comment_sort_key)
    return roots, replies


def _group_inline_roots(roots: list[dict[str, Any]]) -> list[tuple[InlineLocation, list[dict[str, Any]]]]:
    groups: dict[InlineLocation, list[dict[str, Any]]] = defaultdict(list)
    for comment in roots:
        if comment.get("inline"):
            location = comment.get("location") or {}
            ranges = location.get("ranges") or {}
            bounds = tuple(
                (side, ranges[side]["start_line"], ranges[side]["end_line"])
                for side in ("old", "new") if side in ranges
            )
            groups[(location.get("path"), location.get("line"), location.get("side"), bounds)].append(comment)
    return [
        (location, sorted(group, key=_comment_sort_key))
        for location, group in sorted(
            groups.items(), key=lambda item: (item[0][0] or "", item[0][1] or 0, item[0][2] or "", item[0][3])
        )
    ]


def _render_comment(
    lines: list[str],
    comment: dict[str, Any],
    replies: dict[str, list[dict[str, Any]]],
    include_deleted: bool,
    *,
    reply: bool = False,
) -> None:
    prefix = "↳ " if reply else ""
    lines.append(f"{prefix}**{comment.get('author') or 'Unknown'}** · {_format_datetime(comment.get('created'))}")
    for body_line in _quote_body(comment, include_deleted):
        lines.append(body_line)
    lines.append("")

    comment_id = comment.get("id")
    if comment_id is None:
        return
    for child in replies.get(str(comment_id), []):
        _render_comment(lines, child, replies, include_deleted, reply=True)


def _quote_body(comment: dict[str, Any], include_deleted: bool) -> list[str]:
    if comment.get("deleted") and include_deleted:
        return ["> ~~[deleted]~~"]
    body = comment.get("body") or ""
    if not body.strip():
        return ["> _No comment text._"]
    return [f"> {line}" if line else ">" for line in body.splitlines()]


def _format_decision(decision: str | None) -> str:
    normalized = (decision or "").lower()
    match normalized:
        case "approved" | "approve" | "approved_pending_comment":
            return "✅ Approved"
        case "needs_work" | "changes_requested" | "request_changes":
            return "🔄 Changes requested"
        case "unapproved":
            return "Unapproved"
        case "":
            return "Unknown"
        case _:
            return decision.replace("_", " ").title() if decision else "Unknown"


def _format_date(value: str | None) -> str:
    formatted = _parse_datetime(value)
    if formatted is None:
        return value or "Unknown"
    return formatted.strftime("%Y-%m-%d")


def _format_datetime(value: str | None) -> str:
    formatted = _parse_datetime(value)
    if formatted is None:
        return value or "Unknown"
    return formatted.strftime("%Y-%m-%d %H:%M UTC")


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    candidate = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _comment_sort_key(comment: dict[str, Any]) -> tuple[str, str]:
    return (comment.get("created") or "", str(comment.get("id") or ""))
