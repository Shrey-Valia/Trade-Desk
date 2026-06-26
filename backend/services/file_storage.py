"""Local-filesystem storage for journal trade screenshots.

A deliberately tiny abstraction: save an uploaded image under
`backend/data/uploads/`, validate it (size ≤ 5MB, PNG/JPEG only), and
hand back a served path the API exposes via GET. No S3, no DB blob —
the journal only needs one screenshot per trade and the demo runs on a
single box, so a flat directory keyed by trade id is the right size.

Validation is defense-in-depth: we check BOTH the declared content-type
and the file's magic-number signature, and we cap the size while
streaming so an oversize upload can't exhaust memory. The stored filename
is derived solely from the trade id (never the client filename), so the
upload path can't be used to traverse out of the uploads dir.
"""

from __future__ import annotations

import logging
from pathlib import Path

from config import PROJECT_ROOT

log = logging.getLogger(__name__)

# Where uploads live. Co-located with the SQLite db under backend/data so
# a single .gitignore'd data dir holds all runtime artifacts.
UPLOAD_DIR = PROJECT_ROOT / "data" / "uploads"

# 5 MB ceiling — a chart screenshot is well under this; anything larger is
# almost certainly a mistake (or abuse).
MAX_BYTES = 5 * 1024 * 1024

# Allowed image types → canonical file extension. The declared content-type
# must be in this map AND the bytes must start with the matching signature.
_ALLOWED: dict[str, str] = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",  # some clients send the non-canonical form
}

# Magic-number signatures, keyed by the canonical extension we resolve to.
_SIGNATURES: dict[str, tuple[bytes, ...]] = {
    ".png": (b"\x89PNG\r\n\x1a\n",),
    ".jpg": (b"\xff\xd8\xff",),
}


class FileStorageError(ValueError):
    """Validation failure (bad type, oversize, corrupt). Carries a
    user-safe message the router maps to a 4xx."""


def _ext_for(content_type: str | None) -> str:
    ct = (content_type or "").split(";")[0].strip().lower()
    ext = _ALLOWED.get(ct)
    if ext is None:
        raise FileStorageError(
            f"unsupported image type {ct or '(none)'}; allowed: PNG, JPEG"
        )
    return ext


def _sniff(data: bytes, ext: str) -> None:
    """Confirm the bytes actually look like the claimed format."""
    sigs = _SIGNATURES.get(ext, ())
    if not any(data.startswith(sig) for sig in sigs):
        raise FileStorageError(
            "file contents do not match a PNG or JPEG image"
        )


def save_screenshot(trade_id: int, content_type: str | None, data: bytes) -> str:
    """Validate + persist a screenshot for `trade_id`.

    Returns the served URL path (`/api/journal/trades/{id}/screenshot`) the
    caller stores on the trade row. Raises FileStorageError on a bad type,
    an oversize payload, or contents that don't match the declared format.

    A trade has at most ONE screenshot: re-uploading replaces the prior
    file (and removes a stale sibling with a different extension so we never
    leave two images for one trade).
    """
    ext = _ext_for(content_type)
    if len(data) == 0:
        raise FileStorageError("empty file")
    if len(data) > MAX_BYTES:
        raise FileStorageError(
            f"file too large ({len(data)} bytes); max {MAX_BYTES} bytes (5 MB)"
        )
    _sniff(data, ext)

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    # Clear any prior screenshot for this trade (possibly a different ext).
    _remove_existing(trade_id)

    dest = UPLOAD_DIR / f"trade_{trade_id}{ext}"
    dest.write_bytes(data)
    log.info("saved screenshot for trade %s (%d bytes) → %s", trade_id, len(data), dest.name)
    return served_url(trade_id)


def find_screenshot(trade_id: int) -> Path | None:
    """Resolved on-disk path of a trade's screenshot, or None if absent."""
    for ext in (".png", ".jpg"):
        p = UPLOAD_DIR / f"trade_{trade_id}{ext}"
        if p.is_file():
            return p
    return None


def served_url(trade_id: int) -> str:
    """The GET path the frontend renders a thumbnail from."""
    return f"/api/journal/trades/{trade_id}/screenshot"


def media_type_for(path: Path) -> str:
    return "image/png" if path.suffix == ".png" else "image/jpeg"


def _remove_existing(trade_id: int) -> None:
    for ext in (".png", ".jpg"):
        p = UPLOAD_DIR / f"trade_{trade_id}{ext}"
        if p.is_file():
            try:
                p.unlink()
            except OSError:  # pragma: no cover — best-effort cleanup
                log.debug("could not unlink stale screenshot %s", p.name)
