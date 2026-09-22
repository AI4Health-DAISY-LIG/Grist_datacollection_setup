"""Small configuration helpers used by the command-line entry point."""

from __future__ import annotations

import os
from pathlib import Path


def load_env_file(path: str | Path = ".env") -> None:
    """Load simple KEY=VALUE entries without overwriting the shell environment."""
    env_path = Path(path)
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = (part.strip() for part in line.split("=", 1))
        if value[:1] in {"\"", "'"} and value[-1:] == value[:1]:
            value = value[1:-1]
        os.environ.setdefault(key, value)