"""Optimistic locking: refuse to overwrite a record somebody else changed while you were looking at it."""
from fastapi import HTTPException

CONFLICT_MESSAGE = "This record was changed by someone else while you were editing it. Reload to see their changes."


def check_version(obj, sent: int | None) -> None:
    """`sent` is the version the client loaded. None means the client doesn't care (scripts, older callers)."""
    if sent is not None and sent != (obj.version or 1):
        raise HTTPException(409, CONFLICT_MESSAGE)


def bump(obj) -> None:
    obj.version = (obj.version or 1) + 1
