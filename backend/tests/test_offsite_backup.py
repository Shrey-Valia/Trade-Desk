"""services/offsite_backup — SigV4 signing, the S3 wire, and retention safety.

Nothing here touches the network: every request goes to a fake S3 running on
localhost. That fake VERIFIES THE SIGNATURE of what it receives (recomputing
it from the bytes that actually arrived) and 403s on a mismatch, which is what
catches the whole class of bugs where the signed canonical request and the
request on the wire drift apart — query encoding, an unsigned header, a
payload hash that doesn't match the body.

Signing correctness itself is pinned by the fixed vectors in
TestSigV4Vectors. Those were produced two independent ways: two are the
published AWS documentation examples, and all five were confirmed byte-for-byte
against botocore's own SigV4Auth (differential run at authoring time; botocore
is deliberately NOT a dependency of this repo). The same authoring run also
replayed every request this store puts on the wire through botocore, and drove
the whole module end to end against moto's S3 server (real ListObjectsV2 XML,
real continuation tokens, real error codes) — see the PR for that transcript.
"""

from __future__ import annotations

import hashlib
import http.server
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qsl, unquote

import pytest

from services.offsite_backup import (
    _EMPTY_SHA256,
    OffsiteBackupError,
    OffsiteConfigError,
    RemoteObject,
    S3OffsiteStore,
    get_offsite_store,
    prune_remote,
    sign_request,
)

AK = "AKIAIOSFODNN7EXAMPLE"
SK = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"


# ---------------------------------------------------------------------------
# 1. Signing


class TestSigV4Vectors:
    """Fixed vectors. A change to the signer that breaks any of these breaks
    every real request; do not "fix" a vector to match new code."""

    def _sig(self, **kw) -> str:
        auth = sign_request(access_key_id=AK, secret_access_key=SK, **kw)["Authorization"]
        return auth.split("Signature=")[1]

    def test_aws_docs_get_object_example(self):
        """AWS "Signature Calculations: GET Object" worked example."""
        assert (
            self._sig(
                method="GET",
                host="examplebucket.s3.amazonaws.com",
                path="/test.txt",
                params={},
                headers={"range": "bytes=0-9"},
                payload_sha256=_EMPTY_SHA256,
                region="us-east-1",
                now=datetime(2013, 5, 24, tzinfo=timezone.utc),
            )
            == "f0e8bdb87c964420e857bd35b5d6ed310bd44f0170aba48dd91039c6036bdb41"
        )

    def test_put_object_with_encoded_key_and_extra_signed_header(self):
        """'$' in the key must be percent-encoded in the canonical URI, and a
        caller-supplied x-amz-* header must be signed."""
        assert (
            self._sig(
                method="PUT",
                host="examplebucket.s3.amazonaws.com",
                path="/test$file.text",
                params={},
                headers={"x-amz-storage-class": "REDUCED_REDUNDANCY"},
                payload_sha256=(
                    "44ce7dd67c959e0d3524ffac1771dfbba87d2b6b4b4e99e42034a8b803f8b072"
                ),
                region="us-east-1",
                now=datetime(2013, 5, 24, tzinfo=timezone.utc),
            )
            == "1ee3a9a719bf9cd67d34043a52b3d1f8b674e378dc99c0748019b43f49b5b9bb"
        )

    def test_list_objects_v2_path_style_r2(self):
        """Query parameters are sorted and percent-encoded ('/' → %2F)."""
        assert (
            self._sig(
                method="GET",
                host="acct.r2.cloudflarestorage.com",
                path="/mybucket/",
                params={"list-type": "2", "max-keys": "1000", "prefix": "backups/"},
                headers={},
                payload_sha256=_EMPTY_SHA256,
                region="auto",
                now=datetime(2026, 8, 26, 7, 30, 15, tzinfo=timezone.utc),
            )
            == "041f90894b71d90d5172ec6f5a209aff88c62a50afb0b16623724ad69720e5af"
        )

    def test_put_snapshot_with_content_length(self):
        assert (
            self._sig(
                method="PUT",
                host="acct.r2.cloudflarestorage.com",
                path="/mybucket/backups/dashboard-20260826-023000.db",
                params={},
                headers={"Content-Length": "4096"},
                payload_sha256="0" * 63 + "a",
                region="auto",
                now=datetime(2026, 8, 26, 2, 30, tzinfo=timezone.utc),
            )
            == "52c6329c0365c74b56f2ca8049ef9be8001b1b7af16782324de946287d48af15"
        )

    def test_delete_key_with_space_and_tilde(self):
        """'~' must NOT be encoded; a space must be."""
        assert (
            self._sig(
                method="DELETE",
                host="s3.example.net",
                path="/b/backups/odd ~name/dashboard-20260101-000000.db",
                params={},
                headers={},
                payload_sha256=_EMPTY_SHA256,
                region="us-west-004",
                now=datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc),
            )
            == "675feb1ca4fcb66d5b344a48c370a8060d2030956893a514368112de2fbea617"
        )

    def test_credential_scope_and_signed_headers(self):
        out = sign_request(
            method="GET",
            host="h",
            path="/b/",
            params={},
            headers={},
            payload_sha256=_EMPTY_SHA256,
            access_key_id=AK,
            secret_access_key=SK,
            region="auto",
            now=datetime(2026, 8, 26, 1, 2, 3, tzinfo=timezone.utc),
        )
        assert out["x-amz-date"] == "20260826T010203Z"
        assert f"Credential={AK}/20260826/auto/s3/aws4_request" in out["Authorization"]
        assert "SignedHeaders=host;x-amz-content-sha256;x-amz-date" in out["Authorization"]
        assert out["Host"] == "h"


# ---------------------------------------------------------------------------
# 2. Configuration


class TestConfiguration:
    def test_provider_none_returns_no_store(self, monkeypatch):
        monkeypatch.setattr("config.settings.backup_offsite_provider", "none")
        assert get_offsite_store() is None

    def test_unknown_provider_raises_rather_than_silently_skipping(self, monkeypatch):
        monkeypatch.setattr("config.settings.backup_offsite_provider", "gcs")
        with pytest.raises(OffsiteConfigError, match="not recognised"):
            get_offsite_store()

    def test_s3_provider_with_blank_settings_names_what_is_missing(self, monkeypatch):
        monkeypatch.setattr("config.settings.backup_offsite_provider", "s3")
        monkeypatch.setattr("config.settings.backup_s3_bucket", "")
        monkeypatch.setattr("config.settings.backup_s3_access_key_id", "")
        monkeypatch.setattr("config.settings.backup_s3_secret_access_key", "")
        with pytest.raises(OffsiteConfigError) as exc:
            get_offsite_store()
        for name in (
            "BACKUP_S3_BUCKET",
            "BACKUP_S3_ACCESS_KEY_ID",
            "BACKUP_S3_SECRET_ACCESS_KEY",
        ):
            assert name in str(exc.value)

    def test_settings_are_wired_through(self, monkeypatch):
        monkeypatch.setattr("config.settings.backup_offsite_provider", "s3")
        monkeypatch.setattr("config.settings.backup_s3_bucket", "bkt")
        monkeypatch.setattr("config.settings.backup_s3_region", "auto")
        monkeypatch.setattr("config.settings.backup_s3_access_key_id", AK)
        monkeypatch.setattr("config.settings.backup_s3_secret_access_key", SK)
        monkeypatch.setattr(
            "config.settings.backup_s3_endpoint_url", "https://acct.r2.cloudflarestorage.com"
        )
        monkeypatch.setattr("config.settings.backup_s3_prefix", "td/backups/")
        store = get_offsite_store()
        assert store is not None
        assert store.full_key("dashboard-1.db") == "td/backups/dashboard-1.db"

    def test_bucket_containing_a_path_is_rejected(self):
        with pytest.raises(OffsiteConfigError, match="not a path"):
            S3OffsiteStore(
                bucket="bkt/sub", region="auto", access_key_id=AK, secret_access_key=SK
            )

    def test_aws_uses_virtual_hosted_addressing(self):
        store = S3OffsiteStore(
            bucket="bkt", region="eu-west-1", access_key_id=AK, secret_access_key=SK
        )
        assert store._url("k.db") == "https://bkt.s3.eu-west-1.amazonaws.com/k.db"

    def test_custom_endpoint_uses_path_style_and_defaults_to_https(self):
        store = S3OffsiteStore(
            bucket="bkt",
            region="auto",
            access_key_id=AK,
            secret_access_key=SK,
            endpoint_url="acct.r2.cloudflarestorage.com/",
        )
        assert store._url("k.db") == "https://acct.r2.cloudflarestorage.com/bkt/k.db"

    @pytest.mark.parametrize("raw", ["", "backups", "/backups/", "backups///"])
    def test_prefix_is_normalised_to_one_trailing_slash(self, raw):
        store = S3OffsiteStore(
            bucket="b", region="auto", access_key_id=AK, secret_access_key=SK, prefix=raw
        )
        assert store.prefix in ("", "backups/")
        assert store.full_key("x.db").endswith("x.db")
        assert "//" not in store.full_key("x.db")


# ---------------------------------------------------------------------------
# 3. A fake S3 that checks our signatures


class _FakeS3(http.server.BaseHTTPRequestHandler):
    """Verifies the arriving request's signature against the bytes received,
    then serves whatever the test queued. `server.state` carries everything."""

    protocol_version = "HTTP/1.1"

    def log_message(self, *args):  # keep pytest output clean
        pass

    # -- signature check ---------------------------------------------------

    def _verify_signature(self, body: bytes | None) -> bool:
        auth = self.headers.get("Authorization", "")
        if "SignedHeaders=" not in auth:
            return False
        signed_names = auth.split("SignedHeaders=")[1].split(",")[0].split(";")
        path, _, raw_query = self.path.partition("?")
        params = dict(parse_qsl(raw_query, keep_blank_values=True))
        headers = {
            name: self.headers.get(name, "")
            for name in signed_names
            if name not in ("host", "x-amz-date", "x-amz-content-sha256")
        }
        stamp = self.headers["x-amz-date"]
        expected = sign_request(
            method=self.command,
            host=self.headers["Host"],
            path=unquote(path),
            params=params,
            headers=headers,
            payload_sha256=self.headers["x-amz-content-sha256"],
            access_key_id=AK,
            secret_access_key=SK,
            region=self.server.state["region"],
            now=datetime.strptime(stamp, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc),
        )["Authorization"]
        if expected != auth:
            self.server.state["signature_mismatch"] = {"got": auth, "expected": expected}
            return False
        # The payload hash must describe the body that actually arrived.
        if body is not None:
            if hashlib.sha256(body).hexdigest() != self.headers["x-amz-content-sha256"]:
                self.server.state["payload_mismatch"] = True
                return False
        return True

    # -- plumbing ----------------------------------------------------------

    def _read_body(self) -> bytes:
        length = self.headers.get("Content-Length")
        if length is None:
            return b""
        return self.rfile.read(int(length))

    def _send(self, status: int, body: bytes = b"", ctype: str = "application/xml"):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)

    def _deny(self):
        self._send(
            403,
            b"<?xml version='1.0'?><Error><Code>SignatureDoesNotMatch</Code>"
            b"<Message>fake s3 recomputed a different signature</Message></Error>",
        )

    def _key(self) -> str:
        """The object key from the request path, with the path-style bucket
        segment stripped (`/bkt/backups/x.db` → `backups/x.db`)."""
        path = unquote(self.path.split("?")[0]).lstrip("/")
        return path.split("/", 1)[1] if "/" in path else path

    def _record(self):
        self.server.state["requests"].append(
            {
                "method": self.command,
                "path": self.path,
                "headers": dict(self.headers),
            }
        )

    def do_PUT(self):
        body = self._read_body()
        self._record()
        self.server.state["requests"][-1]["body_len"] = len(body)
        self.server.state["requests"][-1]["transfer_encoding"] = self.headers.get(
            "Transfer-Encoding"
        )
        if not self._verify_signature(body):
            return self._deny()
        forced = self.server.state.get("force_put_status")
        if forced:
            return self._send(forced, self.server.state.get("force_put_body", b""))
        self.server.state["objects"][self._key()] = body
        self._send(200)

    def do_DELETE(self):
        self._record()
        if not self._verify_signature(None):
            return self._deny()
        self.server.state["deleted"].append(self._key())
        self._send(204)

    def do_GET(self):
        self._record()
        if not self._verify_signature(None):
            return self._deny()
        path, _, query = self.path.partition("?")
        if "list-type=2" in query:
            pages = self.server.state["list_pages"]
            idx = self.server.state["list_calls"]
            self.server.state["list_calls"] += 1
            body = pages[min(idx, len(pages) - 1)]
            return self._send(200, body.encode("utf-8"))
        data = self.server.state["objects"].get(self._key())
        if data is not None and self.server.state.get("truncate_get"):
            # Promise more bytes than we deliver, then hang up: what a
            # connection dropped mid-download looks like to the client.
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(len(data) + 500))
            self.end_headers()
            self.wfile.write(data[: len(data) // 2])
            self.close_connection = True
            return
        if data is None:
            return self._send(
                404,
                b"<?xml version='1.0'?><Error><Code>NoSuchKey</Code>"
                b"<Message>not here</Message></Error>",
            )
        self._send(200, data, ctype="application/octet-stream")


@pytest.fixture
def fake_s3():
    """A running fake S3. Yields (store, state)."""
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _FakeS3)
    server.state = {
        "region": "auto",
        "requests": [],
        "objects": {},
        "deleted": [],
        "list_pages": ["<ListBucketResult></ListBucketResult>"],
        "list_calls": 0,
    }
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    store = S3OffsiteStore(
        bucket="bkt",
        region="auto",
        access_key_id=AK,
        secret_access_key=SK,
        endpoint_url=f"http://127.0.0.1:{port}",
        prefix="backups/",
        timeout_s=10.0,
    )
    try:
        yield store, server.state
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _list_xml(keys_sizes_dates, *, truncated_token: str | None = None) -> str:
    contents = "".join(
        f"<Contents><Key>{k}</Key><Size>{s}</Size>"
        f"<LastModified>{d}</LastModified></Contents>"
        for k, s, d in keys_sizes_dates
    )
    trunc = (
        f"<IsTruncated>true</IsTruncated>"
        f"<NextContinuationToken>{truncated_token}</NextContinuationToken>"
        if truncated_token
        else "<IsTruncated>false</IsTruncated>"
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">'
        f"<Name>bkt</Name>{trunc}{contents}</ListBucketResult>"
    )


class TestWireProtocol:
    def test_put_file_uploads_body_under_prefix(self, fake_s3, tmp_path):
        store, state = fake_s3
        src = tmp_path / "dashboard-20260826-023000.db"
        src.write_bytes(b"SQLite format 3\x00" + b"payload" * 100)

        out = store.put_file(src, src.name)

        assert out["key"] == "backups/dashboard-20260826-023000.db"
        assert out["bytes"] == src.stat().st_size
        assert out["sha256"] == hashlib.sha256(src.read_bytes()).hexdigest()
        assert state["objects"]["backups/dashboard-20260826-023000.db"] == src.read_bytes()
        req = state["requests"][-1]
        assert req["method"] == "PUT"
        assert req["path"] == "/bkt/backups/dashboard-20260826-023000.db"
        assert "signature_mismatch" not in state

    def test_upload_sends_content_length_not_chunked(self, fake_s3, tmp_path):
        """S3 rejects chunked transfer-encoding for a signed single-part
        payload, and httpx switches to it for any file-like body that has no
        explicit Content-Length. This is the regression guard."""
        store, state = fake_s3
        src = tmp_path / "dashboard-20260826-030000.db"
        src.write_bytes(b"z" * 3000)
        store.put_file(src, src.name)
        req = state["requests"][-1]
        assert req["transfer_encoding"] is None
        assert req["headers"]["Content-Length"] == "3000"
        assert req["body_len"] == 3000

    def test_upload_streams_a_file_larger_than_one_chunk(self, fake_s3, tmp_path):
        """Peak memory is one chunk, so a multi-chunk file must still arrive
        whole and hash correctly (the hash pass and the send pass are two
        separate reads of the file)."""
        store, state = fake_s3
        src = tmp_path / "dashboard-20260826-040000.db"
        src.write_bytes(b"ab" * (1024 * 1024 + 7))  # > _CHUNK
        out = store.put_file(src, src.name)
        stored = state["objects"]["backups/dashboard-20260826-040000.db"]
        assert len(stored) == src.stat().st_size
        assert hashlib.sha256(stored).hexdigest() == out["sha256"]

    def test_list_objects_follows_continuation_tokens(self, fake_s3):
        store, state = fake_s3
        # A token with characters whose encoding differs between percent- and
        # plus-encoding: if the signed query and the sent query diverge, the
        # fake's signature check fails and this raises.
        token = "a+b/c=d e"
        state["list_pages"] = [
            _list_xml(
                [("backups/dashboard-20260101-000000.db", 10, "2026-01-01T00:00:00.000Z")],
                truncated_token=token,
            ),
            _list_xml(
                [("backups/dashboard-20260102-000000.db", 20, "2026-01-02T00:00:00.000Z")]
            ),
        ]
        objs = store.list_objects()
        assert [o.key for o in objs] == [
            "backups/dashboard-20260101-000000.db",
            "backups/dashboard-20260102-000000.db",
        ]
        assert objs[0].size == 10
        assert objs[1].last_modified == datetime(2026, 1, 2, tzinfo=timezone.utc)
        assert state["list_calls"] == 2
        assert "signature_mismatch" not in state

    def test_list_objects_tolerates_a_namespace_free_response(self, fake_s3):
        """Not every S3-compatible store emits the AWS namespace."""
        store, state = fake_s3
        state["list_pages"] = [
            "<ListBucketResult><IsTruncated>false</IsTruncated>"
            "<Contents><Key>backups/dashboard-20260103-000000.db</Key>"
            "<Size>7</Size><LastModified>2026-01-03T00:00:00Z</LastModified>"
            "</Contents></ListBucketResult>"
        ]
        objs = store.list_objects()
        assert [(o.key, o.size) for o in objs] == [
            ("backups/dashboard-20260103-000000.db", 7)
        ]

    def test_list_objects_skips_directory_placeholders(self, fake_s3):
        store, state = fake_s3
        state["list_pages"] = [
            _list_xml(
                [
                    ("backups/", 0, "2026-01-01T00:00:00Z"),
                    ("backups/dashboard-20260104-000000.db", 5, "2026-01-04T00:00:00Z"),
                ]
            )
        ]
        assert [o.key for o in store.list_objects()] == [
            "backups/dashboard-20260104-000000.db"
        ]

    def test_get_to_file_round_trips_the_object(self, fake_s3, tmp_path):
        store, _ = fake_s3
        src = tmp_path / "dashboard-20260826-050000.db"
        src.write_bytes(b"q" * 5000)
        store.put_file(src, src.name)

        dest = tmp_path / "restored" / "out.db"
        written = store.get_to_file("backups/dashboard-20260826-050000.db", dest)
        assert written == 5000
        assert dest.read_bytes() == src.read_bytes()

    def test_interrupted_download_leaves_no_file_at_the_destination(self, fake_s3, tmp_path):
        """A half-downloaded snapshot must not be left sitting at the path an
        operator is about to restore from — it would open as a corrupt
        SQLite file, or worse, open fine and be missing rows."""
        store, state = fake_s3
        src = tmp_path / "dashboard-20260826-090000.db"
        src.write_bytes(b"w" * 4000)
        store.put_file(src, src.name)
        state["truncate_get"] = True

        dest = tmp_path / "restored.db"
        with pytest.raises(OffsiteBackupError, match="GET bkt/backups/.*failed"):
            store.get_to_file("backups/dashboard-20260826-090000.db", dest)
        assert not dest.exists()
        assert not list(tmp_path.glob("*.part"))

    def test_get_missing_key_raises_with_the_store_error_code(self, fake_s3, tmp_path):
        store, _ = fake_s3
        with pytest.raises(OffsiteBackupError, match="NoSuchKey"):
            store.get_to_file("backups/nope.db", tmp_path / "x.db")

    def test_delete_hits_the_full_key(self, fake_s3):
        store, state = fake_s3
        store.delete("backups/dashboard-20260101-000000.db")
        assert state["deleted"] == ["backups/dashboard-20260101-000000.db"]

    def test_error_response_surfaces_code_and_message(self, fake_s3, tmp_path):
        store, state = fake_s3
        state["force_put_status"] = 403
        state["force_put_body"] = (
            b"<Error><Code>AccessDenied</Code><Message>no write permission</Message></Error>"
        )
        src = tmp_path / "dashboard-20260826-060000.db"
        src.write_bytes(b"x")
        with pytest.raises(OffsiteBackupError) as exc:
            store.put_file(src, src.name)
        assert "AccessDenied" in str(exc.value)
        assert "no write permission" in str(exc.value)
        assert "HTTP 403" in str(exc.value)

    def test_wrong_credentials_are_rejected_by_the_fake(self, fake_s3, tmp_path):
        """Sanity check on the harness itself: the fake really does validate
        signatures, so the passing tests above mean something."""
        store, _ = fake_s3
        store._secret = "not-the-secret"
        src = tmp_path / "dashboard-20260826-070000.db"
        src.write_bytes(b"x")
        with pytest.raises(OffsiteBackupError, match="SignatureDoesNotMatch"):
            store.put_file(src, src.name)

    def test_oversize_file_is_refused_before_any_request(self, fake_s3, tmp_path, monkeypatch):
        """Multipart upload isn't implemented, so name the reason instead of
        letting S3 reject a 5GiB PUT after uploading it."""
        store, state = fake_s3
        monkeypatch.setattr("services.offsite_backup._MAX_SINGLE_PUT_BYTES", 10)
        src = tmp_path / "dashboard-20260826-100000.db"
        src.write_bytes(b"x" * 11)
        with pytest.raises(OffsiteBackupError, match="single-part PUT limit"):
            store.put_file(src, src.name)
        assert state["requests"] == []

    def test_unreachable_endpoint_raises_offsite_error(self, tmp_path):
        store = S3OffsiteStore(
            bucket="bkt",
            region="auto",
            access_key_id=AK,
            secret_access_key=SK,
            # Port 1 is reserved and nothing listens on it.
            endpoint_url="http://127.0.0.1:1",
            timeout_s=2.0,
        )
        src = tmp_path / "dashboard-20260826-080000.db"
        src.write_bytes(b"x")
        with pytest.raises(OffsiteBackupError, match="failed"):
            store.put_file(src, src.name)


# ---------------------------------------------------------------------------
# 4. Retention safety


class _FakeStore:
    """Just enough store for prune_remote."""

    def __init__(self, objects: list[RemoteObject]):
        self.objects = objects
        self.deleted: list[str] = []

    def list_objects(self):
        return list(self.objects)

    def delete(self, key):
        self.deleted.append(key)


NOW = datetime(2026, 8, 26, 12, 0, tzinfo=timezone.utc)


def _obj(days_ago: float, *, name: str | None = None, lm_days_ago: float | None = None):
    stamp = NOW - timedelta(days=days_ago)
    key = f"backups/{name or 'dashboard-' + stamp.strftime('%Y%m%d-%H%M%S') + '.db'}"
    lm = NOW - timedelta(days=days_ago if lm_days_ago is None else lm_days_ago)
    return RemoteObject(key=key, size=1024, last_modified=lm)


class TestRetention:
    def test_zero_retention_deletes_nothing(self):
        store = _FakeStore([_obj(d) for d in (400, 300, 200, 100, 50, 1)])
        assert prune_remote(store, retention_days=0, now=NOW) == 0
        assert store.deleted == []

    def test_deletes_only_snapshots_past_the_window(self):
        keep = [_obj(1), _obj(2), _obj(3)]
        drop = [_obj(40), _obj(90)]
        store = _FakeStore(keep + drop)
        assert prune_remote(store, retention_days=30, keep_min=3, now=NOW) == 2
        assert sorted(store.deleted) == sorted(o.key for o in drop)

    def test_newest_keep_min_survive_however_old_they_are(self):
        """The clock-bug guard: every object is ancient, yet the newest few
        must never be deleted — otherwise a timezone or retention mistake
        empties the bucket."""
        store = _FakeStore([_obj(d) for d in (500, 600, 700)])
        assert prune_remote(store, retention_days=1, keep_min=3, now=NOW) == 0
        assert store.deleted == []

    def test_keep_min_applies_before_the_age_test(self):
        store = _FakeStore([_obj(d) for d in (500, 600, 700, 800, 900)])
        assert prune_remote(store, retention_days=1, keep_min=3, now=NOW) == 2

    def test_foreign_keys_are_never_candidates(self):
        """Anything the backup job did not write — a hand-uploaded rescue
        copy, another app's data — must be untouchable."""
        store = _FakeStore(
            [
                _obj(400, name="important-manual-copy.db"),
                _obj(400, name="dashboard-backup.db"),
                _obj(400, name="notes.txt"),
                _obj(1),
                _obj(2),
                _obj(3),
                _obj(400),
            ]
        )
        prune_remote(store, retention_days=30, keep_min=3, now=NOW)
        assert store.deleted == [_obj(400).key]

    def test_recent_last_modified_vetoes_an_old_looking_key(self):
        """Two signals must agree. A key stamped last year whose object was
        written yesterday is a re-upload, not garbage."""
        store = _FakeStore(
            [_obj(1), _obj(2), _obj(3), _obj(400, lm_days_ago=0.5)]
        )
        assert prune_remote(store, retention_days=30, keep_min=3, now=NOW) == 0

    def test_missing_last_modified_vetoes_deletion(self):
        old = _obj(400)
        store = _FakeStore(
            [_obj(1), _obj(2), _obj(3), old._replace(last_modified=None)]
        )
        assert prune_remote(store, retention_days=30, keep_min=3, now=NOW) == 0

    def test_unparseable_stamp_is_ignored(self):
        store = _FakeStore(
            [_obj(1), _obj(2), _obj(3), _obj(400, name="dashboard-20261345-999999.db")]
        )
        assert prune_remote(store, retention_days=30, keep_min=3, now=NOW) == 0


# ---------------------------------------------------------------------------
# 5. backup_db integration


@pytest.fixture(autouse=True)
def _stub_prune_job_runs(monkeypatch):
    calls: list[int] = []

    def fake_prune(days: int = 14) -> int:
        calls.append(days)
        return 0

    monkeypatch.setattr("services.job_runs.prune_job_runs", fake_prune)
    return calls


@pytest.fixture
def sqlite_engine(tmp_path):
    from sqlalchemy import create_engine, text

    engine = create_engine(f"sqlite:///{tmp_path / 'live.db'}", future=True)
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE trades (id INTEGER PRIMARY KEY)"))
        conn.execute(text("INSERT INTO trades (id) VALUES (1), (2)"))
    yield engine
    engine.dispose()


class TestBackupJobIntegration:
    def test_disabled_by_default(self, sqlite_engine, tmp_path, monkeypatch):
        from jobs.backup_db import backup_db

        monkeypatch.setattr("config.settings.backup_offsite_provider", "none")
        out = backup_db(
            engine=sqlite_engine, backup_dir=str(tmp_path / "b"), retention_days=14
        )
        assert out["status"] == "ok"
        assert out["offsite"] == "disabled"

    def test_snapshot_is_uploaded_and_is_a_valid_database(
        self, sqlite_engine, tmp_path, fake_s3, monkeypatch
    ):
        import services.offsite_backup as offsite
        from jobs.backup_db import backup_db

        store, state = fake_s3
        monkeypatch.setattr(offsite, "get_offsite_store", lambda: store)
        monkeypatch.setattr("config.settings.backup_offsite_retention_days", 0)

        out = backup_db(
            engine=sqlite_engine, backup_dir=str(tmp_path / "b"), retention_days=14
        )

        assert out["offsite"] == "ok"
        assert out["offsite_key"].startswith("backups/dashboard-")
        assert out["pruned_offsite"] == 0
        uploaded = state["objects"][out["offsite_key"]]
        # What landed offsite must be a restorable database, not just bytes.
        restored = tmp_path / "restored.db"
        restored.write_bytes(uploaded)
        with sqlite3.connect(restored) as conn:
            assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            assert conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0] == 2

    def test_upload_failure_fails_the_job_but_keeps_the_local_snapshot(
        self, sqlite_engine, tmp_path, monkeypatch, _stub_prune_job_runs
    ):
        """The local backup and both prunes happen first, so a dead object
        store cannot cost us the local snapshot — but the job still goes red,
        because an offsite copy that silently stopped is the failure this
        whole feature exists to surface."""
        import services.offsite_backup as offsite
        from jobs.backup_db import backup_db

        class Boom:
            def put_file(self, *a, **k):
                raise OffsiteBackupError("PUT bkt/x → HTTP 403 — AccessDenied: nope")

        monkeypatch.setattr(offsite, "get_offsite_store", lambda: Boom())
        backup_dir = tmp_path / "b"

        with pytest.raises(OffsiteBackupError) as exc:
            backup_db(engine=sqlite_engine, backup_dir=str(backup_dir), retention_days=14)

        message = str(exc.value)
        assert "LOCAL snapshot" in message and "OK" in message
        assert "AccessDenied" in message
        assert len(list(backup_dir.glob("dashboard-*.db"))) == 1
        assert _stub_prune_job_runs == [14]  # the JobRun prune still ran

    def test_misconfiguration_also_fails_the_job(self, sqlite_engine, tmp_path, monkeypatch):
        from jobs.backup_db import backup_db

        monkeypatch.setattr("config.settings.backup_offsite_provider", "s3")
        monkeypatch.setattr("config.settings.backup_s3_bucket", "")
        with pytest.raises(OffsiteBackupError, match="OFFSITE copy FAILED"):
            backup_db(engine=sqlite_engine, backup_dir=str(tmp_path / "b"), retention_days=14)

    def test_offsite_prune_runs_after_a_successful_upload(
        self, sqlite_engine, tmp_path, fake_s3, monkeypatch
    ):
        import services.offsite_backup as offsite
        from jobs.backup_db import backup_db

        store, state = fake_s3
        old = (NOW - timedelta(days=400)).strftime("%Y%m%d-%H%M%S")
        state["list_pages"] = [
            _list_xml(
                [
                    (f"backups/dashboard-{old}.db", 1, "2025-07-22T00:00:00Z"),
                    ("backups/dashboard-20260825-000000.db", 1, "2026-08-25T00:00:00Z"),
                    ("backups/dashboard-20260824-000000.db", 1, "2026-08-24T00:00:00Z"),
                    ("backups/dashboard-20260823-000000.db", 1, "2026-08-23T00:00:00Z"),
                ]
            )
        ]
        monkeypatch.setattr(offsite, "get_offsite_store", lambda: store)
        monkeypatch.setattr("config.settings.backup_offsite_retention_days", 30)

        out = backup_db(
            engine=sqlite_engine, backup_dir=str(tmp_path / "b"), retention_days=14
        )
        assert out["pruned_offsite"] == 1
        assert state["deleted"] == [f"backups/dashboard-{old}.db"]
