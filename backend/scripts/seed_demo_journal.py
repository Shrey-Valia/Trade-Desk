"""Seed a realistic demo journal onto ONE user's active combine.

Unlike the built-in `SEED_TRADES` boot seed (which inserts combine-less
orphan trades that the per-combine journal never shows, and skips entirely
once the table already has ≥10 rows), this attaches a curated set of closed
0DTE trades to a specific user's ACTIVE combine — so their journal, analytics,
and dashboard all populate and reconcile.

Balance is derived (`starting_balance + Σ realized_pnl` over the combine's
closed execution fills — services.combine_state.realized_sum_for_combine), so
the trades alone move the balance; we additionally walk the combine's HWM up to
the peak so the trailing-MLL floor stays consistent.

Run from the backend directory AFTER the user has signed up and started a
combine:

    python -m scripts.seed_demo_journal --email valia.s@northeastern.edu
    python -m scripts.seed_demo_journal --email you@x.com --force   # re-seed

Idempotent: refuses to run if the combine already has trades, unless --force
(which first removes prior demo-seeded rows, tagged "demo").
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, time, timedelta, timezone

from sqlalchemy import select

from database import SessionLocal
from models.combine import Combine
from models.trade import Trade
from models.user import User
from services.account_tiers import TIERS

_ET = timezone(timedelta(hours=-4))  # EDT — cosmetic timestamps only
_SEED_TAG = "demo"

# Curated trades at 50K scale (contracts + P&L scale up with the tier). Each:
# (symbol, spot, strategy, legs, pnl_50k, tags, mistakes, thesis, notes).
# A leg = (side, action, strike, entry_price, contracts_50k). Net is
# realistic-ish; only realized_pnl drives account math.
_TEMPLATES = [
    ("SPY", 735.0, "long_call", [("call", "buy", 735, 1.15, 4)], 540.0,
     ["0dte", "momentum"], [], "Trend day continuation off the open drive.",
     "Clean break of overnight high, held to the 2:30 push."),
    ("QQQ", 630.0, "long_put", [("put", "buy", 630, 1.30, 3)], -210.0,
     ["0dte"], ["chased"], "Failed breakdown.",
     "Entered late on a move already extended; faded on me."),
    ("SPY", 736.0, "call_vertical",
     [("call", "buy", 736, 1.05, 5), ("call", "sell", 739, 0.45, 5)], 320.0,
     ["0dte", "defined-risk"], [], "Defined-risk debit spread into strength.",
     "Took the spread to cap theta; exited at 70% of max."),
    ("IWM", 240.0, "long_call", [("call", "buy", 240, 0.85, 4)], -180.0,
     ["0dte"], ["size-too-big"], "Rotation into small caps.",
     "Oversized for a chop day; stopped for a small loss."),
    ("NVDA", 180.0, "long_call", [("call", "buy", 180, 1.60, 3)], 620.0,
     ["0dte", "momentum"], [], "Gap-and-go after the AI headline.",
     "Best setup of the week — trailed the runner into the close."),
    ("SPY", 734.0, "straddle",
     [("call", "buy", 734, 1.10, 2), ("put", "buy", 734, 1.05, 2)], -300.0,
     ["0dte", "vol"], ["held-too-long"], "Expected an expansion that didn't come.",
     "IV crush chopped both legs; should have cut at lunch."),
    ("QQQ", 628.0, "put_vertical",
     [("put", "buy", 628, 1.00, 5), ("put", "sell", 625, 0.42, 5)], 260.0,
     ["0dte", "defined-risk"], [], "Fade the failed retest.",
     "Clean defined-risk fade; covered into support."),
    ("TSLA", 350.0, "long_put", [("put", "buy", 350, 2.10, 2)], 410.0,
     ["0dte"], [], "Breakdown from the range.",
     "Momentum short via puts; took it at the measured move."),
    ("SPY", 737.0, "long_call", [("call", "buy", 737, 0.95, 4)], -150.0,
     ["0dte"], [], "Continuation that stalled.",
     "Small stop-out — respected the level and moved on."),
    ("AAPL", 235.0, "long_call", [("call", "buy", 235, 1.05, 3)], 230.0,
     ["0dte"], [], "Bounce off the rising 20.",
     "Base-hit long into the afternoon bid."),
]


def _trading_days_back(n: int) -> list[datetime]:
    """The last `n` weekdays (most recent last), as ~10:15 ET datetimes."""
    out: list[datetime] = []
    d = datetime.now(_ET).date() - timedelta(days=1)
    while len(out) < n:
        if d.weekday() < 5:  # Mon–Fri
            out.append(datetime.combine(d, time(10, 15), tzinfo=_ET))
        d -= timedelta(days=1)
    return list(reversed(out))


def _resolve_combine(session, email: str) -> Combine:
    user = session.execute(
        select(User).where(User.email == email.strip().lower())
    ).scalar_one_or_none()
    if user is None:
        raise SystemExit(
            f"No user {email!r}. Sign up in the app first (you set the "
            f"password), then re-run this."
        )
    combine = None
    if user.active_combine_id is not None:
        combine = session.get(Combine, user.active_combine_id)
    if combine is None:
        combine = session.execute(
            select(Combine)
            .where(Combine.user_id == user.id, Combine.status == "active")
            .order_by(Combine.id)
        ).scalars().first()
    if combine is None:
        raise SystemExit(
            f"{email} has no active combine. Click 'Start a combine' in the "
            f"app, then re-run this."
        )
    return combine


def _weekdays_back(start_offset: int, count: int) -> list[datetime]:
    """`count` weekdays ending `start_offset` days before today (oldest first)."""
    out: list[datetime] = []
    d = datetime.now(_ET).date() - timedelta(days=start_offset)
    while len(out) < count:
        if d.weekday() < 5:
            out.append(datetime.combine(d, time(10, 30), tzinfo=_ET))
        d -= timedelta(days=1)
    return list(reversed(out))


def _pass_eval(session, combine) -> None:
    """Top the combine up past its profit target with additional winning days,
    keeping the 50%-of-total consistency rule intact, so the live evaluator
    (services.combine_state) auto-passes and funds it → activation required."""
    tier = TIERS[combine.tier]
    target = tier.starting_balance * 0.06  # 50K→3k, 100K→6k, 150K→9k
    rows = session.execute(
        select(Trade).where(
            Trade.combine_id == combine.id,
            Trade.status == "closed",
            Trade.origin == "execution",
        )
    ).scalars().all()
    current = float(sum(t.realized_pnl or 0.0 for t in rows))
    goal = target * 1.10  # clear the bar with headroom
    deficit = goal - current
    if deficit <= 0:
        print(f"Already at ${current:,.0f} ≥ target ${target:,.0f} — nothing to add.")
        return

    # Spread the deficit over >=3 fresh days, each well under 50% of the final
    # total so consistency holds (cap each day at 30% of goal).
    cap = 0.30 * goal
    n = max(3, -(-int(deficit) // int(cap)))  # ceil
    per = round(deficit / n, 2)
    # Place them on weekdays BEFORE the base-seed window (last ~14 weekdays),
    # so they don't collide with existing rows.
    days = _weekdays_back(21, n)
    symbols = [("SPY", 735.0, 735), ("QQQ", 630.0, 630), ("NVDA", 180.0, 180),
               ("IWM", 240.0, 240), ("AAPL", 235.0, 235)]
    for i, entry_dt in enumerate(days):
        sym, spot, strike = symbols[i % len(symbols)]
        contracts = max(2, round(4 * tier.starting_balance / 50_000.0))
        legs = [{
            "side": "call", "action": "buy", "strike": float(strike),
            "expiry": entry_dt.date().isoformat(), "contracts": contracts,
            "entry_price": 1.20,
        }]
        cost = 1.20 * contracts * 100
        entry_utc = entry_dt.astimezone(timezone.utc)
        exit_utc = (entry_dt + timedelta(hours=3)).astimezone(timezone.utc)
        session.add(
            Trade(
                symbol=sym, strategy="long_call", legs_json=json.dumps(legs),
                entry_date=entry_utc, entry_underlying_price=spot,
                net_debit_credit=round(cost, 2), status="closed",
                exit_date=exit_utc, exit_underlying_price=round(spot * 1.004, 2),
                realized_pnl=per, is_paper=True,
                notes="Target push — clean momentum long.",
                tags_json=json.dumps(["0dte", "momentum", _SEED_TAG]),
                mistake_tags_json="[]", thesis="Trend-day continuation.",
                tier=combine.tier, combine_id=combine.id, order_type="market",
                time_in_force="gtc", origin="execution",
                created_at=entry_utc, updated_at=exit_utc,
            )
        )
    new_total = current + per * n
    peak_balance = tier.starting_balance + new_total
    combine.hwm = max(combine.hwm or tier.starting_balance, peak_balance)
    combine.settled_hwm = max(combine.settled_hwm or tier.starting_balance, peak_balance)
    combine.last_settled_at = datetime.now(timezone.utc)
    session.commit()
    print(
        f"Added {n} winning days (+${per:,.0f} each) → realized "
        f"${new_total:,.2f} ≥ target ${target:,.0f}; largest day ${per:,.0f} "
        f"≤ 50% of total (${new_total/2:,.0f}). Open the app — the evaluator "
        f"will pass + fund it, and Activate will appear."
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--email", default="valia.s@northeastern.edu")
    ap.add_argument("--force", action="store_true", help="re-seed (drops prior demo rows)")
    ap.add_argument("--pass", dest="pass_eval", action="store_true",
                    help="top up past the profit target so the eval passes (funds the account)")
    args = ap.parse_args()

    with SessionLocal() as session:
        combine = _resolve_combine(session, args.email)
        tier = TIERS[combine.tier]
        scale = tier.starting_balance / 50_000.0

        if args.pass_eval:
            _pass_eval(session, combine)
            return

        existing = session.execute(
            select(Trade).where(Trade.combine_id == combine.id)
        ).scalars().all()
        if existing:
            demo_rows = [t for t in existing if _SEED_TAG in json.loads(t.tags_json or "[]")]
            non_demo = [t for t in existing if t not in demo_rows]
            if non_demo and not args.force:
                raise SystemExit(
                    f"Combine {combine.account_code} already has "
                    f"{len(non_demo)} real trade(s); not touching it. Use "
                    f"--force to seed anyway."
                )
            for t in demo_rows:
                session.delete(t)
            session.flush()

        days = _trading_days_back(len(_TEMPLATES))
        cum = 0.0
        peak = 0.0
        for tpl, entry_dt in zip(_TEMPLATES, days):
            symbol, spot, strategy, legs, pnl_50k, tags, mistakes, thesis, notes = tpl
            pnl = round(pnl_50k * scale, 2)
            leg_dicts = [
                {
                    "side": side,
                    "action": action,
                    "strike": float(strike),
                    "expiry": entry_dt.date().isoformat(),
                    "contracts": max(1, round(contracts * scale)),
                    "entry_price": entry_price,
                }
                for (side, action, strike, entry_price, contracts) in legs
            ]
            cost = sum(
                (1 if l["action"] == "buy" else -1)
                * l["entry_price"] * l["contracts"] * 100
                for l in leg_dicts
            )
            exit_dt = entry_dt + timedelta(hours=3, minutes=20)
            entry_utc = entry_dt.astimezone(timezone.utc)
            exit_utc = exit_dt.astimezone(timezone.utc)
            session.add(
                Trade(
                    symbol=symbol,
                    strategy=strategy,
                    legs_json=json.dumps(leg_dicts),
                    entry_date=entry_utc,
                    entry_underlying_price=spot,
                    net_debit_credit=round(cost, 2),
                    status="closed",
                    exit_date=exit_utc,
                    exit_underlying_price=round(spot * (1.003 if pnl >= 0 else 0.997), 2),
                    realized_pnl=pnl,
                    is_paper=True,
                    notes=notes,
                    tags_json=json.dumps([*tags, _SEED_TAG]),
                    mistake_tags_json=json.dumps(mistakes),
                    thesis=thesis,
                    tier=combine.tier,
                    combine_id=combine.id,
                    order_type="market",
                    time_in_force="gtc",
                    origin="execution",
                    created_at=entry_utc,
                    updated_at=exit_utc,
                )
            )
            cum += pnl
            peak = max(peak, cum)

        # Walk the HWM up to the peak equity so the trailing-MLL floor stays
        # consistent with the seeded balance (balance derives from Σ pnl).
        peak_balance = tier.starting_balance + max(0.0, peak)
        combine.hwm = max(combine.hwm or tier.starting_balance, peak_balance)
        combine.settled_hwm = max(combine.settled_hwm or tier.starting_balance, peak_balance)
        combine.last_settled_at = datetime.now(timezone.utc)

        session.commit()
        net = round(cum, 2)
        print(
            f"Seeded {len(_TEMPLATES)} closed trades on {combine.account_code} "
            f"({combine.tier}) for {args.email}."
        )
        print(
            f"Net realized P&L {net:+,.2f} → balance "
            f"${tier.starting_balance + net:,.2f} "
            f"(target ${tier.starting_balance * 0.06:,.0f}); HWM walked to "
            f"${combine.settled_hwm:,.2f}."
        )


if __name__ == "__main__":
    main()
