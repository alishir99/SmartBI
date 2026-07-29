"""Make the scripts' progress output survive a non-UTF-8 console.

Every script in here prints Swedish names and the odd arrow. A Windows console hands Python
a cp1252 stdout, so `python scripts/generate_data.py` — the first command in the README —
died on its opening line before writing a single row. Encoding is not something the reader
should have to configure to run the documented setup.
"""

from __future__ import annotations

import sys


def use_utf8_stdout() -> None:
    """Force UTF-8 on stdout/stderr where the stream supports it.

    `errors="replace"` rather than `strict`: a mangled glyph in a progress line is a
    cosmetic problem, and it must never be the reason a seed run fails.
    """
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
