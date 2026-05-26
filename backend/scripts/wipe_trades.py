"""Wipe ALL rows from the trades table.

The seed used to top up the journal to ~39 fake trades on first boot.
After we gated the seed behind `SEED_TRADES=1` (off by default), the
existing DB still has those seed rows plus any junk created during
debugging. This script clears them so the user starts from zero.

Usage:
    cd backend && .venv/bin/python -m scripts.wipe_trades [--yes]

By default it asks for confirmation. Pass --yes to skip the prompt.

Idempotent: running on an empty trades table is a no-op.
"""

from __future__ import annotations

import argparse
import sys

from sqlalchemy import delete

from database import SessionLocal, init_db
from models.trade import Trade


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Skip the interactive confirmation.",
    )
    args = parser.parse_args()

    init_db()
    with SessionLocal() as session:
        before = session.query(Trade).count()
        if before == 0:
            print("trades table already empty; nothing to do.")
            return 0
        if not args.yes:
            print(f"This will delete {before} rows from the trades table.")
            reply = input("Type 'wipe' to confirm: ").strip().lower()
            if reply != "wipe":
                print("aborted.")
                return 1
        session.execute(delete(Trade))
        session.commit()
        after = session.query(Trade).count()
    print(f"wiped {before} trade(s); table now has {after}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
