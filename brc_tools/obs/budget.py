"""Single-process bounded transport for dedicated acquisition workers.

Wrap the existing libraries' requests transport, including import-time token checks.
Never use this process-global context in a multithreaded service.
"""

from __future__ import annotations

import contextlib
import fcntl
import json
import os
import tempfile
import time
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlparse


class AcquisitionStopped(RuntimeError):
    pass


class Budget:
    def __init__(
        self,
        root,
        provider,
        batch,
        *,
        allowed=False,
        max_requests=8,
        interval=30.0,
        clock=time.time,
        sleep=time.sleep,
    ):
        if not 1 <= max_requests <= 8 or interval < 30:
            raise ValueError("pilot permits 1..8 requests and spacing >=30 seconds")
        self.root, self.provider, self.batch = Path(root), provider, batch
        self.allowed, self.maximum, self.interval = allowed, max_requests, interval
        self.clock, self.sleep = clock, sleep
        self.state_path = self.root / f"{provider}.json"

    def _write(self, state):
        fd, name = tempfile.mkstemp(dir=self.root, prefix=".ledger-")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(state, f, sort_keys=True)
                f.flush()
                os.fsync(f.fileno())
            os.replace(name, self.state_path)
        finally:
            if os.path.exists(name):
                os.unlink(name)

    def acknowledge_redirect(self, reason):
        """Explicit operator review only; never clear quota/auth/timeout failures."""
        if not reason.strip():
            raise ValueError("review reason required")
        with (self.root / f"{self.provider}.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            state = json.loads(self.state_path.read_text())
            entries = [e for batch in state["batches"].values() for e in batch]
            last = max(entries, key=lambda e: e["utc_epoch"])
            if last.get("status") not in (301, 302, 307, 308):
                raise AcquisitionStopped(
                    "only a reviewed redirect can be acknowledged here"
                )
            state.setdefault("reviews", []).append(
                {"reason": reason, "utc_epoch": self.clock()}
            )
            state["stopped"] = None
            self._write(state)

    @contextlib.contextmanager
    def transport(self):
        if not self.allowed:
            raise AcquisitionStopped(
                "live access requires recorded no-charge/budget confirmation"
            )
        import requests

        self.root.mkdir(parents=True, exist_ok=True)
        with (self.root / f"{self.provider}.lock").open("a") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise AcquisitionStopped(
                    "another acquisition worker holds the provider lock"
                ) from None
            state = (
                json.loads(self.state_path.read_text())
                if self.state_path.exists()
                else {"batches": {}, "last": 0}
            )
            if state.get("stopped"):
                raise AcquisitionStopped(
                    "provider is stopped; review its ledger before a new run"
                )
            entries = state["batches"].setdefault(self.batch, [])
            original = requests.sessions.Session.send

            def guarded(session, request, **kwargs):
                host = urlparse(request.url).hostname
                allowed_hosts = {
                    "synoptic": {"api.synopticdata.com"},
                    "igra2": {"www1.ncdc.noaa.gov", "www.ncei.noaa.gov"},
                }
                if request.method != "GET" or host not in allowed_hosts[self.provider]:
                    raise AcquisitionStopped("unplanned transport host or method")
                if len(entries) >= self.maximum:
                    raise AcquisitionStopped("request budget exhausted")
                wait = self.interval - (self.clock() - state["last"])
                if wait > 0:
                    self.sleep(wait)
                # Mark before send: killed workers still spend a request and stop resume.
                entry = {
                    "utc_epoch": self.clock(),
                    "path": urlparse(request.url).path,
                    "outcome": "in_flight",
                }
                entries.append(entry)
                state.update(last=self.clock(), stopped="incomplete request")
                self._write(state)
                kwargs.update(timeout=(10, 60), allow_redirects=False)
                try:
                    # requests defaults to no retries; disallow a caller's retry adapter.
                    adapter = session.get_adapter(request.url)
                    if adapter.max_retries.total not in (0, False):
                        raise AcquisitionStopped("transport retries are not permitted")
                    response = original(session, request, **kwargs)
                    entry.update(
                        status=response.status_code,
                        retry_after=response.headers.get("Retry-After"),
                    )
                    if not 200 <= response.status_code < 300:
                        raise AcquisitionStopped(
                            f"HTTP {response.status_code}; batch stopped"
                        )
                    if self.provider == "synoptic":
                        summary = response.json().get("SUMMARY", {})
                        entry["response_code"] = summary.get("RESPONSE_CODE")
                        msg = str(summary.get("RESPONSE_MESSAGE", "")).lower()
                        if summary.get("RESPONSE_CODE") != 1 or any(
                            w in msg
                            for w in ("quota", "billing", "too many", "unauthorized")
                        ):
                            raise AcquisitionStopped(
                                "API payload indicates rejection; batch stopped"
                            )
                    entry["outcome"] = "success"
                    state["stopped"] = None
                    return response
                except Exception as exc:
                    entry["outcome"] = type(exc).__name__
                    # Never expose provider exceptions: they can embed full credential URLs.
                    raise AcquisitionStopped(
                        f"{entry['outcome']}; inspect the sanitized request ledger"
                    ) from None
                finally:
                    state["last"] = self.clock()
                    self._write(state)

            with patch.object(requests.sessions.Session, "send", guarded):
                yield
