"""Send a near-static file only when it changed, or when the last send is getting old.

The obs cron fetches station metadata every 5 minutes and, until 2026-11-20, uploaded it
every time: 288 byte-identical files a day to each BasinWX host (59,955 on basinwx.dev by
then). The website reads only the newest one and its manifest expects one every 6 hours.

The gate keeps a small JSON state file holding the SHA-256 of the last file every host
accepted and when that was. A file is due when there is no state, the state is unreadable,
the content differs, or the last send is older than ``max_age_seconds``.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
from pathlib import Path


def content_digest(path: str | os.PathLike[str]) -> str:
    """SHA-256 of a file's bytes, as hex."""
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def is_due(
    path: str | os.PathLike[str],
    state_path: str | os.PathLike[str],
    *,
    max_age_seconds: float,
    now: float | None = None,
) -> bool:
    """True when ``path`` should be sent: new content, no usable state, or state too old."""
    now = time.time() if now is None else now
    try:
        state = json.loads(Path(state_path).read_text())
        last_digest = state["sha256"]
        last_sent = float(state["sent_at"])
    except (OSError, ValueError, KeyError, TypeError):
        return True
    if last_digest != content_digest(path):
        return True
    return (now - last_sent) >= max_age_seconds


def record_sent(
    path: str | os.PathLike[str],
    state_path: str | os.PathLike[str],
    *,
    now: float | None = None,
) -> None:
    """Remember that ``path`` reached every host. Written atomically."""
    now = time.time() if now is None else now
    state = {"sha256": content_digest(path), "sent_at": now, "file": Path(path).name}
    state_path = Path(state_path)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=state_path.parent, prefix=".resend_gate_")
    try:
        with os.fdopen(fd, "w") as fh:
            json.dump(state, fh)
        os.replace(tmp, state_path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
