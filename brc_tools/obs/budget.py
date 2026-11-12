"""Single-process bounded transport for dedicated acquisition workers.

Wrap the existing libraries' requests transport, including import-time token checks.
Never use this process-global context in a multithreaded service.

Tiers name the caps a human authorised; the ledger records every request, so a
rolling cap can be computed from it without a schema change:

* ``pilot`` (default): at most 8 requests per batch, no rolling cap -- the
  pseudoprofile pilot contract of 2026-11-10.
* ``historical``: at most 60 requests per batch and 300 per rolling 24 h -- the
  basin-soil-snowmelt contract of 2026-11-12.

Both keep one request in flight, 30 s after each completion, no retries.
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

TIERS = {
    "pilot": dict(max_requests=8, rolling_cap=None, rolling_hours=None),
    "historical": dict(max_requests=60, rolling_cap=300, rolling_hours=24),
}

_REJECTION_WORDS = ("quota", "billing", "too many", "unauthorized")


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
        tier="pilot",
        max_requests=None,
        interval=30.0,
        clock=time.time,
        sleep=time.sleep,
    ):
        if tier not in TIERS:
            raise ValueError(f"unknown budget tier {tier!r}; known: {sorted(TIERS)}")
        spec = TIERS[tier]
        if max_requests is None:
            max_requests = spec["max_requests"]
        if not 1 <= max_requests <= spec["max_requests"] or interval < 30:
            raise ValueError(
                f"tier {tier!r} permits 1..{spec['max_requests']} requests per batch "
                "and spacing >=30 seconds"
            )
        self.root, self.provider, self.batch = Path(root), provider, batch
        self.allowed, self.maximum, self.interval = allowed, max_requests, interval
        self.tier = tier
        self.rolling_cap, self.rolling_hours = spec["rolling_cap"], spec["rolling_hours"]
        self.clock, self.sleep = clock, sleep
        self.state_path = self.root / f"{provider}.json"

    # -- ledger -----------------------------------------------------------------

    def _read(self):
        return (
            json.loads(self.state_path.read_text())
            if self.state_path.exists()
            else {"batches": {}, "last": 0}
        )

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

    def _recent(self, state):
        """Every recorded request, any batch, inside the rolling window."""
        if not self.rolling_cap:
            return []
        cutoff = self.clock() - 3600.0 * self.rolling_hours
        return [
            e
            for entries in state["batches"].values()
            for e in entries
            if e.get("utc_epoch", 0) >= cutoff
        ]

    def headroom(self):
        """(left in this batch, left in the rolling window, seconds until the window
        frees one request). Read-only; takes no lock; None where no cap applies."""
        state = self._read()
        in_batch = len(state["batches"].get(self.batch, []))
        left_batch = max(self.maximum - in_batch, 0)
        if not self.rolling_cap:
            return left_batch, None, 0.0
        recent = sorted(e["utc_epoch"] for e in self._recent(state))
        left_window = max(self.rolling_cap - len(recent), 0)
        if left_window > 0:
            return left_batch, left_window, 0.0
        # The oldest request inside the window frees the first slot.
        oldest = recent[len(recent) - self.rolling_cap]
        wait = oldest + 3600.0 * self.rolling_hours - self.clock()
        return left_batch, 0, max(wait, 0.0)

    # -- operator reviews ---------------------------------------------------------

    def _last_entry(self, state):
        entries = [e for batch in state["batches"].values() for e in batch]
        if not entries:
            raise AcquisitionStopped("ledger has no requests to review")
        return max(entries, key=lambda e: e["utc_epoch"])

    def acknowledge_redirect(self, reason):
        """Explicit operator review only; never clear quota/auth/timeout failures."""
        if not reason.strip():
            raise ValueError("review reason required")
        with (self.root / f"{self.provider}.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            state = json.loads(self.state_path.read_text())
            last = self._last_entry(state)
            if last.get("status") not in (301, 302, 307, 308):
                raise AcquisitionStopped(
                    "only a reviewed redirect can be acknowledged here"
                )
            state.setdefault("reviews", []).append(
                {"reason": reason, "utc_epoch": self.clock()}
            )
            state["stopped"] = None
            self._write(state)

    def acknowledge_empty_probe(self, reason):
        """Clear a stop caused by a *no data* answer (HTTP 200, RESPONSE_CODE 2 and no
        quota/auth wording). A probe into history the token does not cover is such an
        answer. Anything else stays stopped."""
        if not reason.strip():
            raise ValueError("review reason required")
        with (self.root / f"{self.provider}.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            state = json.loads(self.state_path.read_text())
            last = self._last_entry(state)
            msg = str(last.get("response_message", "")).lower()
            if (
                last.get("status") != 200
                or last.get("response_code") != 2
                or any(w in msg for w in _REJECTION_WORDS)
            ):
                raise AcquisitionStopped(
                    "only a 200 / RESPONSE_CODE 2 'no data' answer can be acknowledged here"
                )
            state.setdefault("reviews", []).append(
                {"reason": reason, "utc_epoch": self.clock(), "kind": "empty_probe"}
            )
            state["stopped"] = None
            self._write(state)

    # -- transport ----------------------------------------------------------------

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
            state = self._read()
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
                if self.rolling_cap and len(self._recent(state)) >= self.rolling_cap:
                    raise AcquisitionStopped(
                        f"rolling {self.rolling_hours} h request cap reached"
                    )
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
                    "tier": self.tier,
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
                        # A sanitized fragment only: the message never carries the URL.
                        entry["response_message"] = msg[:120]
                        if summary.get("RESPONSE_CODE") != 1 or any(
                            w in msg for w in _REJECTION_WORDS
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
