"""Shared helpers for normalized comment locations."""


def line_range(start: object, end: object) -> dict[str, int] | None:
    if type(start) is int and type(end) is int and 1 <= start <= end:
        return {"start_line": start, "end_line": end}
    return None
