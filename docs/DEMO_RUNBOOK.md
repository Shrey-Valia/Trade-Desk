# Investor Demo Runbook — Trade Desk

**Target date:** Tue 2026-07-28 · **Baseline:** backend 1126 tests pass, frontend typecheck clean.

This is the one-page setup + click-through for the live investor demo. Do the
**Tonight** section the night before; run the **Morning-of** checks 30 min before
you present.

---

## 1. Tonight — one-time config

All of these are set in the root `.env` (git-ignored). A ready-to-paste block
lives in [`.env.demo.example`](../.env.demo.example) — copy the lines you need
into `.env`.

| Setting | Value | Why |
|---|---|---|
| `ADMIN_EMAILS` | `["<your-login-email>"]` | **Without this the entire Admin console 403s.** JSON-array syntax. Use the lowercased email you'll sign in with. |
| `SEED_TRADES` | `1` | Cold DB otherwise shows an empty journal/analytics. Seeded data is DB-only (weekend/after-hours safe). |
| `PAYOUT_AUTO_APPROVE` | `0` | Otherwise any payout >1h old is auto-approved out of the queue you want to demo approving by hand. |
| `KYC_AUTO_VERIFY` | `0` | Otherwise KYC never sits at `pending`, so the manual review flow can't be shown. |
| `COOKIE_SECURE` | `0` | **Only if** serving over plain HTTP on a LAN IP / hostname / Safari. Not needed on `localhost`. |

> **Admin seat:** there is no seeded admin row — the role is minted from the
> `ADMIN_EMAILS` allowlist on first identity check (`/api/auth/me`). Set
> `ADMIN_EMAILS`, sign in with that email, and the **Admin** nav item appears.
> (A live dry-run on 2026-07-27 found that promotion previously fired only on
> an `/api/admin/*` call, which the UI never reaches — the route guard redirects
> a non-admin away first — leaving the console unreachable. Fixed so `/me`
> applies the bootstrap; setting `ADMIN_EMAILS` is now sufficient.)

After editing `.env`, restart the backend so it re-reads config.

---

## 2. Morning-of — 30-minute pre-flight

Run in order. Each must pass before you present.

```bash
# 1. Confirm the Alpaca feed returns a LIVE chain today (keys not stale/rate-limited).
#    Run DURING market hours — after-hours the 0DTE chain is empty/expired.
curl -s "http://localhost:8000/api/zerodte/chain?symbol=SPY" | head -c 400; echo
# expect a JSON ATM call+put payload, NOT a 503 "market data degraded"
```

```bash
# 2. Backend + frontend green (optional but fast).
cd backend && uv run pytest -q -x
cd ../frontend && npx tsc --noEmit
```

- **Trade during market hours (09:30–16:00 ET).** Every position-open path is
  hard-gated on the live NYSE clock — there is **no override**. Off-session,
  create-combine works but "open a position" returns 409 *Market closed*.
  Schedule the live trading portion of the demo inside RTH.
- Sign in with your `ADMIN_EMAILS` address once, confirm the **Admin** nav item
  loads (Overview / Users / Payouts / Support / Platform / Jobs / Audit).

---

## 3. The click-through (happy path)

1. **Sign up / sign in** → land on the dashboard.
2. **New combine** → pick a tier (50K/100K/150K) → purchase.
   *Note: with Stripe keys blank, purchase is free/simulated — say "simulated
   prop-firm billing," not "live payments."*
3. **Open a position** (during RTH): pick a symbol, draw the option on the chart,
   fire the order. Show the magenta breakeven line + entry marker.
4. **Close it** → confirm the position books and the journal entry appears.
5. **Journal** → open the day, show P&L attribution, tags, notes.
6. **Analytics / Dashboard** → *close at least two trades, one a loser, first* —
   profit factor reads "∞" with zero losers and the balance curve needs ≥2
   closed trades. These are correct behaviors, not bugs; just don't show a
   one-trade account.
7. **Admin tour**: Platform (kill-switch toggle), Payout queue (approve/deny),
   Users (KYC review), Audit log.

---

## 4. Talking points (correct behavior — brief the presenter)

- **Purchase is simulated** (Stripe not wired) — intended for a sim prop firm.
- **KYC auto-verify / payout auto-approve** are turned off for the demo so the
  manual review flows are visible; in production they're configurable.
- **Market data degrades gracefully**: the DB-backed surfaces (auth, journal,
  combines, admin) all render with the feed down — only live *opens* need a
  live market.
- **Single-instance deploy** is a hard constraint (rate limiters + scheduler are
  process-local). Don't scale replicas.

---

## 5. Known cosmetic items (won't block; fixed on `fix/demo-readiness-2026-07-28`)

Reset-combine confirm, header cold-load skeleton (no more flash of `$0.00`),
copy-trade ratio-integrity guard, atomic kill-switch audit, arm-to-confirm on the
working-order cancel and resting-close-limit pull, NaN theta-label guard, and a
few in-flight double-submit guards. All covered by the branch; merge before the
demo if you want them in.

---

## 6. T‑30 pre-demo checklist

Run start to finish before anyone's watching. Ordered by time.

### T‑30 → T‑20 · Bring it up
- [ ] Backend: `uv run --directory backend uvicorn main:app --port 8000` — watch for `Application startup complete`, no tracebacks.
- [ ] Frontend: `npm --prefix frontend run dev -- --port 5199`.
- [ ] Confirm `.env` still has `ADMIN_EMAILS=["valia.s@northeastern.edu"]`.

### T‑20 → T‑15 · Log in *(before the room — a cold browser can drop the session)*
- [ ] `http://localhost:5199` → sign in (demo creds).
- [ ] Confirm the **Admin** nav item shows (admin role minted).

### T‑15 → T‑8 · Verify the demo state
- [ ] **Dashboard:** BAL $106,599.99 · CLOSED P&L +$6,599.99 · amber "Evaluation passed" banner + green **Activate** button; curve + tracker (69% / 13 closed) all agree.
- [ ] **Journal:** 13 trades · +$6,599.99 · 69%.
- [ ] **Analytics:** profit factor 4.93, equity curve populated.
- [ ] **Accounts:** 100K FUNDED, prominent green Activate button.
- [ ] **Admin → Overview** loads; click **Platform** once (kill-switch renders).

### T‑8 → T‑3 · Warm the terminal (the slow one)
- [ ] Open Chart/Positions and leave it ~10s so the live SPY chart finishes loading (~5s cold — don't open it live on stage cold).
- [ ] Market-hours check (only for the live trade): header reads market OPEN during 09:30–16:00 ET; if closed, narrate over the chart.
- [ ] Optional feed check: `curl -s "http://localhost:8000/api/zerodte/chain?symbol=SPY" | head -c 200` → JSON, not a 503.

### T‑3 → T‑0 · Presentation hygiene
- [ ] Browser at desktop width, zoom 100%, full-screen; close unrelated tabs.
- [ ] Land on the opening screen (Dashboard, or Landing for the cold open).
- [ ] `docs/INVESTOR_QA.md` open in another window, real metrics filled into the `[brackets]`.

### 🚫 Do NOT (on stage)
- Click **Activate** mid-demo unless it's your finale (it resets the card to $100k funded — correct behavior, jarring mid-flow).
- Open the terminal cold and talk over a "Loading…" spinner — warm it first.
- Attempt a live trade after-hours — opens are gated ("market closed").

### 🆘 If something breaks
- **Logged out / blank:** re-sign-in; DB data persists.
- **Chart won't load / chain empty:** market's likely closed or the feed's cold — narrate over it, it's not a crash.
- **Account state wrong** (shows $100k / $0 = it got activated): reset combine 11 to funded-not-activated (`funded_activated_at=None, funded_epoch_at=None, hwm=settled_hwm=106599.99`; import models.user + models.trade first).
- **Total fallback:** keep screenshots of the 7 beats on hand to present from images if the network dies.
