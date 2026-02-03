from __future__ import annotations


def redact_token(token: str, *, keep: int = 4) -> str:
    if not token:
        return ""
    if len(token) <= keep:
        return "*" * len(token)
    return f"{token[:keep]}…{'*' * 8}"
