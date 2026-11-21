"""A finite timeout for every ``requests`` call that passes none.

Herbie (2026.3.0 and 2026.10.0) downloads each index with ``requests.get(self.idx)``
and checks files with ``requests.head(url)``, both with no timeout. A connection that
opens and then never answers blocks the caller forever. On 18-19 Nov 2026 four
BasinWX cron runs sat for 2-3 days, each on one TLS connection to S3 whose server
had sent nothing for 67 hours, and they held 2.3 GB of the cron host's 8 GiB.

``ensure_request_timeouts`` wraps ``requests.Session.request`` once per process. A
call that gives no timeout (or ``timeout=None``) gets ``DEFAULT_TIMEOUT``, and a call
that gives one keeps it. The read value bounds the gap between bytes, not the whole
transfer, so a slow download that keeps arriving is never cut off. NWPSource and the
other Herbie entry points call it before they reach Herbie.
"""

from __future__ import annotations

import functools

import requests

#: (connect, read) in seconds. The read timeout is the longest wait for the next
#: bytes. A healthy S3 index answers in under a second.
DEFAULT_TIMEOUT = (15.0, 120.0)

_ORIGINAL_REQUEST = None


def ensure_request_timeouts(timeout=DEFAULT_TIMEOUT) -> None:
    """Make every ``requests`` call in this process that passes no timeout use one.

    Idempotent: the first call installs the wrapper, and later calls change only the
    default. Explicit timeouts are left alone.
    """
    global _ORIGINAL_REQUEST
    _Default.value = timeout
    if _ORIGINAL_REQUEST is not None:
        return
    original = requests.sessions.Session.request

    @functools.wraps(original)
    def request(self, method, url, *args, **kwargs):
        # timeout is the 7th parameter after url; positional use is left untouched.
        if len(args) < 7 and kwargs.get("timeout") is None:
            kwargs["timeout"] = _Default.value
        return original(self, method, url, *args, **kwargs)

    requests.sessions.Session.request = request
    _ORIGINAL_REQUEST = original


def _uninstall() -> None:
    """Restore ``requests`` as it was (tests only)."""
    global _ORIGINAL_REQUEST
    if _ORIGINAL_REQUEST is not None:
        requests.sessions.Session.request = _ORIGINAL_REQUEST
        _ORIGINAL_REQUEST = None
    _Default.value = DEFAULT_TIMEOUT


class _Default:
    value = DEFAULT_TIMEOUT
