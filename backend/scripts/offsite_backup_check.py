#!/usr/bin/env python3
"""Exercise offsite backups for real: list them, force one, restore one.

Run from the REPO ROOT with the backend venv's python, so the .env beside
docker-compose.yml is the configuration under test:

  backend/.venv/bin/python backend/scripts/offsite_backup_check.py list
  backend/.venv/bin/python backend/scripts/offsite_backup_check.py put
  backend/.venv/bin/python backend/scripts/offsite_backup_check.py restore /tmp/restored.db

WHY EACH SUBCOMMAND EXISTS

  list     — what is actually in the bucket, with ages. Answers "is
             replication still happening?" without reading logs. Exits
             non-zero when the newest snapshot is older than --max-age-h,
             so it also works as a cron/monitor check.
  put      — upload the newest LOCAL snapshot NOW. This is the credential
             test: bucket, keys, region, endpoint and prefix are all wrong
             in ways no unit test can discover, and waiting for the 02:30 ET
             cron to find out is a bad trade.
  restore  — download the newest remote snapshot and open it: PRAGMA
             integrity_check plus row counts for the tables that matter.
             A backup nobody has ever restored is not a backup, and this is
             the cheapest possible way to stop believing in one.

Credentials are never printed. On failure the exit code is non-zero.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import settings  # noqa: E402
from services.offsite_backup import (  # noqa: E402
    OffsiteBackupError,
    OffsiteConfigError,
    RemoteObject,
    get_offsite_store,
)

_BACKUP_GLOB = "dashboard-*.db"
# Tables whose emptiness in a "successful" restore would mean the snapshot is
# useless. Missing tables are reported, not fatal — the schema moves.
_SANITY_TABLES = ("users", "combines", "trades")


def _size(n: int) -> str:
    val = float(n)
    for unit in ("B", "KiB", "MiB", "GiB"):
        if val < 1024 or unit == "GiB":
            return f"{val:.1f}{unit}" if unit != "B" else f"{val:.0f}B"
        val /= 1024
    return f"{val:.1f}GiB"


def _age_h(obj: RemoteObject) -> float | None:
    if obj.last_modified is None:
        return None
    return (datetime.now(timezone.utc) - obj.last_modified).total_seconds() / 3600


def _store():
    try:
        store = get_offsite_store()
    except OffsiteConfigError as exc:
        print(f"FAIL  configuration: {exc}")
        return None
    if store is None:
        print(
            "offsite replication is OFF (BACKUP_OFFSITE_PROVIDER=none).\n"
            "Nothing is being copied off this machine — see docs/DEPLOYMENT.md."
        )
        return None
    print(f"target: {store.describe()}   region={store.region}")
    return store


def _snapshots(store) -> list[RemoteObject]:
    objs = [o for o in store.list_objects() if o.key.endswith(".db")]
    objs.sort(key=lambda o: o.key, reverse=True)
    return objs


def cmd_list(args) -> int:
    store = _store()
    if store is None:
        return 1
    objs = _snapshots(store)
    if not objs:
        print("FAIL  no snapshots found under the prefix")
        return 1
    for obj in objs:
        age = _age_h(obj)
        age_s = f"{age:6.1f}h ago" if age is not None else "   unknown"
        print(f"  {obj.key}  {_size(obj.size):>9}  {age_s}")
    newest_age = _age_h(objs[0])
    print(f"\n{len(objs)} snapshot(s), newest {objs[0].key}")
    if newest_age is not None and newest_age > args.max_age_h:
        print(f"FAIL  newest snapshot is {newest_age:.1f}h old (> {args.max_age_h}h)")
        return 1
    print("PASS  replication looks current")
    return 0


def cmd_put(args) -> int:
    store = _store()
    if store is None:
        return 1
    local_dir = Path(settings.backup_dir)
    local = sorted(local_dir.glob(_BACKUP_GLOB), key=lambda p: p.stat().st_mtime)
    if not local:
        print(
            f"FAIL  no local snapshot in {local_dir} to upload — run the backup job "
            "first (it runs at 02:30 ET, or on boot when the newest is >20h old)"
        )
        return 1
    newest = local[-1]
    print(f"uploading {newest.name} ({_size(newest.stat().st_size)}) …")
    started = time.perf_counter()
    put = store.put_file(newest, newest.name)
    print(
        f"PASS  wrote {put['key']} in {time.perf_counter() - started:.1f}s  "
        f"sha256={put['sha256'][:12]}…"
    )
    return 0


def cmd_restore(args) -> int:
    store = _store()
    if store is None:
        return 1
    objs = _snapshots(store)
    if not objs:
        print("FAIL  no snapshots found under the prefix")
        return 1
    target = objs[0]
    dest = Path(args.dest).expanduser().resolve()
    if dest.exists() and not args.force:
        print(f"FAIL  {dest} exists (pass --force to overwrite)")
        return 1
    print(f"downloading {target.key} ({_size(target.size)}) → {dest} …")
    written = store.get_to_file(target.key, dest)
    if target.size and written != target.size:
        print(f"FAIL  wrote {written} bytes, store reported {target.size}")
        return 1

    # The part that makes this a restore drill rather than a download: open
    # the file as SQLite and make it prove it is a usable database.
    try:
        with sqlite3.connect(f"file:{dest}?mode=ro", uri=True) as conn:
            integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
            tables = {
                row[0]
                for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            counts = []
            for name in _SANITY_TABLES:
                if name not in tables:
                    counts.append(f"{name}=MISSING")
                    continue
                n = conn.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]  # noqa: S608
                counts.append(f"{name}={n}")
    except sqlite3.DatabaseError as exc:
        print(f"FAIL  downloaded file is not a readable SQLite database: {exc}")
        return 1

    print(f"  integrity_check: {integrity}")
    print(f"  tables: {len(tables)}   {'  '.join(counts)}")
    if integrity != "ok":
        print("FAIL  integrity_check did not return 'ok'")
        return 1
    print(f"PASS  restored {written} bytes to {dest}")
    print(
        "\nTo run the app on it: stop the container, replace the live database "
        "file with this one (keeping a copy of the old), and start again — "
        "docs/DEPLOYMENT.md has the exact steps."
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd")

    p_list = sub.add_parser("list", help="list offsite snapshots and their ages")
    p_list.add_argument(
        "--max-age-h",
        type=float,
        default=48.0,
        help="fail if the newest snapshot is older than this (default 48)",
    )
    p_list.set_defaults(func=cmd_list)

    p_put = sub.add_parser("put", help="upload the newest local snapshot now")
    p_put.set_defaults(func=cmd_put)

    p_restore = sub.add_parser("restore", help="download the newest snapshot and verify it")
    p_restore.add_argument("dest", help="where to write the downloaded database")
    p_restore.add_argument("--force", action="store_true", help="overwrite dest if it exists")
    p_restore.set_defaults(func=cmd_restore)

    args = parser.parse_args()
    if not getattr(args, "func", None):
        parser.print_help()
        return 2
    try:
        return args.func(args)
    except OffsiteBackupError as exc:
        # A store error is an expected outcome here (wrong bucket, revoked
        # token, dropped connection); print it as one FAIL line rather than a
        # traceback, so the exit code and the message are the whole answer.
        print(f"FAIL  {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
