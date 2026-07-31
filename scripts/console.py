"""Make the scripts' progress output survive a non-UTF-8 console."""

from __future__ import annotations

import sys


def use_utf8_stdout() -> None:
    """Force UTF-8 on stdout/stderr where the stream supports it."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
