"""The small contract every query backend satisfies."""

from __future__ import annotations

import re
from typing import Any, Protocol

Row = dict[str, Any]


class BackendUnavailable(RuntimeError):
    """The backend cannot serve queries right now; the message says what to do."""


class Backend(Protocol):
    name: str
    label: str
    read_only: bool

    def query(self, sql: str) -> list[Row]: ...


_COMMENTS = re.compile(r"--[^\n]*|/\*.*?\*/", re.DOTALL)
_WRITE_KEYWORDS = re.compile(
    r"\b(insert|update|delete|merge|drop|alter|create|truncate|grant|revoke|exec|execute|into)\b",
    re.IGNORECASE,
)


def assert_read_only(sql: str) -> None:
    """Reject anything but a single SELECT/WITH statement (defence in depth, not a boundary).

    The real boundary is the identity's permissions on the SQL analytics endpoint.
    """
    body = _COMMENTS.sub(" ", sql).strip().rstrip(";").strip()
    if not body.lower().startswith(("select", "with")):
        raise PermissionError("Only SELECT/WITH queries are allowed on a read-only backend")
    if ";" in body or _WRITE_KEYWORDS.search(body):
        raise PermissionError("Write or multi-statement SQL is not allowed on a read-only backend")
