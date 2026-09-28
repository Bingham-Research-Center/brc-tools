"""Clean and push data to the basinwx website.

John Lawson, July 2025
"""
import json
import mimetypes
import socket
import os
import re
import sys
import time
from datetime import datetime, timezone
import requests

import numpy as np
import pandas as pd

def clean_dataframe_for_json(df):
    # If the dataframe is a Polars dataframe, convert it to Pandas.
    if hasattr(df, "to_pandas"):
        df = df.to_pandas()

    # Replace NaN with None to become proper JSON null.
    df = df.where(pd.notnull(df), None)

    # Clean string columns (remove unnecessary quotes).
    for col in df.select_dtypes(include=['object']):
        df[col] = df[col].str.strip('"')

    return df

def save_json(df, fpath, orient='records'):
    if hasattr(df, "to_pandas"):
        df = df.to_pandas()

    # Pandas will map NaN → null automatically
    df.to_json(fpath, orient=orient, indent=2, date_format="iso")
    print(f"Exported {len(df)} records to {fpath}")
    return


def _stamp():
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def _say(msg, *, err=False):
    """stdout (or stderr) with a UTC stamp.

    Cron redirects our stdout to ~/logs/*.log. Until 2026-09 none of those lines
    carried a time: obs.log held 249k lines and 365 failures and could not say
    when a single one of them happened.
    """
    print(f"{_stamp()} {msg}", file=sys.stderr if err else sys.stdout)


RECEIPTS_ENV = 'BASINWX_RECEIPTS_LOG'
DEFAULT_RECEIPTS = os.path.join(os.path.expanduser('~'), 'logs', 'basinwx',
                                'push_receipts.jsonl')


def _receipt(**fields):
    """Append one JSON line per upload attempt to $BASINWX_RECEIPTS_LOG.

    Default ~/logs/basinwx/push_receipts.jsonl; set the variable empty to disable.
    Never raises: a receipt is worth less than the upload it describes.
    """
    path = os.environ.get(RECEIPTS_ENV, DEFAULT_RECEIPTS)
    if not path:
        return
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'a') as f:
            f.write(json.dumps({'ts': _stamp(), **fields}, sort_keys=True) + '\n')
    except OSError as e:
        _say(f"WARNING receipt not written to {path}: {e}", err=True)


def _verify_visible(server_address, served_path):
    """HEAD the path the server says it stored the file at.

    True on 200, False otherwise, None when skipped (BASINWX_VERIFY_UPLOADS=0 or
    no path in the response). A 200 from the upload route means the server
    accepted the bytes; this asks whether a reader can now fetch them.
    """
    if os.environ.get('BASINWX_VERIFY_UPLOADS', '1') == '0' or not served_path:
        return None
    try:
        return requests.head(f"{server_address}{served_path}", timeout=10).status_code == 200
    except requests.exceptions.RequestException:
        return False


def _post_json_to_url(server_address, fpath, file_data, api_key, *, role="PRIMARY"):
    """Upload one file to one server. Return True on HTTP 200.

    Named for its original JSON-only life; it now also carries the outlook
    .md files, so the MIME type follows the file extension.

    Every exit writes a receipt (see _receipt) and every line is stamped.
    """
    endpoint = f"{server_address}/api/upload/{file_data}"
    hostname = socket.getfqdn()
    headers = {'x-api-key': api_key, 'x-client-hostname': hostname}
    prefix = f"[{role} {server_address}]"
    name = os.path.basename(fpath)
    receipt = dict(role=role, url=server_address, data_type=file_data, file=name)
    t0 = time.monotonic()

    def elapsed_ms():
        return int((time.monotonic() - t0) * 1000)

    try:
        health_response = requests.get(f"{server_address}/api/health", timeout=10)
        _say(f"{prefix} health {health_response.status_code}")
    except requests.exceptions.RequestException as e:
        _say(f"{prefix} health check failed: {e}")
        _receipt(**receipt, stage='health', ok=False, status=None,
                 error=str(e)[:300], elapsed_ms=elapsed_ms())
        return False

    _say(f"{prefix} uploading {name} to {endpoint}")
    try:
        mime = mimetypes.guess_type(str(fpath))[0] or 'application/octet-stream'
        with open(fpath, 'rb') as f:
            files = {'file': (name, f, mime)}
            response = requests.post(endpoint, files=files, headers=headers, timeout=30)
        if response.status_code == 200:
            try:
                served_path = response.json().get('path')
            except ValueError:
                served_path = None
            visible = _verify_visible(server_address, served_path)
            note = "" if visible in (True, None) else f" (WARNING: not visible at {served_path} afterwards)"
            _say(f"{prefix} ✅ uploaded {name}{note}")
            _receipt(**receipt, stage='upload', ok=True, status=200,
                     verified=visible, elapsed_ms=elapsed_ms())
            return True
        _say(f"{prefix} ❌ upload failed ({response.status_code}): {response.text}")
        _receipt(**receipt, stage='upload', ok=False, status=response.status_code,
                 error=response.text[:300], elapsed_ms=elapsed_ms())
        return False
    except requests.exceptions.Timeout:
        _say(f"{prefix} ❌ upload timed out after 30s")
        _receipt(**receipt, stage='upload', ok=False, status=None,
                 error='timeout after 30s', elapsed_ms=elapsed_ms())
        return False
    except requests.exceptions.RequestException as e:
        _say(f"{prefix} ❌ upload error: {e}")
        _receipt(**receipt, stage='upload', ok=False, status=None,
                 error=str(e)[:300], elapsed_ms=elapsed_ms())
        return False


def send_json_to_server(server_address, fpath, file_data, API_KEY):
    """Upload JSON to a single server. Preserved for the clyfar import contract."""
    _post_json_to_url(server_address, fpath, file_data, API_KEY, role="PRIMARY")


def send_json_to_all(server_addresses, fpath, file_data, api_key):
    """Fan-out upload. First URL is primary (failure raises), rest are mirrors
    (failure logged, non-fatal). Returns a {url: ok} mapping.
    """
    if not server_addresses:
        raise ValueError("server_addresses is empty")

    results = {}
    for idx, url in enumerate(server_addresses):
        role = "PRIMARY" if idx == 0 else "MIRROR"
        results[url] = _post_json_to_url(url, fpath, file_data, api_key, role=role)

    primary = server_addresses[0]
    mirror_failures = [u for u in server_addresses[1:] if not results[u]]
    if mirror_failures:
        _say(f"WARNING mirror uploads failed: {', '.join(mirror_failures)}")
    if not results[primary]:
        raise RuntimeError(f"Primary upload to {primary} failed for {fpath}")
    return results


class UploadIncomplete(RuntimeError):
    """The primary host did not receive every file in a bundle."""


class FanoutSession:
    """Fan-out uploader with a per-host memory across a whole bundle.

    ``send_json_to_all`` judges one file at a time, so a host that rejected a
    run file still receives the small ``*_index.json`` that follows it. That is
    how basinwx.dev spent 2026-04-27 to 2026-08-25 serving an index advertising
    ~1.5 MB run files nginx had 413'd: the index is ~3 KB, so it sailed through
    every cycle and the job exited 0.

    A session marks a host failed on its first bad response and skips it for the
    rest of the bundle -- the index included. Upload the index last and a host
    either gets a consistent set or keeps its previous, honest one.

    Mirrors stay best-effort: only the primary can fail the job. But a mirror
    failure is no longer silent -- ``finish`` prints an ALERT to stderr so the
    cron wrapper can surface it and MAILTO fires.
    """

    ALERT = "ALERT_MIRROR_INCOMPLETE"

    def __init__(self, server_addresses, api_key):
        if not server_addresses:
            raise ValueError("server_addresses is empty")
        self.urls = list(server_addresses)
        self.primary = self.urls[0]
        self.api_key = api_key
        self.failed = {}      # url -> filename of its first failure
        self.skipped = {}     # url -> count of files not attempted after that
        self.sent = {url: 0 for url in self.urls}

    def send(self, fpath, file_data):
        """Upload one file to every host still healthy. Returns {url: ok}."""
        results = {}
        name = os.path.basename(fpath)
        for idx, url in enumerate(self.urls):
            if url in self.failed:
                self.skipped[url] = self.skipped.get(url, 0) + 1
                _say(f"[SKIP {url}] {name} -- host already failed on "
                     f"{self.failed[url]}")
                results[url] = False
                continue
            role = "PRIMARY" if idx == 0 else "MIRROR"
            ok = _post_json_to_url(url, fpath, file_data, self.api_key, role=role)
            results[url] = ok
            if ok:
                self.sent[url] += 1
            else:
                self.failed[url] = name
        return results

    def finish(self):
        """Report the bundle. Raise if the primary is incomplete.

        Returns the {url: files_sent} tally so callers can log it.
        """
        for url in self.urls:
            if url not in self.failed:
                continue
            missed = self.skipped.get(url, 0)
            role = "PRIMARY" if url == self.primary else "MIRROR"
            _say(f"[{role} {url}] incomplete: failed on {self.failed[url]}"
                 f"{f', skipped {missed} later file(s)' if missed else ''}")

        if self.primary in self.failed:
            raise UploadIncomplete(
                f"Primary upload to {self.primary} failed for "
                f"{self.failed[self.primary]}; bundle abandoned")

        mirror_failures = [u for u in self.urls[1:] if u in self.failed]
        if mirror_failures:
            # stderr, so the cron wrapper can spot it without parsing the log.
            _say(f"{self.ALERT} hosts={','.join(mirror_failures)} "
                 f"primary={self.primary} ok", err=True)
        return dict(self.sent)


def send_bundle_to_all(server_addresses, fpaths, file_data, api_key):
    """Upload an ordered bundle, gating later files on earlier success.

    Put the index last: any host that rejected a run file will not receive it.
    """
    session = FanoutSession(server_addresses, api_key)
    for fpath in fpaths:
        session.send(fpath, file_data)
    return session.finish()


def _read_url_file(path):
    with open(path, 'r') as f:
        raw = f.read()
    return [u.strip().rstrip('/') for u in raw.replace('\n', ',').split(',') if u.strip()]


def load_config():
    """Single-URL config loader. Preserved for the clyfar import contract.
    Returns (api_key, primary_url). New brc-tools code should use load_config_urls().
    """
    api_key, urls = load_config_urls()
    return api_key, urls[0]


def load_config_urls():
    """Load API key and the full list of upload destinations.

    Resolution order for URLs:
      1. BASINWX_API_URLS env var (comma-separated; first = primary, rest = mirrors).
      2. ~/.config/ubair-website/website_urls (comma- or newline-separated).
      3. ~/.config/ubair-website/website_url (legacy single URL → one-element list).
    API key is always read from DATA_UPLOAD_API_KEY.
    """
    api_key = os.environ.get('DATA_UPLOAD_API_KEY', '').strip()
    if not api_key:
        raise ValueError("DATA_UPLOAD_API_KEY environment variable not set")
    if not re.fullmatch(r'[0-9a-fA-F]{32,128}', api_key):
        raise ValueError(
            f"API key should be 32-128 hex characters, got {len(api_key)}")

    env_urls = os.environ.get('BASINWX_API_URLS', '').strip()
    if env_urls:
        urls = [u.strip().rstrip('/') for u in env_urls.split(',') if u.strip()]
        if urls:
            return api_key, urls

    config_dir = os.path.join(os.path.expanduser('~'), '.config', 'ubair-website')
    plural = os.path.join(config_dir, 'website_urls')
    if os.path.exists(plural):
        urls = _read_url_file(plural)
        if urls:
            return api_key, urls

    singular = os.path.join(config_dir, 'website_url')
    if os.path.exists(singular):
        urls = _read_url_file(singular)
        if urls:
            return api_key, urls

    raise FileNotFoundError(
        "No upload URL found. Set BASINWX_API_URLS or create "
        "~/.config/ubair-website/website_urls (see docs for setup)."
    )