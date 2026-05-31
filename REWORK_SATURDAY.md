# Saturday rework — punch-list batch

Three commits, nine fixes, all derived from AUDIT.md. The pitch
(Topstep-style options combine with a moving-breakeven hook) is
now defensible end-to-end: no two-magenta-lines optical illusion,
no 1D 404, no double-fire BUY/SELL, no cross-tier ghosts, no 5-second
lag on the header, no inert stub buttons.

`tsc --noEmit` clean after every commit. `216/216` backend tests pass.
Trading math, MLL/tier math, and backend services untouched in this
batch.

---

## Phase 1 — Chart honesty
Commit: `070fb28`

### 1a. AUDIT B-001 — drop the expiration-breakeven ghost line
`frontend/src/components/stock/AnnotatedChart.tsx`

Removed the loop at lines 431-452 that rendered `breakevensExpiration`
as a dotted magenta "BE✕" line alongside the live `breakevensToday`.
For a long_call with DTE>0 the two values differ (today ≈ 100.61,
expiry = 105.00) and both read as "breakeven" to a user. Now:

- single-leg (long_call / long_put / short_call / short_put) →
  **1 magenta line**
- straddle / strangle → 2 lines (still both live BEs, one above and
  one below the strike)

The today BE already moves toward the expiration BE as theta decays —
that motion IS the differentiator. Showing both was redundant and
visually confusing.

### 1b. AUDIT B-003 + new 1D 404 — restrict timeframes to real backend support
`frontend/src/components/positions/ChartToolbar.tsx`,
`frontend/src/pages/SettingsPage.tsx`,
`frontend/src/pages/PositionsPage.tsx`

Two problems collapsed into one fix:

(i) The toolbar's 1m/5m/15m/1h/4h "intraday" buttons all routed to
backend "1D" via `TF_REAL_MAP` — clicking any of them showed the
same bars. (ii) Backend "1D" minute bars 404 off-hours (`_fetch_bars`
raises `404 no bars for SPY @ 1D` when the day's minute series is
empty).

**Toolbar** now offers only `TF_OPTIONS = ["5D", "1M", "3M"]` — the
timeframes the backend serves reliably regardless of session.
`StubTimeframe` / `TF_REAL_MAP` / `REAL_TO_VISUAL` retired.
`OhlcStrip` simplified: the `visualTf` prop is gone; the strip reads
the real timeframe directly.

**Settings TimeframePicker** also drops 1D from `TIMEFRAMES` so a
fresh install / settings reset doesn't cold-open into a 404 over
the weekend.

**PositionsPage auto-switch-to-1D effect** (`useEffect` at line 68)
retired. The chart overlay's clamp-into-visible-band logic already
keeps the entry marker visible across 5D/1M/3M without forcing 1D.

### 1c. AUDIT G-001 / G-003 — hide chart toolbar stubs
`frontend/src/components/positions/ChartToolbar.tsx`

`CandleTypeStub`, `DrawingToolStubs` (three icons), `IndicatorsStub`,
and the now-redundant `Separator` all removed from the Toolbar's
render. The toolbar is:

`[5D] [1M] [3M] ... (right) LEGEND · levels↓`

All five stub components + the Separator are block-commented in
place (`/* ... */` with a restoration header) so they can be revived
intact once the underlying features ship.

---

## Phase 2 — Trade integrity
Commit: `96b6681`

### 2a. AUDIT B-002 — synchronous double-click guard on BUY/SELL
`frontend/src/components/positions/TradeTicket.tsx`

The button's `disabled={!canFire}` prop tracks `mutation.isPending`
correctly **after** React renders. Two synchronous clicks within one
frame both see `pending=false` in the closure and both dispatch a
`POST /api/zerodte/open-leg`. Result: two trades on a hammered click.

Fix: `submittingRef = useRef(false)`. Flipped synchronously inside
`fire()` **before** `mutation.mutate()` queues. The second click bails
on `submittingRef.current === true` well before React has rendered
the disabled state. Cleared on the mutation's `onSettled`. Same guard
covers both BUY and SELL.

### 2b. AUDIT B-004 — cross-tier position contamination
`frontend/src/hooks/useAccountState.ts`,
`frontend/src/pages/PositionsPage.tsx`,
`frontend/src/components/positions/TradeDeskHeader.tsx`

Three leaks closed:

(i) `useSwitchTier.onSuccess` now calls `useActivePosition.clear()`
so the activeTradeId from tier A does not survive the switch into
tier B.

(ii) `PositionsPage.activeTrade` lookup gained a tier filter:
```ts
trades.find(t => t.id === activeTradeId
                && (t.tier ?? "50K") === activeTier)
```
The chart's entry marker + BE lines stop rendering a foreign-tier
trade.

(iii) `TradeDeskHeader.MetricPills` applies the same filter to its
local `activeTrade`, **and** nulls the analytics tradeId when the
trade doesn't match. `useTradeAnalytics` disables its query and UP&L
stays at 0 — no more "100K-tier UPL surfacing on the 50K header."

Legacy trades without a `tier` field default to "50K" via `??` so
the filter doesn't drop them.

### 2c. AUDIT B-005 — invalidate account state on mutations
`frontend/src/hooks/useOpenZeroDteLeg.ts`,
`frontend/src/hooks/useOpenZeroDteStraddle.ts`,
`frontend/src/components/positions/BottomStrip.tsx`

`useAccountState` polls every 5s. Before: open/close mutations
invalidated `["journal", "trades"]` but not `["account", "state"]`,
so the header BAL/MLL/RP&L lagged up to 5 seconds after a trade
fired/closed.

All three onSuccess handlers (open-leg, open-straddle, close) now
also invalidate `["account", "state"]`. Header numbers update on
the very next tick.

---

## Phase 3 — Polish
Commit: `cb88ae5` (after this write)

### 3a. AUDIT P-001 — restyle CLOSE button to match SELL
`frontend/src/components/positions/BottomStrip.tsx:449-477`

CLOSE was pre-rework: 0 border-radius, hairline border, no fill,
h-7, bearish-outlined-only-when-enabled. Sat next to the filled
rounded BUY/SELL and looked inconsistent.

Now: `h-8`, `rounded-btn` (4px), `bg-action-sell` filled with white
text + uppercase. Hover/active hues match SELL. Disabled state sinks
into `bg-tier-1` + `text-fg-disabled`. The `tone` variable (which
recolored the realize-$ readout green/red) retired — the saturated
red fill carries the urgency without per-amount recolor.

### 3b. AUDIT P-005 — Settings footer copy
`frontend/src/pages/SettingsPage.tsx:88-94`

Replaced:

> Changes persist locally; no Save needed. Reload the page to apply
> settings that affect cold-open behavior (default ticker, timeframe).

With:

> Most settings apply immediately. Default ticker and default
> timeframe take effect on next reload.

Reflects the post-Chart-Appearance reality where bullish/bearish
color, BG gradient, and grid opacity all apply live.

### 3c. AUDIT B-007 — vol-as-OI disclosure tooltips
`frontend/src/components/positions/BottomStrip.tsx`

Free Alpaca tier doesn't expose Open Interest, so Call Wall / Put
Wall / Max Pain / Gamma Flip are computed from per-contract VOLUME.
That's documented in the code but invisible to a user. Added title
tooltips on those four rows:

- CW: "Call wall — computed from today's volume as OI proxy (free
  tier limitation)"
- PW: "Put wall — ..."
- MP: "Max pain — ..."
- GF: "Gamma flip — ..."

Applied to both the **full-strip column 3** (`LevelRow`) and the
**collapsed inline strip** (`InlineLevel`). `EM↑/EM↓` (spot × IV ×
sqrt(days)) and `IV rank` are NOT volume-derived and don't carry
the disclosure.

---

## Verification

After each phase:
- `npx tsc --noEmit` — clean.
- `uv run pytest tests/ -q` — `216 passed, 1 warning`.

Trading math (`calculations/*`, `routers/zerodte.py` entry logic),
MLL/tier math (`services/account_tiers.py`, `routers/account.py`),
and backend services were not modified in this batch.

---

## Outstanding from AUDIT.md (not in this batch)

These remain open and intentional. Listed for the record:

- **G-001/G-003** — toolbar stubs are HIDDEN, not deleted. The
  block-commented code can be revived once the underlying features
  ship.
- **G-002** — ticker search catalog is still 16 hardcoded symbols
  with the 0DTE-flag matching only `settings.zero_dte_universe`.
  Replacing the catalog with a live universe + chain-availability
  check is M-effort and deliberately deferred.
- **G-004** — live moving-BE demo recording still needs Monday
  09:31 ET market hours (or a scrubber-driven off-market take).
- **G-007 / G-008 / G-009** — tier enforcement, daily-loss-limit,
  profit targets, payout flow all remain framing/roadmap items
  rather than shipped features.
- **B-007** — `vol-as-OI` is now DISCLOSED via tooltips. The
  underlying paid-feed integration that would replace the proxy is
  not in scope here.

---

## Git log

```
$ git log --oneline -3
cb88ae5  Phase 3: Polish — CLOSE button restyle, Settings footer, vol-proxy tooltips
96b6681  Phase 2: Trade integrity — double-click guard, tier reset on switch, account state invalidation
070fb28  Phase 1: Chart honesty — drop ghost BE line, fix 1D 404, hide toolbar stubs, restrict timeframes to real backend support
```

Each commit is independently revertable; later commits do not depend
on the substance of earlier ones beyond touching the same files in a
couple places.
