"""Canonical JSON envelope shared by every debrief CLI command.

Success: {"ok": true, "schemaVersion": 1, "data": {...}}
Failure: {"ok": false, "schemaVersion": 1, "error": {"code": "DEBRIEF_XXX", "message": "..."}}
"""

import json
import sys
from typing import Any, NoReturn, Optional

SCHEMA_VERSION = 1


class KernelError(Exception):
    """A structured CLI failure carrying a stable error code."""

    def __init__(self, code: str, message: str, exit_code: int = 1):
        super().__init__(message)
        self.code = code
        self.message = message
        self.exit_code = exit_code


class UsageError(KernelError):
    def __init__(self, message: str):
        super().__init__("DEBRIEF_USAGE", message, exit_code=2)


def ok(data: Any) -> dict:
    return {"ok": True, "schemaVersion": SCHEMA_VERSION, "data": data}


def fail(code: str, message: str) -> dict:
    return {"ok": False, "schemaVersion": SCHEMA_VERSION, "error": {"code": code, "message": message}}


def print_envelope(payload: dict) -> None:
    """Write the single-line JSON envelope to stdout (UTF-8, newline-terminated)."""
    sys.stdout.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def fail_and_exit(err: KernelError) -> NoReturn:
    print_envelope(fail(err.code, err.message))
    sys.exit(err.exit_code)


def exit_with_failure(code: str, message: str, exit_code: int = 1) -> NoReturn:
    fail_and_exit(KernelError(code, message, exit_code))


def read_stdin_json() -> dict:
    """Parse the single JSON document expected on stdin for write commands."""
    raw = sys.stdin.read()
    if not raw.strip():
        raise UsageError("stdin JSON payload required (e.g. echo '...' | debrief ...)")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise KernelError("DEBRIEF_VALIDATION", f"stdin is not valid JSON: {exc}") from None
    if not isinstance(payload, dict):
        raise KernelError("DEBRIEF_VALIDATION", "stdin JSON must be an object")
    return payload


def require_string(payload: dict, key: str, *, allow_empty: bool = False) -> Optional[str]:
    value = payload.get(key)
    if value is None:
        raise KernelError("DEBRIEF_VALIDATION", f"missing required field '{key}'")
    if not isinstance(value, str):
        raise KernelError("DEBRIEF_VALIDATION", f"field '{key}' must be a string")
    if not allow_empty and not value.strip():
        raise KernelError("DEBRIEF_VALIDATION", f"field '{key}' must not be empty")
    return value
