"""Redact credentials before writing diagnostic messages."""
from __future__ import annotations

import base64
import re
from typing import Iterable


def redact(message: str, tokens: Iterable[str | None] = (), usernames: Iterable[str | None] = ()) -> str:
    secrets = {token for token in tokens if token}
    for token in tuple(secrets):
        for username in usernames:
            if username:
                secrets.add(base64.b64encode(f'{username}:{token}'.encode()).decode())
    # Also hide Authorization values supplied by an upstream service or gateway.
    message = re.sub(r'(?i)\b(Bearer|Basic)\s+[A-Za-z0-9._~+/-]+=*', r'\1 [REDACTED]', message)
    for secret in sorted(secrets, key=len, reverse=True):
        message = message.replace(secret, '[REDACTED]')
    return message
