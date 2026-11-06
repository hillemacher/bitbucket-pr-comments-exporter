"""Shared resource budgets for one complete export, including retries/pages."""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, fields
from functools import wraps
import math
import time


@dataclass(frozen=True)
class Limits:
    timeout_seconds: float = 90.0
    max_pages: int = 1000
    max_response_bytes: int = 8 * 1024 * 1024
    max_total_bytes: int = 64 * 1024 * 1024


def limits_from_config(config: dict) -> Limits:
    from .http import BitbucketExportError
    table = config.get('limits', {})
    if not isinstance(table, dict) or set(table) - {f.name for f in fields(Limits)}:
        raise BitbucketExportError('Invalid [limits] table or unknown limit setting.')
    for name, value in table.items():
        numeric = isinstance(value, (int, float)) if name == 'timeout_seconds' else isinstance(value, int)
        if isinstance(value, bool) or not numeric or value <= 0 or (isinstance(value, float) and not math.isfinite(value)):
            raise BitbucketExportError('Export limits must be finite positive numbers; byte/page limits must be integers.')
    return Limits(**table)


class Budget:
    def __init__(self, limits: Limits):
        self.limits = limits
        self.deadline = time.monotonic() + limits.timeout_seconds
        self.total_bytes = 0
        self.pages = 0

    def remaining(self) -> float:
        from .http import ExportLimitError
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise ExportLimitError('Export deadline exceeded; no complete export is available.')
        return remaining

    def page(self) -> None:
        from .http import ExportLimitError
        self.remaining()
        self.pages += 1
        if self.pages > self.limits.max_pages:
            raise ExportLimitError('Export pagination limit exceeded.')


_current: ContextVar[Budget | None] = ContextVar('export_budget', default=None)


@contextmanager
def export_budget(limits: Limits | None = None):
    if _current.get() is not None:
        yield _current.get()
        return
    budget = Budget(limits or Limits())
    token = _current.set(budget)
    try:
        yield budget
        budget.remaining()
    finally:
        _current.reset(token)


def current_budget() -> Budget:
    budget = _current.get()
    if budget is None:
        raise RuntimeError('HTTP operation outside export budget')
    return budget


def bounded_export(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        with export_budget():
            return function(*args, **kwargs)
    return wrapped
