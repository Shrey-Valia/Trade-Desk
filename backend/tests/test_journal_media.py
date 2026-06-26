"""Journal screenshot upload/serve — WS4 (#13).

Covers the happy path (multipart upload sets `screenshot_url` and the
bytes serve back), the validation guards (oversize, wrong format, contents
that don't match the declared type), and the auth/ownership boundary
(another user can't upload to or read a foreign trade's screenshot).

A trade must exist first — the upload sets the screenshot on an existing
row — so each test creates a trade through the real journal endpoint on a
purchased combine, exactly like test_journal.py.
"""

from __future__ import annotations

import struct
import zlib
from datetime import date, datetime, timedelta, timezone

import pytest

from services import file_storage
from tests.conftest import make_combine


@pytest.fixture
def client(auth_client):
    """Authed client owning one active 50K combine."""
    make_combine(auth_client, "50K")
    return auth_client


@pytest.fixture(autouse=True)
def _isolate_uploads(tmp_path, monkeypatch):
    """Redirect the uploads dir into a per-test tmp path so the suite never
    writes into the real backend/data/uploads/ and tests don't see each
    other's files."""
    monkeypatch.setattr(file_storage, "UPLOAD_DIR", tmp_path / "uploads")
    yield


# --- tiny valid image payloads ---------------------------------------------


def _png_bytes() -> bytes:
    """A minimal but structurally valid 1x1 PNG (real signature + IHDR)."""
    sig = b"\x89PNG\r\n\x1a\n"

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    idat = zlib.compress(b"\x00\x00\x00\x00")
    return sig + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")


def _jpeg_bytes() -> bytes:
    """Minimal JPEG — the SOI marker is enough for our signature sniff."""
    return b"\xff\xd8\xff\xe0" + b"\x00" * 64


def _future_expiry(days: int = 21) -> str:
    return (date.today() + timedelta(days=days)).isoformat()


def _trade_payload(**overrides):
    base = {
        "symbol": "AAPL",
        "strategy": "long_call",
        "entry_date": datetime.now(timezone.utc).isoformat(),
        "entry_underlying_price": 230.0,
        "is_paper": True,
        "legs": [
            {
                "side": "call", "action": "buy",
                "strike": 230, "expiry": _future_expiry(),
                "contracts": 1, "entry_price": 6.20,
            },
        ],
    }
    base.update(overrides)
    return base


def _create_trade(client) -> int:
    res = client.post("/api/journal/trades", json=_trade_payload())
    assert res.status_code == 201, res.text
    return res.json()["id"]


# --- happy path -------------------------------------------------------------


def test_upload_sets_screenshot_url_and_serves(client):
    tid = _create_trade(client)
    assert client.get(f"/api/journal/trades/{tid}").json()["screenshot_url"] is None

    png = _png_bytes()
    res = client.post(
        f"/api/journal/trades/{tid}/screenshot",
        files={"file": ("chart.png", png, "image/png")},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["screenshot_url"] == f"/api/journal/trades/{tid}/screenshot"

    # It persists on the trade row.
    assert (
        client.get(f"/api/journal/trades/{tid}").json()["screenshot_url"]
        == f"/api/journal/trades/{tid}/screenshot"
    )

    # And the bytes serve back unchanged with an image content-type.
    served = client.get(f"/api/journal/trades/{tid}/screenshot")
    assert served.status_code == 200
    assert served.headers["content-type"] == "image/png"
    assert served.content == png


def test_upload_jpeg_serves_as_jpeg(client):
    tid = _create_trade(client)
    res = client.post(
        f"/api/journal/trades/{tid}/screenshot",
        files={"file": ("chart.jpg", _jpeg_bytes(), "image/jpeg")},
    )
    assert res.status_code == 200, res.text
    served = client.get(f"/api/journal/trades/{tid}/screenshot")
    assert served.headers["content-type"] == "image/jpeg"


def test_reupload_replaces_prior_screenshot(client):
    tid = _create_trade(client)
    client.post(
        f"/api/journal/trades/{tid}/screenshot",
        files={"file": ("a.png", _png_bytes(), "image/png")},
    )
    # Replace with a JPEG — only one file should remain for the trade.
    res = client.post(
        f"/api/journal/trades/{tid}/screenshot",
        files={"file": ("b.jpg", _jpeg_bytes(), "image/jpeg")},
    )
    assert res.status_code == 200
    served = client.get(f"/api/journal/trades/{tid}/screenshot")
    assert served.headers["content-type"] == "image/jpeg"
    # The stale PNG sibling was removed.
    assert not (file_storage.UPLOAD_DIR / f"trade_{tid}.png").exists()
    assert (file_storage.UPLOAD_DIR / f"trade_{tid}.jpg").exists()


# --- validation -------------------------------------------------------------


def test_reject_unsupported_format(client):
    tid = _create_trade(client)
    res = client.post(
        f"/api/journal/trades/{tid}/screenshot",
        files={"file": ("notes.gif", b"GIF89a" + b"\x00" * 32, "image/gif")},
    )
    assert res.status_code == 422
    assert "unsupported image type" in res.json()["detail"]


def test_reject_content_type_signature_mismatch(client):
    """Declared PNG but the bytes aren't a PNG → rejected by the magic-number
    sniff (defense against a mislabeled / malicious payload)."""
    tid = _create_trade(client)
    res = client.post(
        f"/api/journal/trades/{tid}/screenshot",
        files={"file": ("fake.png", b"this is not a png", "image/png")},
    )
    assert res.status_code == 422
    assert "do not match" in res.json()["detail"]


def test_reject_oversize(client):
    tid = _create_trade(client)
    # 5MB + 1 byte of valid-PNG-prefixed data.
    big = _png_bytes() + b"\x00" * (file_storage.MAX_BYTES + 1)
    res = client.post(
        f"/api/journal/trades/{tid}/screenshot",
        files={"file": ("huge.png", big, "image/png")},
    )
    assert res.status_code in (413, 422)
    assert "too large" in res.json()["detail"]


def test_reject_empty_file(client):
    tid = _create_trade(client)
    res = client.post(
        f"/api/journal/trades/{tid}/screenshot",
        files={"file": ("empty.png", b"", "image/png")},
    )
    assert res.status_code == 422


# --- not-found / auth / ownership ------------------------------------------


def test_upload_to_missing_trade_404(client):
    res = client.post(
        "/api/journal/trades/999999/screenshot",
        files={"file": ("x.png", _png_bytes(), "image/png")},
    )
    assert res.status_code == 404


def test_get_screenshot_404_when_none_uploaded(client):
    tid = _create_trade(client)
    assert client.get(f"/api/journal/trades/{tid}/screenshot").status_code == 404


def test_requires_auth(client):
    tid = _create_trade(client)
    client.post("/api/auth/signout")
    res = client.post(
        f"/api/journal/trades/{tid}/screenshot",
        files={"file": ("x.png", _png_bytes(), "image/png")},
    )
    assert res.status_code == 401
    assert client.get(f"/api/journal/trades/{tid}/screenshot").status_code == 401


def test_cross_user_cannot_upload_or_read(client, second_user_client):
    tid = _create_trade(client)
    client.post(
        f"/api/journal/trades/{tid}/screenshot",
        files={"file": ("x.png", _png_bytes(), "image/png")},
    )
    # The rival sees the foreign trade as nonexistent for both verbs.
    assert (
        second_user_client.post(
            f"/api/journal/trades/{tid}/screenshot",
            files={"file": ("y.png", _png_bytes(), "image/png")},
        ).status_code
        == 404
    )
    assert (
        second_user_client.get(f"/api/journal/trades/{tid}/screenshot").status_code
        == 404
    )
