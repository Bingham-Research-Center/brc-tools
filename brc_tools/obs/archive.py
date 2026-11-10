"""Credential-free, content-addressed observation archives. No HTTP imports."""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path

VERSION = 1


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def encode(value) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()


def sanitize(value):
    if isinstance(value, dict):
        return {
            k: (
                "<redacted>"
                if re.search(r"token|password|api.?key|authorization", k, re.I)
                else sanitize(v)
            )
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [sanitize(v) for v in value]
    if isinstance(value, str):
        return re.sub(
            r"(?i)((?:token|api_key|apikey|authorization)=)[^&\s\"<>]+",
            r"\1<redacted>",
            value,
        )
    return value


def atomic(path: Path, data: bytes):
    """Publish once; a collision is safe only when the existing bytes agree."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=path.parent, prefix=".pending-")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        try:
            os.link(name, path)
        except FileExistsError:
            if path.read_bytes() != data:
                raise ValueError(
                    "archive collision or corrupt existing object"
                ) from None
    finally:
        os.unlink(name)


def put(root: Path, value) -> str:
    blob = gzip.compress(encode(value), mtime=0)
    sha = digest(blob)
    atomic(Path(root) / "objects" / f"{sha}.json.gz", blob)
    return sha


def get(root: Path, sha: str):
    if not re.fullmatch("[0-9a-f]{64}", sha):
        raise ValueError("invalid object digest")
    blob = (Path(root) / "objects" / f"{sha}.json.gz").read_bytes()
    if digest(blob) != sha:
        raise ValueError("archive digest mismatch")
    return json.loads(gzip.decompress(blob))


def preserve(
    root: Path, payload: dict, service: str, params: dict, versions: dict
) -> Path:
    """Deduplicate metadata; retain values/QC/unknown fields without quantization."""
    root = Path(root)
    data = sanitize(payload)
    # Only documented transport timing is discarded, never scientific fields.
    for key in ("RESPONSE_TIME", "DATA_QUERY_TIME"):
        data.get("SUMMARY", {}).pop(key, None)
    if "STATION" in data:
        stations = []
        for station in data["STATION"]:
            variable = {k: v for k, v in station.items() if k in ("OBSERVATIONS", "QC")}
            meta = {k: v for k, v in station.items() if k not in variable}
            stations.append({"metadata_ref": put(root, meta), **variable})
        data["STATION"] = stations
    sha = put(root, data)
    receipt = dict(
        schema_version=VERSION,
        format="canonical-lossless-observations",
        discarded=["SUMMARY.RESPONSE_TIME", "SUMMARY.DATA_QUERY_TIME"],
        service=service,
        params=sanitize(params),
        payload_sha256=sha,
        versions=versions,
        requested_utc=datetime.now(timezone.utc).isoformat(),
        outcome="success"
        if payload.get("STATION", payload.get("MNET", []))
        else "empty",
    )
    path = root / "receipts" / f"{digest(encode(receipt))}.json"
    atomic(path, encode(receipt))
    return path


def replay(receipt_path: Path) -> tuple[dict, dict]:
    receipt_path = Path(receipt_path)
    receipt_bytes = receipt_path.read_bytes()
    if (
        re.fullmatch("[0-9a-f]{64}", receipt_path.stem)
        and digest(receipt_bytes) != receipt_path.stem
    ):
        raise ValueError("receipt digest mismatch")
    receipt = json.loads(receipt_bytes)
    if receipt["schema_version"] != VERSION:
        raise ValueError("unsupported archive version")
    root = receipt_path.parent.parent
    data = get(root, receipt["payload_sha256"])
    if "STATION" in data:
        data["STATION"] = [
            {
                **get(root, s["metadata_ref"]),
                **{k: v for k, v in s.items() if k != "metadata_ref"},
            }
            for s in data["STATION"]
        ]
    return data, receipt
