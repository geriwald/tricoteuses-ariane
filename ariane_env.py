"""Small .env loader for Ariane command-line scripts.

The bricks intentionally avoid a python-dotenv dependency. This loader supports
the subset we need: KEY=value lines, optional "export", comments, and quotes.
Existing process environment variables win by default.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _strip_inline_comment(value: str) -> str:
    quote = ""
    escaped = False
    for i, ch in enumerate(value):
        if escaped:
            escaped = False
            continue
        if ch == "\\":
            escaped = True
            continue
        if quote:
            if ch == quote:
                quote = ""
            continue
        if ch in ("'", '"'):
            quote = ch
            continue
        if ch == "#" and (i == 0 or value[i - 1].isspace()):
            return value[:i].rstrip()
    return value.strip()


def _decode_value(raw: str) -> str:
    value = _strip_inline_comment(raw.strip())
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        value = value[1:-1]
        if raw.strip()[0] == '"':
            value = value.encode("utf-8").decode("unicode_escape")
    return value


def load_dotenv(path: str | os.PathLike[str] | None = None, *, override: bool = False) -> dict[str, str]:
    """Load repository .env into os.environ.

    Returns the variables inserted or overwritten. Missing .env is not an error.
    """
    env_path = Path(path) if path is not None else Path(__file__).resolve().parent / ".env"
    try:
        lines = env_path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return {}

    loaded: dict[str, str] = {}
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        if "=" not in line:
            continue
        key, raw_value = line.split("=", 1)
        key = key.strip()
        if not _KEY.match(key):
            continue
        if not override and key in os.environ:
            continue
        value = _decode_value(raw_value)
        os.environ[key] = value
        loaded[key] = value
    return loaded
