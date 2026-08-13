#!/usr/bin/env python3
"""Verify the API keys in an env file actually work — without ever printing them.

Run it from the REPO ROOT, with the backend venv's python (the system
python3 on macOS framework builds ships no usable root store and fails
every HTTPS call with CERTIFICATE_VERIFY_FAILED, which looks exactly like
a revoked key):

  backend/.venv/bin/python backend/scripts/check_keys.py .env

Prints one PASS/FAIL line per provider. Key VALUES are never echoed; only a
length and a 4-char fingerprint of the sha256, enough to tell "the file
changed" from "I edited the wrong line".

Use it twice around a rotation:
  1. against the NEW .env   -> expect all PASS
  2. against a scratch file holding the OLD keys -> expect all FAIL/401,
     which is what proves the old credentials were really revoked and not
     just replaced locally.
"""

from __future__ import annotations

import hashlib
import json
import sys
import urllib.error
import urllib.parse
import urllib.request

TIMEOUT = 15

# Some Python builds (notably python.org framework installs on macOS) ship no
# usable root store, which fails every HTTPS call with CERTIFICATE_VERIFY_FAILED
# and looks exactly like a dead key. Prefer certifi's bundle when present.
try:
    import ssl

    import certifi

    _SSL_CTX: ssl.SSLContext | None = ssl.create_default_context(
        cafile=certifi.where()
    )
except Exception:
    _SSL_CTX = None


def load_env(path: str) -> dict[str, str]:
    out: dict[str, str] = {}
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def fingerprint(value: str) -> str:
    """Non-reversible identity marker, so you can confirm the file changed."""
    if not value:
        return "unset"
    digest = hashlib.sha256(value.encode()).hexdigest()[:4]
    return f"len={len(value)} fp={digest}"


def get(url: str, headers: dict[str, str] | None = None) -> tuple[int, str]:
    req = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT, context=_SSL_CTX) as resp:
            # Read enough to parse — truncating mid-JSON turns a healthy 200
            # into a bogus FAIL. Error detail is trimmed at the print site.
            return resp.status, resp.read(16384).decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(16384).decode("utf-8", "replace")
    except Exception as exc:  # network down, DNS, TLS
        return 0, f"{type(exc).__name__}: {exc}"


def report(name: str, ok: bool, detail: str, fp: str) -> bool:
    status = "PASS" if ok else "FAIL"
    print(f"  [{status}] {name:<22} {fp:<22} {detail}")
    return ok


def main() -> int:
    path = sys.argv[1] if len(sys.argv) > 1 else ".env"
    env = load_env(path)
    print(f"Checking credentials in {path}\n")
    results = []

    # -- Alpaca market data -------------------------------------------------
    ak, asec = env.get("ALPACA_API_KEY", ""), env.get("ALPACA_API_SECRET", "")
    fp = fingerprint(ak)
    if not ak or not asec:
        results.append(report("Alpaca (data)", False, "key or secret unset", fp))
    else:
        hdrs = {"APCA-API-KEY-ID": ak, "APCA-API-SECRET-KEY": asec}
        code, body = get(
            "https://data.alpaca.markets/v2/stocks/SPY/snapshot", hdrs
        )
        ok = code == 200
        detail = "snapshot ok" if ok else f"HTTP {code} {body[:90]}"
        results.append(report("Alpaca (data)", ok, detail, fp))

        # Paper trading endpoint — the clock call the app makes.
        code, body = get("https://paper-api.alpaca.markets/v2/clock", hdrs)
        ok = code == 200
        detail = "clock ok" if ok else f"HTTP {code} {body[:90]}"
        results.append(report("Alpaca (paper trade)", ok, detail, fingerprint(asec)))

    # -- Finnhub ------------------------------------------------------------
    fk = env.get("FINNHUB_API_KEY", "")
    fp = fingerprint(fk)
    if not fk:
        results.append(report("Finnhub", False, "unset", fp))
    else:
        q = urllib.parse.urlencode({"symbol": "AAPL", "token": fk})
        code, body = get(f"https://finnhub.io/api/v1/quote?{q}")
        ok = code == 200 and '"c"' in body
        detail = "quote ok" if ok else f"HTTP {code} {body[:90]}"
        results.append(report("Finnhub", ok, detail, fp))

    # -- FRED ---------------------------------------------------------------
    rk = env.get("FRED_API_KEY", "")
    fp = fingerprint(rk)
    if not rk:
        results.append(report("FRED", False, "unset", fp))
    else:
        q = urllib.parse.urlencode(
            {"series_id": "DGS10", "api_key": rk, "file_type": "json"}
        )
        code, body = get(f"https://api.stlouisfed.org/fred/series?{q}")
        ok = code == 200
        if ok:
            try:
                ok = bool(json.loads(body).get("seriess"))
            except Exception:
                ok = False
        detail = "series ok" if ok else f"HTTP {code} {body[:90]}"
        results.append(report("FRED", ok, detail, fp))

    passed = sum(1 for r in results if r)
    print(f"\n{passed}/{len(results)} checks passed")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
