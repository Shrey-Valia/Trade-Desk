"""Offsite replication for the nightly database backup.

WHY THIS EXISTS: `jobs/backup_db.py` writes its snapshots into
`settings.backup_dir`, which on the Fly deploy is the SAME volume that
holds the live database (both default under /app/data). That volume is
one failure domain — losing it, or a mistaken `fly volumes destroy`,
takes the database AND every backup of it in one step. Fly volume
snapshots are not a substitute: 5-day retention, same provider, same
region, and nothing you have ever restored from. This module puts a copy
somewhere else.

Transport is plain S3 REST signed with SigV4, over httpx (already a
dependency) — no boto3. Two reasons: botocore's bundled service models
add ~90MB to an image that already carries pandas/numpy/scipy on a 1GB
machine, and a single-object PUT/GET/LIST/DELETE is a small enough
surface to sign correctly. The signer is pinned by the AWS documentation
test vectors AND by vectors differentially generated against botocore
(see tests/test_offsite_backup.py). A signing mistake fails LOUDLY with a
403 — it cannot produce a silently corrupt backup.

Works against anything S3-compatible: Cloudflare R2 (region "auto"),
Backblaze B2, MinIO, AWS S3. A custom `endpoint_url` selects path-style
addressing (`endpoint/bucket/key`); bare AWS uses virtual-hosted
(`bucket.s3.region.amazonaws.com`), which is the only style AWS promises
for new buckets.

DORMANT by default: `backup_offsite_provider` is "none", so a dev box and
CI never reach the network. Setting it to "s3" with an incomplete
configuration raises at construction (loud job failure) rather than
skipping — a backup that silently isn't happening is the whole thing this
module exists to prevent.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import IO, NamedTuple
from urllib.parse import quote

import httpx

from config import settings

log = logging.getLogger(__name__)

_ALGORITHM = "AWS4-HMAC-SHA256"
_SERVICE = "s3"
# SHA256 of b"" — the payload hash for every request without a body.
_EMPTY_SHA256 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
# Read the local snapshot in 1MB slices when hashing and when streaming it
# up, so a database far larger than the machine's RAM still uploads.
_CHUNK = 1024 * 1024
# Cap on a non-body response we buffer (ListObjectsV2 XML, error XML).
_MAX_RESPONSE_BYTES = 8 * 1024 * 1024
# S3 rejects a single-part PUT above 5GiB. We do not implement multipart;
# refusing at this line turns "the upload mysteriously fails" into a clear
# job error naming the reason.
_MAX_SINGLE_PUT_BYTES = 5 * 1024 * 1024 * 1024

# Backup object names this module owns. Mirrors _BACKUP_GLOB in
# jobs/backup_db.py: remote retention only ever considers keys the job
# itself wrote, so an unrelated object someone parks in the bucket (or a
# hand-uploaded rescue copy) is never a deletion candidate.
_KEY_STAMP_RE = re.compile(r"dashboard-(\d{8}-\d{6})\.db\Z")


class OffsiteConfigError(RuntimeError):
    """Offsite replication asked for, but the configuration cannot work."""


class OffsiteBackupError(RuntimeError):
    """A request to the object store failed."""


class RemoteObject(NamedTuple):
    key: str
    size: int
    last_modified: datetime | None


# ---------------------------------------------------------------------------
# SigV4


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _hmac(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def _signing_key(secret: str, datestamp: str, region: str) -> bytes:
    k_date = _hmac(f"AWS4{secret}".encode(), datestamp)
    k_region = _hmac(k_date, region)
    k_service = _hmac(k_region, _SERVICE)
    return _hmac(k_service, "aws4_request")


def _canonical_uri(path: str) -> str:
    """URI-encode an object path. Each segment is encoded, '/' preserved;
    S3 wants unreserved characters (including '~') left alone and must not
    see double-encoding."""
    return quote(path, safe="/~")


def _canonical_query(params: dict[str, str]) -> str:
    return "&".join(
        f"{quote(k, safe='-_.~')}={quote(v, safe='-_.~')}" for k, v in sorted(params.items())
    )


def sign_request(
    *,
    method: str,
    host: str,
    path: str,
    params: dict[str, str],
    headers: dict[str, str],
    payload_sha256: str,
    access_key_id: str,
    secret_access_key: str,
    region: str,
    now: datetime,
) -> dict[str, str]:
    """Return the headers to send: the caller's headers plus Host,
    x-amz-date, x-amz-content-sha256 and Authorization.

    Pure and deterministic given `now` — which is what makes it testable
    against fixed vectors. Header names are matched case-insensitively;
    every header passed in is signed (S3 requires host, x-amz-date and
    x-amz-content-sha256 to be among them).
    """
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    datestamp = now.strftime("%Y%m%d")

    signed = {k.lower(): v.strip() for k, v in headers.items()}
    signed["host"] = host
    signed["x-amz-date"] = amz_date
    signed["x-amz-content-sha256"] = payload_sha256

    names = sorted(signed)
    canonical_headers = "".join(f"{n}:{signed[n]}\n" for n in names)
    signed_headers = ";".join(names)

    canonical_request = "\n".join(
        (
            method,
            _canonical_uri(path),
            _canonical_query(params),
            canonical_headers,
            signed_headers,
            payload_sha256,
        )
    )
    scope = f"{datestamp}/{region}/{_SERVICE}/aws4_request"
    string_to_sign = "\n".join(
        (_ALGORITHM, amz_date, scope, _sha256_hex(canonical_request.encode("utf-8")))
    )
    signature = hmac.new(
        _signing_key(secret_access_key, datestamp, region),
        string_to_sign.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    out = dict(headers)
    out["Host"] = host
    out["x-amz-date"] = amz_date
    out["x-amz-content-sha256"] = payload_sha256
    out["Authorization"] = (
        f"{_ALGORITHM} Credential={access_key_id}/{scope}, "
        f"SignedHeaders={signed_headers}, Signature={signature}"
    )
    return out


# ---------------------------------------------------------------------------
# Store


class S3OffsiteStore:
    """Minimal S3 REST client: put / list / get / delete under one prefix.

    Construction validates the configuration and raises OffsiteConfigError
    if it cannot possibly work, so the failure surfaces at the top of the
    backup job instead of as a mystery 403 later.
    """

    def __init__(
        self,
        *,
        bucket: str,
        region: str,
        access_key_id: str,
        secret_access_key: str,
        endpoint_url: str = "",
        prefix: str = "",
        timeout_s: float = 60.0,
    ) -> None:
        missing = [
            name
            for name, value in (
                ("BACKUP_S3_BUCKET", bucket),
                ("BACKUP_S3_REGION", region),
                ("BACKUP_S3_ACCESS_KEY_ID", access_key_id),
                ("BACKUP_S3_SECRET_ACCESS_KEY", secret_access_key),
            )
            if not str(value).strip()
        ]
        if missing:
            raise OffsiteConfigError(
                "BACKUP_OFFSITE_PROVIDER=s3 but these are unset: " + ", ".join(missing)
            )
        if "/" in bucket:
            raise OffsiteConfigError(
                f"BACKUP_S3_BUCKET must be a bucket name, not a path (got {bucket!r}) — "
                "put any subdirectory in BACKUP_S3_PREFIX"
            )

        self.bucket = bucket.strip()
        self.region = region.strip()
        self.access_key_id = access_key_id.strip()
        self._secret = secret_access_key.strip()
        self.timeout_s = timeout_s
        # A prefix is a key namespace, never a leading slash; normalise it to
        # exactly one trailing slash so key joining is unambiguous.
        self.prefix = prefix.strip().strip("/")
        if self.prefix:
            self.prefix += "/"

        endpoint = endpoint_url.strip().rstrip("/")
        if endpoint:
            if "://" not in endpoint:
                endpoint = f"https://{endpoint}"
            scheme, _, host = endpoint.partition("://")
            self._scheme = scheme
            self._host = host
            # Path-style: every S3-compatible endpoint (R2, B2, MinIO)
            # supports it; virtual-hosted needs per-bucket DNS they may not
            # give you.
            self._base_path = f"/{self.bucket}"
        else:
            self._scheme = "https"
            self._host = f"{self.bucket}.s3.{self.region}.amazonaws.com"
            self._base_path = ""

    # -- internals ---------------------------------------------------------

    def describe(self) -> str:
        """Human-readable target, safe to log (no credentials)."""
        return f"{self._scheme}://{self._host}{self._base_path}/{self.prefix}"

    def full_key(self, name: str) -> str:
        return f"{self.prefix}{name}"

    def _url(self, key: str = "", params: dict[str, str] | None = None) -> str:
        """The request URL, query string included and encoded EXACTLY as
        _canonical_query encodes it for the signature. The query is built
        here rather than handed to httpx's `params=` on purpose: httpx
        serialises with quote_plus (space → '+'), the signature uses
        percent-encoding, and any such divergence between the signed string
        and the wire is an unattributable 403 from the store."""
        path = f"{self._base_path}/{key}" if key else f"{self._base_path}/"
        url = f"{self._scheme}://{self._host}{_canonical_uri(path)}"
        query = _canonical_query(params or {})
        return f"{url}?{query}" if query else url

    def _path(self, key: str = "") -> str:
        return f"{self._base_path}/{key}" if key else f"{self._base_path}/"

    def _signed_headers(
        self,
        method: str,
        key: str,
        params: dict[str, str],
        payload_sha256: str,
        headers: dict[str, str] | None,
    ) -> dict[str, str]:
        return sign_request(
            method=method,
            host=self._host,
            path=self._path(key),
            params=params,
            headers=dict(headers or {}),
            payload_sha256=payload_sha256,
            access_key_id=self.access_key_id,
            secret_access_key=self._secret,
            region=self.region,
            now=datetime.now(timezone.utc),
        )

    def _request(
        self,
        method: str,
        *,
        key: str = "",
        params: dict[str, str] | None = None,
        payload_sha256: str = _EMPTY_SHA256,
        headers: dict[str, str] | None = None,
        body: IO[bytes] | bytes | None = None,
    ) -> httpx.Response:
        params = params or {}
        signed = self._signed_headers(method, key, params, payload_sha256, headers)
        try:
            with httpx.Client(timeout=self.timeout_s, follow_redirects=False) as client:
                resp = client.request(
                    method, self._url(key, params), headers=signed, content=body
                )
        except httpx.HTTPError as exc:
            raise self._transport_error(method, key, exc) from exc
        if resp.status_code >= 300:
            self._raise(method, key, resp)
        return resp

    def _download(self, key: str, dest: Path) -> int:
        """Stream one object to `dest`, via a .part file renamed on success —
        a download that dies halfway must not leave something that looks like
        a restorable snapshot."""
        signed = self._signed_headers("GET", key, {}, _EMPTY_SHA256, None)
        part = dest.with_name(dest.name + ".part")
        written = 0
        try:
            with httpx.Client(timeout=self.timeout_s, follow_redirects=False) as client:
                with client.stream("GET", self._url(key), headers=signed) as resp:
                    if resp.status_code >= 300:
                        resp.read()
                        self._raise("GET", key, resp)
                    with part.open("wb") as fh:
                        for chunk in resp.iter_bytes(_CHUNK):
                            fh.write(chunk)
                            written += len(chunk)
        except httpx.HTTPError as exc:
            part.unlink(missing_ok=True)
            raise self._transport_error("GET", key, exc) from exc
        except BaseException:
            part.unlink(missing_ok=True)
            raise
        part.replace(dest)
        return written

    def _transport_error(self, method: str, key: str, exc: Exception) -> OffsiteBackupError:
        return OffsiteBackupError(
            f"{method} {self.bucket}/{key or '(list)'} failed: {type(exc).__name__}: {exc}"
        )

    def _raise(self, method: str, key: str, resp: httpx.Response) -> None:
        """Turn an S3 error response into one readable exception. The store's
        error XML carries the actionable part (NoSuchBucket vs
        SignatureDoesNotMatch vs AccessDenied); the raw body is truncated
        because JobRun.error keeps only 300 chars."""
        code = message = ""
        try:
            root = ET.fromstring(resp.content[:_MAX_RESPONSE_BYTES])
            code = (_find_text(root, "Code") or "").strip()
            message = (_find_text(root, "Message") or "").strip()
        except ET.ParseError:
            pass
        detail = f"{code}: {message}" if code else resp.text[:200].replace("\n", " ")
        raise OffsiteBackupError(
            f"{method} {self.bucket}/{key or '(list)'} → HTTP {resp.status_code} — {detail}"
        )

    # -- operations --------------------------------------------------------

    def put_file(self, path: Path, name: str) -> dict:
        """Upload `path` as `<prefix><name>`. Streams: the file is hashed in
        chunks and sent with an explicit Content-Length, so peak memory is
        one chunk regardless of database size."""
        size = path.stat().st_size
        if size > _MAX_SINGLE_PUT_BYTES:
            raise OffsiteBackupError(
                f"{path.name} is {size} bytes — above S3's 5GiB single-part PUT limit; "
                "multipart upload is not implemented"
            )
        digest = hashlib.sha256()
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(_CHUNK), b""):
                digest.update(chunk)
        payload_hash = digest.hexdigest()

        key = self.full_key(name)
        with path.open("rb") as fh:
            self._request(
                "PUT",
                key=key,
                payload_sha256=payload_hash,
                # Explicit Content-Length keeps httpx from switching a
                # file-like body to chunked transfer-encoding, which S3
                # rejects for a signed single-part payload.
                headers={"Content-Length": str(size)},
                body=fh,
            )
        log.info("offsite_backup: uploaded %s (%d bytes) to %s", name, size, self.describe())
        return {"key": key, "bytes": size, "sha256": payload_hash}

    def list_objects(self) -> list[RemoteObject]:
        """Every object under the prefix, following continuation tokens."""
        out: list[RemoteObject] = []
        token: str | None = None
        for _ in range(1000):  # hard stop; 1000 pages = 1M objects
            params = {"list-type": "2", "max-keys": "1000"}
            if self.prefix:
                params["prefix"] = self.prefix
            if token:
                params["continuation-token"] = token
            resp = self._request("GET", params=params)
            root = ET.fromstring(resp.content[:_MAX_RESPONSE_BYTES])
            for node in _find_all(root, "Contents"):
                key = _find_text(node, "Key") or ""
                if not key or key.endswith("/"):
                    continue
                out.append(
                    RemoteObject(
                        key=key,
                        size=int(_find_text(node, "Size") or 0),
                        last_modified=_parse_iso8601(_find_text(node, "LastModified")),
                    )
                )
            if (_find_text(root, "IsTruncated") or "").lower() != "true":
                break
            token = _find_text(root, "NextContinuationToken")
            if not token:
                break
        return out

    def get_to_file(self, key: str, dest: Path) -> int:
        """Download `key` (a FULL key, as returned by list_objects) to
        `dest`, streaming. Returns bytes written."""
        dest.parent.mkdir(parents=True, exist_ok=True)
        return self._download(key, dest)

    def delete(self, key: str) -> None:
        self._request("DELETE", key=key)


# ---------------------------------------------------------------------------
# XML / date helpers. Providers are inconsistent about the S3 namespace, so
# match on the LOCAL tag name and ignore any namespace entirely.


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _find_text(node: ET.Element, name: str) -> str | None:
    for child in node.iter():
        if child is not node and _local(child.tag) == name:
            return child.text
    return None


def _find_all(node: ET.Element, name: str) -> list[ET.Element]:
    return [child for child in node if _local(child.tag) == name]


def _parse_iso8601(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Selection + retention


def get_offsite_store() -> S3OffsiteStore | None:
    """The configured store, or None when offsite replication is off.

    Unlike the mailer (whose unknown-provider fallback is the harmless
    console transport), an unrecognised provider raises: silently not
    replicating is the failure this feature exists to prevent.
    """
    provider = (settings.backup_offsite_provider or "none").strip().lower()
    if provider in ("", "none", "off", "disabled"):
        return None
    if provider != "s3":
        raise OffsiteConfigError(
            f"BACKUP_OFFSITE_PROVIDER={provider!r} is not recognised (use 'none' or 's3')"
        )
    return S3OffsiteStore(
        bucket=settings.backup_s3_bucket,
        region=settings.backup_s3_region,
        access_key_id=settings.backup_s3_access_key_id,
        secret_access_key=settings.backup_s3_secret_access_key,
        endpoint_url=settings.backup_s3_endpoint_url,
        prefix=settings.backup_s3_prefix,
        timeout_s=settings.backup_offsite_timeout_s,
    )


def prune_remote(
    store: S3OffsiteStore,
    *,
    retention_days: int,
    keep_min: int = 3,
    now: datetime | None = None,
) -> int:
    """Delete offsite snapshots older than `retention_days`. Returns the
    count deleted. `retention_days <= 0` deletes nothing (the default —
    see settings.backup_offsite_retention_days).

    Three deliberate guards, because the worst thing this whole module
    could do is delete the only surviving copy of the database:
      1. only keys matching `dashboard-YYYYMMDD-HHMMSS.db` are candidates;
      2. the newest `keep_min` snapshots are never deleted, whatever their
         age — a clock or timezone bug therefore cannot empty the bucket;
      3. a candidate must look old by BOTH its own key stamp AND the
         store's LastModified, so one bad signal alone deletes nothing.
    """
    if retention_days <= 0:
        return 0
    now = now or datetime.now(timezone.utc)
    cutoff = now.timestamp() - retention_days * 86_400

    candidates: list[tuple[float, RemoteObject]] = []
    for obj in store.list_objects():
        match = _KEY_STAMP_RE.search(obj.key)
        if not match:
            continue
        try:
            stamped = datetime.strptime(match.group(1), "%Y%m%d-%H%M%S").replace(
                tzinfo=timezone.utc
            )
        except ValueError:
            continue
        candidates.append((stamped.timestamp(), obj))

    candidates.sort(key=lambda pair: pair[0], reverse=True)
    deleted = 0
    for stamp_ts, obj in candidates[keep_min:]:
        if stamp_ts >= cutoff:
            continue
        if obj.last_modified is None or obj.last_modified.timestamp() >= cutoff:
            # Key says old, the store says recent (or says nothing): a
            # re-uploaded or clock-skewed object. Leave it.
            continue
        store.delete(obj.key)
        deleted += 1
    if deleted:
        log.info("offsite_backup: pruned %d snapshot(s) older than %dd", deleted, retention_days)
    return deleted
