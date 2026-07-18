import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";

import { useChainTable, useExpirations } from "@/hooks/useChainTable";
import { useZeroDteUniverse } from "@/hooks/useLiquidUniverse";
import { useMarketStatus } from "@/hooks/useMarket";
import { useOpenContractsCount } from "@/hooks/useOpenContractsCount";
import { useCancelOrder } from "@/hooks/useTrades";
import {
  cellKey,
  useWorkingOrdersByStrike,
  type WorkingOrderAtCell,
} from "@/hooks/useWorkingOrdersByStrike";
import { useTradeTicket, type TicketSelection } from "@/stores/tradeTicket";
import type { ChainStrikeRow } from "@/types/zerodte";

import { QuickOrder, type QuickOrderTarget } from "./QuickOrder";

/** Long-press threshold (ms) for opening the quick-order popover on touch. */
const LONG_PRESS_MS = 450;

/**
 * Upper-right column option chain — dense Bloomberg-style layout
 * intended to fit in a ~452px wide column. ~16 strikes visible
 * without scrolling (8 above ATM, 8 below).
 *
 * Layout: CALL price (right) | STRIKE (center) | PUT price (left).
 * ATM row: amber left-border + bg-tier-1 fill + amber values.
 *
 * Click semantics (Phase 5 — select-only, no immediate fire):
 *   - Call cell  → select call-leg at that strike in the ticket
 *   - Put cell   → select put-leg at that strike in the ticket
 *   - Strike cell on ATM row → select straddle at that strike
 *   - Strike cell off ATM → select call-leg at that strike
 *
 * The actual BUY or SELL fires from the trade ticket below the chain,
 * not from these clicks. Direction is which of the ticket's two
 * buttons the user presses.
 *
 * Read-only states (dim cells, no-op clicks):
 *   - market closed
 *   - chain query returned "No 0DTE for {symbol} today"
 */
interface Props {
  symbol: string | null;
  /** Switch the charted symbol — used by the no-0DTE empty-state chips. */
  onPickSymbol: (sym: string) => void;
}

// Topstep DOM-style ladder — two-line rows (32px: bid×ask on top, greeks +
// volume/OI below), wider center strike column anchored with a subtle
// bg-tier-1 tint, hairline every 5 rows.
const ROW_HEIGHT = 32;
const CALL_W = 168;
const STRIKE_W = 88;
const PUT_W = 168;
const GRID = `${CALL_W}px ${STRIKE_W}px ${PUT_W}px`;

/** Strike-span choices (± strikes around ATM) — feeds useChainTable. */
const SPAN_OPTIONS = [5, 10, 20] as const;

/** Above this many strikes the ladder is windowed (only on-screen rows
 *  mount). The default chain pulls ~11 rows, so day-to-day rendering is the
 *  plain path and unchanged; only wide chains (deep strike spans) virtualize. */
const VIRTUALIZE_THRESHOLD = 30;

// ── WS5: chain filtering ────────────────────────────────────────────────────
// Additive narrowing of the strike list. The chain payload carries open
// interest (the liquidity proxy we have — there's no per-row volume/IV field),
// so the "liquidity" filter is min open interest; moneyness is the ± strike
// band off ATM; "quotes only" hides BS-fallback rows (no live quote).
export interface ChainFilters {
  /** ± strikes from ATM to keep (0 = no moneyness limit). */
  band: number;
  /** Minimum open interest on either leg (0 = no minimum). */
  minOpenInterest: number;
  /** Hide rows whose BOTH sides are BS-model fallbacks (no live quote). */
  liveQuotesOnly: boolean;
}

export const DEFAULT_CHAIN_FILTERS: ChainFilters = {
  band: 0,
  minOpenInterest: 0,
  liveQuotesOnly: false,
};

/** Narrow `rows` by the active filters. The ATM row is ALWAYS kept so the
 *  ladder stays anchored and the auto-scroll target survives. Pure → testable. */
export function applyChainFilters(
  rows: ChainStrikeRow[],
  atmStrike: number,
  f: ChainFilters,
  keepStrike?: number | null,
): ChainStrikeRow[] {
  return rows.filter((r) => {
    if (r.strike === atmStrike) return true; // anchor row always survives
    // Never hide the row the user has SELECTED in the ticket, even if a tight
    // band / high min-OI would otherwise filter it out.
    if (keepStrike != null && r.strike === keepStrike) return true;
    if (f.band > 0) {
      // Count how many strike steps away this row is by index distance from
      // ATM in the (sorted) list — approximate with price distance / step.
      // Simpler + robust: keep rows within `band` strikes by rank.
      const rank = strikeRank(rows, atmStrike, r.strike);
      if (rank > f.band) return false;
    }
    if (f.minOpenInterest > 0) {
      const oi = Math.max(r.call_open_interest ?? 0, r.put_open_interest ?? 0);
      if (oi < f.minOpenInterest) return false;
    }
    if (f.liveQuotesOnly) {
      if (r.call_source === "bs" && r.put_source === "bs") return false;
    }
    return true;
  });
}

/** Index distance (in rows) between a strike and the ATM strike. */
function strikeRank(
  rows: ChainStrikeRow[],
  atmStrike: number,
  strike: number,
): number {
  const sorted = [...rows].sort((a, b) => a.strike - b.strike);
  const atmIdx = sorted.findIndex((r) => r.strike === atmStrike);
  const idx = sorted.findIndex((r) => r.strike === strike);
  if (atmIdx < 0 || idx < 0) return 0;
  return Math.abs(idx - atmIdx);
}
// ── end WS5 ─────────────────────────────────────────────────────────────────

export function RightChain({ symbol, onPickSymbol }: Props) {
  // User-selectable strike span (± strikes around ATM). ±5 keeps the ladder
  // light by default; ±10/±20 pull the deeper wings for wide-move days.
  const [span, setSpan] = useState<number>(5);
  // Multi-expiry BROWSING (audit wave 2): null = today's 0DTE (or the
  // nearest upcoming expiry on a no-0DTE day — server fallback). A later
  // expiry renders read-only: trading stays strictly 0DTE.
  const [expiry, setExpiry] = useState<string | null>(null);
  useEffect(() => setExpiry(null), [symbol]);
  const { data, isLoading, isError, error } = useChainTable(symbol, span, expiry);
  const { data: expirations } = useExpirations(symbol);
  const browseOnly = !!data && data.expiry_is_today === false;
  // ── WS5: chain filters (additive — narrows the rendered strikes; composes
  // with WS4's virtualization downstream since it only shrinks the row list).
  const [filters, setFilters] = useState<ChainFilters>(DEFAULT_CHAIN_FILTERS);
  // ── end WS5
  const setSelection = useTradeTicket((s) => s.setSelection);
  const currentSelection = useTradeTicket((s) => s.selection);
  const refreshSelectionPrice = useTradeTicket((s) => s.refreshSelectionPrice);
  const { data: marketStatus } = useMarketStatus();
  const marketOpen = marketStatus?.status === "open";

  const bodyRef = useRef<HTMLDivElement>(null);
  const { data: universe } = useZeroDteUniverse();

  const chainErrMsg = isError ? (error as Error)?.message ?? "" : "";
  const noZeroDteToday = chainErrMsg.startsWith("No 0DTE for");

  // DOM-lite overlay: resting working orders for THIS symbol, keyed by
  // strike+side, plus the existing cancel-order mutation reused inline.
  const { byCell: workingByCell } = useWorkingOrdersByStrike(
    data?.underlying ?? symbol,
  );
  const cancelOrder = useCancelOrder();

  // Scaling-cap remaining capacity for the quick-order popover — the SAME
  // sum-of-legs hook TradeTicket sizes with, so a one-click order can't
  // exceed what the server accepts.
  const { remaining: remainingCap } = useOpenContractsCount();

  // Quick-order popover target (right-click / long-press) + the row to flash
  // amber on a successful fire (keyed by strike).
  const [quickTarget, setQuickTarget] = useState<QuickOrderTarget | null>(null);
  const [flashStrike, setFlashStrike] = useState<number | null>(null);
  const flashTimer = useRef<number | null>(null);

  const flashRow = useCallback((strike: number) => {
    setFlashStrike(strike);
    if (flashTimer.current) window.clearTimeout(flashTimer.current);
    flashTimer.current = window.setTimeout(() => setFlashStrike(null), 650);
  }, []);
  useEffect(
    () => () => {
      if (flashTimer.current) window.clearTimeout(flashTimer.current);
    },
    [],
  );

  // Open the quick-order popover for a cell, anchored at the pointer. No-op
  // when there's no tradeable chain (market closed is allowed — the server
  // gates the actual fire; here we only block the empty/error states).
  const openQuick = useCallback(
    (
      row: ChainStrikeRow,
      side: "call" | "put",
      anchor: { x: number; y: number },
    ) => {
      if (!data || noZeroDteToday || browseOnly) return;
      const price = side === "call" ? row.call_price : row.put_price;
      if (price <= 0) return;
      setQuickTarget({
        symbol: data.underlying,
        side,
        strike: row.strike,
        price,
        expiry: data.expiry,
        anchor,
      });
    },
    [data, noZeroDteToday],
  );

  // With symbol-scoped placeholderData (useChainTable) `data` is already null
  // on a fresh symbol's error; guard explicitly so rows/header never render
  // from a stale or errored payload for the CURRENT symbol (also covers the
  // same-symbol refetch-error case, where stale data lingers).
  const showChain = !!data && !isError;
  const atmStrike = showChain ? data?.atm_strike ?? null : null;

  // Auto-scroll ATM row to center on symbol change.
  useEffect(() => {
    if (!bodyRef.current || atmStrike == null) return;
    const row = bodyRef.current.querySelector<HTMLElement>(
      `[data-strike="${atmStrike}"]`,
    );
    if (row) row.scrollIntoView({ block: "center", behavior: "auto" });
  }, [atmStrike, symbol]);

  // Keep the ticket's SELECTED contract priced off the live chain: each 10s
  // refetch re-syncs selection.price (identity untouched) so the Summary /
  // RiskPreview / DLL hint track the market instead of freezing at click time.
  useEffect(() => {
    if (!data || isError || !currentSelection) return;
    if (currentSelection.symbol !== data.underlying) return;
    // Browsing a different expiration must never re-price a 0DTE selection
    // off the wrong expiry's rows.
    if (currentSelection.expiry !== data.expiry) return;
    const row = data.rows.find((r) => r.strike === currentSelection.strike);
    if (!row) return;
    const next =
      currentSelection.kind === "straddle"
        ? row.call_price + row.put_price
        : (currentSelection.side ?? "call") === "put"
          ? row.put_price
          : row.call_price;
    if (next > 0) refreshSelectionPrice(next);
  }, [data, isError, currentSelection, refreshSelectionPrice]);

  // Cells are clickable to PREVIEW a contract (payoff/greeks in the detail
  // panel) whenever a chain exists — even with the market closed. Trading
  // (BUY/SELL) stays gated in the ticket; selecting is view-only.

  const onClickCall = (row: ChainStrikeRow) => {
    if (!data || noZeroDteToday || browseOnly) return;
    setSelection({
      kind: "leg",
      side: "call",
      symbol: data.underlying,
      strike: row.strike,
      price: row.call_price,
      expiry: data.expiry,
    });
  };
  const onClickPut = (row: ChainStrikeRow) => {
    if (!data || noZeroDteToday || browseOnly) return;
    setSelection({
      kind: "leg",
      side: "put",
      symbol: data.underlying,
      strike: row.strike,
      price: row.put_price,
      expiry: data.expiry,
    });
  };
  const onClickStrike = (row: ChainStrikeRow) => {
    if (!data || noZeroDteToday || browseOnly) return;
    if (row.is_atm) {
      setSelection({
        kind: "straddle",
        symbol: data.underlying,
        strike: row.strike,
        // Straddle "price" = call + put premium (debit if long).
        price: row.call_price + row.put_price,
        expiry: data.expiry,
      });
      return;
    }
    setSelection({
      kind: "leg",
      side: "call",
      symbol: data.underlying,
      strike: row.strike,
      price: row.call_price,
      expiry: data.expiry,
    });
  };

  // ── WS5: apply chain filters to the rows (moneyness band / min open
  // interest / live-quotes-only). Pure narrowing — keeps the ATM row so the
  // ladder stays anchored — so it composes with the virtualization below.
  const filteredRows = useMemo(
    () =>
      data
        ? applyChainFilters(data.rows, data.atm_strike, filters, currentSelection?.strike ?? null)
        : [],
    [data, filters, currentSelection?.strike],
  );
  const filteredOut = (data?.rows.length ?? 0) - filteredRows.length;
  // ── end WS5

  return (
    <section className="flex flex-col bg-tier-0">
      <Header
        symbol={data?.underlying ?? symbol ?? "—"}
        expiry={showChain ? data?.expiry ?? null : null}
        spot={showChain ? data?.spot ?? null : null}
        atm={showChain ? data?.atm_strike ?? null : null}
        iv={showChain ? data?.iv_used ?? null : null}
        asOf={showChain ? data?.as_of ?? null : null}
        expirations={expirations?.expirations ?? []}
        onSelectExpiry={(iso, isToday) => setExpiry(isToday ? null : iso)}
      />
      {browseOnly && showChain && (
        <div
          className="px-3 py-1 border-b border-hairline bg-tier-1 text-position text-center shrink-0"
          style={{ fontSize: 12 }}
          role="status"
        >
          Browsing exp {data?.expiry} — viewing only; trading is strictly 0DTE
        </div>
      )}
      <ColumnHeader />
      {/* ── WS5: filter bar — additive; narrows the rendered strikes. ── */}
      {showChain && (
        <ChainFilterBar
          filters={filters}
          onChange={setFilters}
          span={span}
          onSpanChange={setSpan}
          filteredOut={filteredOut}
          total={data?.rows.length ?? 0}
        />
      )}
      {/* ── end WS5 ── */}
      {!marketOpen && showChain && (
        <div
          className="px-3 py-1 border-b border-hairline bg-tier-1 text-warning text-center shrink-0"
          style={{ fontSize: 12 }}
          role="status"
        >
          Market closed — indicative pricing; tap a contract to preview, trading resumes next session
        </div>
      )}
      <div
        ref={bodyRef}
        className="overflow-y-auto"
        // Flex to the viewport instead of a hard cap: tall screens get a
        // deeper ladder (the ±10/±20 spans are actually scannable) while the
        // 360px floor keeps the ticket + detail panel usable below.
        style={{
          scrollbarGutter: "stable",
          maxHeight: "max(360px, calc(100vh - 560px))",
        }}
      >
        {!symbol && <EmptyMessage>Pick a ticker in the header.</EmptyMessage>}
        {symbol && isLoading && !data && (
          <EmptyMessage>Loading {symbol} chain…</EmptyMessage>
        )}
        {noZeroDteToday && (
          <NoZeroDteEmpty
            symbol={symbol}
            options={(universe?.symbols ?? []).filter((s) => s !== symbol)}
            loadingOptions={!universe}
            onPick={onPickSymbol}
          />
        )}
        {isError && !noZeroDteToday && (
          <EmptyMessage tone="bearish">{chainErrMsg}</EmptyMessage>
        )}
        {showChain && data && data.rows.length > 0 && filteredRows.length === 0 && (
          <EmptyMessage tone="warning">
            No strikes match the filter — widen the band or lower the min OI.
          </EmptyMessage>
        )}
        {showChain && data && filteredRows.length > 0 && (
          <ChainRows
            rows={filteredRows}
            underlying={data.underlying}
            atmStrike={data.atm_strike ?? null}
            selection={currentSelection}
            disabled={noZeroDteToday}
            flashStrike={flashStrike}
            workingByCell={workingByCell}
            cancelOrder={(id) => cancelOrder.mutate(id)}
            cancelling={cancelOrder.isPending}
            onQuickOrder={openQuick}
            onClickCall={onClickCall}
            onClickPut={onClickPut}
            onClickStrike={onClickStrike}
            scrollParentRef={bodyRef}
            scrollKey={symbol}
          />
        )}
      </div>
      {quickTarget && (
        <QuickOrder
          target={quickTarget}
          maxContracts={remainingCap}
          onClose={() => setQuickTarget(null)}
          onFired={() => flashRow(quickTarget.strike)}
        />
      )}
    </section>
  );
}

/** Per-row selection flags, shared by the plain and virtual render paths so
 *  the two stay byte-identical in behavior. */
function rowSelection(
  row: ChainStrikeRow,
  underlying: string,
  selection: TicketSelection | null,
): { selectedCall: boolean; selectedPut: boolean } {
  const selStrike =
    selection?.symbol === underlying ? selection.strike : null;
  const selKind = selection?.kind ?? null;
  const selSide = selection?.side ?? null;
  const atStrike = selStrike === row.strike;
  return {
    selectedCall:
      atStrike &&
      (selKind === "straddle" || (selKind === "leg" && selSide === "call")),
    selectedPut:
      atStrike &&
      (selKind === "straddle" || (selKind === "leg" && selSide === "put")),
  };
}

interface ChainRowsProps {
  rows: ChainStrikeRow[];
  underlying: string;
  atmStrike: number | null;
  selection: TicketSelection | null;
  disabled: boolean;
  flashStrike: number | null;
  workingByCell: Map<string, WorkingOrderAtCell[]>;
  cancelOrder: (id: number) => void;
  cancelling: boolean;
  onQuickOrder: (
    row: ChainStrikeRow,
    side: "call" | "put",
    anchor: { x: number; y: number },
  ) => void;
  onClickCall: (row: ChainStrikeRow) => void;
  onClickPut: (row: ChainStrikeRow) => void;
  onClickStrike: (row: ChainStrikeRow) => void;
  scrollParentRef: React.RefObject<HTMLDivElement>;
  /** Re-center the ATM row when the charted symbol changes (virtual path). */
  scrollKey: string | null;
}

/**
 * Strike-ladder body. Short chains (the common ~11-row case) render plainly —
 * markup and the parent's data-strike ATM auto-scroll are unchanged. Wide
 * chains (> VIRTUALIZE_THRESHOLD strikes) window the rows: only the visible
 * span mounts, fixed ROW_HEIGHT so no measurement is needed, and the ATM row
 * is centered via scrollToIndex (the data-strike querySelector the parent uses
 * can't find an unmounted row). Click-to-select, quick-order popovers, and the
 * working-order overlay badges are identical across both paths.
 */
function ChainRows(props: ChainRowsProps) {
  const {
    rows,
    underlying,
    atmStrike,
    selection,
    disabled,
    flashStrike,
    workingByCell,
    cancelOrder,
    cancelling,
    onQuickOrder,
    onClickCall,
    onClickPut,
    onClickStrike,
    scrollParentRef,
    scrollKey,
  } = props;

  const virtualize = rows.length > VIRTUALIZE_THRESHOLD;

  const virtualizer = useVirtualizer({
    count: rows.length,
    getScrollElement: () => scrollParentRef.current,
    estimateSize: () => ROW_HEIGHT,
    overscan: 10,
    enabled: virtualize,
    getItemKey: (index) => rows[index].strike,
  });

  // Virtual path: center the ATM row on symbol change. The parent's
  // data-strike scrollIntoView no-ops here because the row may be unmounted,
  // so drive the scroll through the virtualizer instead.
  useEffect(() => {
    if (!virtualize || atmStrike == null) return;
    const idx = rows.findIndex((r) => r.strike === atmStrike);
    if (idx >= 0) virtualizer.scrollToIndex(idx, { align: "center" });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [virtualize, atmStrike, scrollKey]);

  const renderRow = (row: ChainStrikeRow, idx: number) => {
    const { selectedCall, selectedPut } = rowSelection(
      row,
      underlying,
      selection,
    );
    return (
      <Row
        key={row.strike}
        row={row}
        disabled={disabled}
        selectedCall={selectedCall}
        selectedPut={selectedPut}
        showBottomRule={(idx + 1) % 5 === 0}
        flashing={flashStrike === row.strike}
        callOrders={workingByCell.get(cellKey(row.strike, "call"))}
        putOrders={workingByCell.get(cellKey(row.strike, "put"))}
        cancelOrder={cancelOrder}
        cancelling={cancelling}
        onQuickOrder={onQuickOrder}
        onClickCall={() => onClickCall(row)}
        onClickPut={() => onClickPut(row)}
        onClickStrike={() => onClickStrike(row)}
      />
    );
  };

  if (!virtualize) {
    return (
      <div className="flex flex-col items-center">
        {rows.map((row, idx) => renderRow(row, idx))}
      </div>
    );
  }

  // Windowed: a spacer div holds the full ladder height; visible rows are
  // absolutely positioned at their virtual offset. Centered horizontally to
  // match the plain path's items-center layout.
  const items = virtualizer.getVirtualItems();
  return (
    <div
      style={{ height: virtualizer.getTotalSize(), position: "relative" }}
    >
      {items.map((vi) => (
        <div
          key={vi.key}
          style={{
            position: "absolute",
            top: 0,
            left: "50%",
            transform: `translate(-50%, ${vi.start}px)`,
          }}
        >
          {renderRow(rows[vi.index], vi.index)}
        </div>
      ))}
    </div>
  );
}

// ── WS5: filter bar UI ──────────────────────────────────────────────────────
function ChainFilterBar({
  filters,
  onChange,
  span,
  onSpanChange,
  filteredOut,
  total,
}: {
  filters: ChainFilters;
  onChange: (f: ChainFilters) => void;
  /** ± strikes around ATM actually FETCHED (useChainTable's strikes param). */
  span: number;
  onSpanChange: (s: number) => void;
  filteredOut: number;
  total: number;
}) {
  const bands = [0, 3, 5, 8];
  const ois = [0, 100, 500, 1000];
  return (
    <div className="flex items-center flex-wrap gap-2 px-3 py-1 border-b border-hairline bg-tier-1 shrink-0">
      <span
        className="uppercase tracking-label-up text-fg-tertiary-2"
        style={{ fontSize: 10 }}
      >
        filter
      </span>
      {/* Strike span — how deep the fetched ladder goes (vs. the ±band
          filter below, which only narrows what's already fetched). */}
      <label className="flex items-center gap-1" style={{ fontSize: 10 }}>
        <span className="uppercase tracking-label-up text-fg-tertiary-2">±span</span>
        <select
          value={span}
          onChange={(e) => onSpanChange(parseInt(e.target.value, 10))}
          aria-label="Strike span (strikes fetched around ATM)"
          className="bg-tier-2 border border-tier-3 rounded-btn text-fg-primary px-1 tabular-nums"
          style={{ height: 20, fontSize: 11 }}
        >
          {SPAN_OPTIONS.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
      </label>
      {/* Moneyness band */}
      <label className="flex items-center gap-1" style={{ fontSize: 10 }}>
        <span className="uppercase tracking-label-up text-fg-tertiary-2">±band</span>
        <select
          value={filters.band}
          onChange={(e) => onChange({ ...filters, band: parseInt(e.target.value, 10) })}
          aria-label="Moneyness band (strikes from ATM)"
          className="bg-tier-2 border border-tier-3 rounded-btn text-fg-primary px-1 tabular-nums"
          style={{ height: 20, fontSize: 11 }}
        >
          {bands.map((b) => (
            <option key={b} value={b}>
              {b === 0 ? "all" : b}
            </option>
          ))}
        </select>
      </label>
      {/* Min open interest (liquidity proxy) */}
      <label className="flex items-center gap-1" style={{ fontSize: 10 }}>
        <span className="uppercase tracking-label-up text-fg-tertiary-2">min OI</span>
        <select
          value={filters.minOpenInterest}
          onChange={(e) =>
            onChange({ ...filters, minOpenInterest: parseInt(e.target.value, 10) })
          }
          aria-label="Minimum open interest"
          className="bg-tier-2 border border-tier-3 rounded-btn text-fg-primary px-1 tabular-nums"
          style={{ height: 20, fontSize: 11 }}
        >
          {ois.map((o) => (
            <option key={o} value={o}>
              {o === 0 ? "any" : o}
            </option>
          ))}
        </select>
      </label>
      {/* Live-quotes-only toggle */}
      <button
        type="button"
        onClick={() => onChange({ ...filters, liveQuotesOnly: !filters.liveQuotesOnly })}
        aria-pressed={filters.liveQuotesOnly}
        className={[
          "uppercase tracking-label-up rounded-btn px-2 transition-colors duration-100 select-none",
          filters.liveQuotesOnly
            ? "bg-tier-3 border border-amber text-amber"
            : "bg-tier-2 border border-tier-3 text-fg-secondary hover:bg-tier-3",
        ].join(" ")}
        style={{ height: 20, fontSize: 10 }}
        title="Hide strikes priced only by the BS model (no live quote on either side)"
      >
        quotes only
      </button>
      {filteredOut > 0 && (
        <span className="text-fg-tertiary-2 ml-auto tabular-nums" style={{ fontSize: 10 }}>
          {total - filteredOut}/{total}
        </span>
      )}
    </div>
  );
}
// ── end WS5 ─────────────────────────────────────────────────────────────────

function Header({
  symbol,
  expiry,
  spot,
  atm,
  iv,
  asOf,
  expirations = [],
  onSelectExpiry,
}: {
  symbol: string;
  expiry: string | null;
  spot: number | null;
  atm: number | null;
  iv: number | null;
  /** Quote timestamp (ISO) — when the chain's prices were sourced. */
  asOf: string | null;
  /** Listed expirations for the browser dropdown (≤1 → static label). */
  expirations?: { expiry: string; dte: number; is_today: boolean }[];
  onSelectExpiry?: (iso: string, isToday: boolean) => void;
}) {
  const asOfLabel = asOf ? formatClockEtSeconds(asOf) : null;
  const expiryLabel = (e: { expiry: string; dte: number; is_today: boolean }) =>
    e.is_today ? `today · 0DTE` : `${e.expiry} · ${e.dte}DTE`;
  return (
    <div className="border-b border-hairline bg-tier-1 shrink-0">
      <div className="flex items-baseline gap-2 px-3 pt-1.5 tabular-nums">
        <span className="text-tiny uppercase tracking-label-up text-fg-secondary">
          Option chain
        </span>
        <span className="text-tiny text-fg-primary">{symbol}</span>
        {expirations.length > 1 && onSelectExpiry ? (
          <select
            value={expiry ?? ""}
            onChange={(e) => {
              const hit = expirations.find((x) => x.expiry === e.target.value);
              if (hit) onSelectExpiry(hit.expiry, hit.is_today);
            }}
            aria-label="Expiration to browse (trading is 0DTE-only)"
            title="Browse any listed expiration. Only today's 0DTE is tradeable — later expiries are view-only."
            className="text-tiny bg-tier-2 border border-tier-3 text-fg-secondary rounded-btn px-1"
            style={{ height: 18, fontSize: 11 }}
          >
            {expirations.map((e) => (
              <option key={e.expiry} value={e.expiry}>
                {expiryLabel(e)}
              </option>
            ))}
          </select>
        ) : (
          <span className="text-tiny text-fg-tertiary-2">
            0DTE · exp {expiry ?? "today"}
          </span>
        )}
        <span
          className="ml-auto text-fg-tertiary-2"
          style={{ fontSize: 12 }}
          title={asOfLabel ? `Quotes sourced ${asOfLabel} ET` : undefined}
        >
          {asOfLabel ? `quotes ${asOfLabel} · ` : ""}indicative pricing
        </span>
      </div>
      <div className="flex items-baseline gap-3 px-3 pb-1 tabular-nums">
        <SubItem label="spot" value={spot != null ? `$${spot.toFixed(2)}` : "—"} />
        <SubItem label="ATM" value={atm != null ? `$${atm}` : "—"} />
        <SubItem
          label="IV"
          value={iv != null ? `${(iv * 100).toFixed(1)}%` : "—"}
        />
      </div>
    </div>
  );
}

function SubItem({ label, value }: { label: string; value: string }) {
  return (
    <span className="text-tiny tabular-nums">
      <span className="text-fg-tertiary-2 uppercase mr-1" style={{ fontSize: 11 }}>
        {label}
      </span>
      <span className="text-fg-secondary">{value}</span>
    </span>
  );
}

function ColumnHeader() {
  return (
    <div className="flex justify-center border-b border-hairline-strong bg-tier-1 shrink-0">
      <div
        className="grid items-center text-tiny uppercase tracking-label-up text-fg-tertiary-2"
        style={{
          gridTemplateColumns: GRID,
          fontSize: 11,
          letterSpacing: "0.08em",
          height: 20,
        }}
      >
        <span className="text-right pr-3">Call bid×ask</span>
        <span className="text-center">Strike</span>
        <span className="text-left pl-3">Put bid×ask</span>
      </div>
    </div>
  );
}

function Row({
  row,
  disabled,
  selectedCall,
  selectedPut,
  showBottomRule,
  flashing,
  callOrders,
  putOrders,
  cancelOrder,
  cancelling,
  onQuickOrder,
  onClickCall,
  onClickPut,
  onClickStrike,
}: {
  row: ChainStrikeRow;
  disabled: boolean;
  selectedCall: boolean;
  selectedPut: boolean;
  /** Hairline divider below this row — only every 5th, for ladder grouping. */
  showBottomRule: boolean;
  /** Brief amber wash after a successful one-click order on this strike. */
  flashing: boolean;
  /** Resting working orders on the call / put cell (overlay badges). */
  callOrders?: WorkingOrderAtCell[];
  putOrders?: WorkingOrderAtCell[];
  cancelOrder: (id: number) => void;
  cancelling: boolean;
  /** Open the quick-order popover for a cell, anchored at the pointer. */
  onQuickOrder: (
    row: ChainStrikeRow,
    side: "call" | "put",
    anchor: { x: number; y: number },
  ) => void;
  onClickCall: () => void;
  onClickPut: () => void;
  onClickStrike: () => void;
}) {
  // ATM row: 4px amber left rule + bg-tier-2 across, amber values
  // (visible even in disabled state).
  // Selected row (any cell): persistent bg-tier-3 + 2px amber outline.
  // Default row: 4px transparent left rule + bg-tier-3 fill on hover.
  const anySelected = selectedCall || selectedPut;
  const baseClass = anySelected
    ? "bg-tier-3 border-l-[4px] border-amber relative ring-1 ring-amber"
    : row.is_atm
      ? "bg-tier-2 border-l-[4px] border-amber"
      : "border-l-[4px] border-transparent hover:bg-tier-3";
  const bottomBorder = showBottomRule ? "border-b border-hairline" : "";
  return (
    <div
      data-strike={row.strike}
      className={`grid items-center tabular-nums ${baseClass} ${bottomBorder}${
        flashing ? " td-quick-flash" : ""
      }`}
      style={{
        gridTemplateColumns: GRID,
        height: ROW_HEIGHT,
      }}
    >
      <Cell
        align="right"
        price={row.call_price}
        source={row.call_source}
        bid={row.call_bid ?? null}
        ask={row.call_ask ?? null}
        volume={row.call_volume ?? null}
        openInterest={row.call_open_interest}
        delta={row.call_delta}
        theta={row.call_theta}
        iv={row.call_iv ?? null}
        disabled={disabled || row.call_price <= 0}
        side="call"
        strike={row.strike}
        isAtm={row.is_atm}
        selected={selectedCall}
        orders={callOrders}
        cancelOrder={cancelOrder}
        cancelling={cancelling}
        onClick={onClickCall}
        onQuickOrder={(anchor) => onQuickOrder(row, "call", anchor)}
      />
      <button
        type="button"
        onClick={onClickStrike}
        disabled={disabled}
        className={[
          "text-center px-1 h-full tabular-nums",
          // Subtle bg tint on the strike column to anchor the ladder
          // center. ATM/selected rows already have their own fills;
          // the column tint only shows on the default rows.
          anySelected || row.is_atm ? "" : "bg-tier-1",
          row.is_atm ? "text-amber font-medium" : "text-fg-primary",
          disabled
            ? row.is_atm
              ? "text-amber cursor-not-allowed"
              : "text-fg-disabled cursor-not-allowed"
            : "hover:text-amber",
        ].join(" ")}
        style={{ fontSize: 13, fontWeight: row.is_atm ? 500 : 400 }}
        title={
          disabled
            ? "Market closed or no 0DTE today"
            : row.is_atm
              ? `Select straddle at ${row.strike}`
              : `Select call at ${row.strike}`
        }
      >
        {row.strike}
      </button>
      <Cell
        align="left"
        price={row.put_price}
        source={row.put_source}
        bid={row.put_bid ?? null}
        ask={row.put_ask ?? null}
        volume={row.put_volume ?? null}
        openInterest={row.put_open_interest}
        delta={row.put_delta}
        theta={row.put_theta}
        iv={row.put_iv ?? null}
        disabled={disabled || row.put_price <= 0}
        side="put"
        strike={row.strike}
        isAtm={row.is_atm}
        selected={selectedPut}
        orders={putOrders}
        cancelOrder={cancelOrder}
        cancelling={cancelling}
        onClick={onClickPut}
        onQuickOrder={(anchor) => onQuickOrder(row, "put", anchor)}
      />
    </div>
  );
}

function Cell({
  align,
  price,
  source,
  bid,
  ask,
  volume,
  openInterest,
  delta,
  theta,
  iv,
  disabled,
  side,
  strike,
  isAtm,
  selected,
  orders,
  cancelOrder,
  cancelling,
  onClick,
  onQuickOrder,
}: {
  align: "left" | "right";
  price: number;
  source: "quote" | "bs";
  /** Per-side NBBO — null until the backend sends quotes (then bid×ask is
   *  the primary cell content; the mid/model price is the fallback). */
  bid: number | null;
  ask: number | null;
  volume: number | null;
  openInterest: number | null;
  delta: number;
  theta: number;
  /** Per-contract IV back-solved from the quote mid — null on model rows. */
  iv: number | null;
  disabled: boolean;
  side: "call" | "put";
  strike: number;
  isAtm: boolean;
  selected: boolean;
  /** Resting working orders on this cell (overlay badge + inline cancel). */
  orders?: WorkingOrderAtCell[];
  cancelOrder: (id: number) => void;
  cancelling: boolean;
  onClick: () => void;
  /** Right-click / long-press → quick-order popover, anchored at the pointer. */
  onQuickOrder: (anchor: { x: number; y: number }) => void;
}) {
  // Long-press (touch) → quick order. A timer armed on touchstart fires the
  // popover unless the finger lifts/moves first; we also suppress the
  // synthetic click that follows so a long-press never also selects the cell.
  const pressTimer = useRef<number | null>(null);
  const longFired = useRef(false);
  const clearPress = () => {
    if (pressTimer.current) {
      window.clearTimeout(pressTimer.current);
      pressTimer.current = null;
    }
  };
  const dim = source === "bs";
  // ATM row keeps its amber values even in disabled state (the row
  // identity should remain visible while market is closed).
  const baseColor = disabled
    ? isAtm
      ? "text-amber cursor-not-allowed"
      : "text-fg-disabled cursor-not-allowed"
    : selected
      ? "text-amber"
      : isAtm
        ? "text-amber"
        : dim
          ? "text-fg-tertiary-2"
          : "text-fg-primary";
  // On 0DTE the SPREAD is the trade: bid×ask is the primary line whenever
  // both sides quote. Without quotes the mid/model price falls back, marked
  // ·mid (quote-derived mid) or ·m (BS model) so a synthetic number is never
  // mistaken for a market. Line 2 carries the secondary read: Δ/Θ + session
  // volume + OI, all display-only values the backend already returns.
  const hasQuote = bid != null && ask != null;
  const priceEl = hasQuote ? (
    <span className="whitespace-nowrap">
      {bid.toFixed(2)}
      <span className="text-fg-tertiary" aria-hidden>
        ×
      </span>
      {ask.toFixed(2)}
    </span>
  ) : (
    <span className="whitespace-nowrap">
      {price.toFixed(2)}
      <span
        className="text-fg-tertiary ml-0.5"
        style={{ fontSize: 11 }}
        aria-hidden
      >
        {source === "bs" ? "·m" : "·mid"}
      </span>
    </span>
  );
  const volOiEl = (volume != null || openInterest != null) && (
    <span className="whitespace-nowrap">
      {volume != null ? `V ${fmtCount(volume)}` : ""}
      {volume != null && openInterest != null ? " · " : ""}
      {openInterest != null ? `OI ${fmtCount(openInterest)}` : ""}
    </span>
  );
  const subEl = (
    <span
      className={`flex gap-1.5 whitespace-nowrap overflow-hidden ${
        disabled ? "text-fg-disabled" : "text-fg-tertiary-2"
      } ${align === "right" ? "justify-end" : "justify-start"}`}
      style={{ fontSize: 10, fontWeight: 400 }}
    >
      <span className="whitespace-nowrap">
        Δ{delta.toFixed(2)} Θ{theta.toFixed(2)}
        {iv != null && (
          <span title="Per-contract implied vol from the quote mid — watch it move across strikes (skew) and vs the header ATM IV">
            {" "}
            IV{Math.round(iv * 100)}
          </span>
        )}
      </span>
      {volOiEl}
    </span>
  );
  const badge = orders && orders.length > 0 && (
    <WorkingBadge
      key="badge"
      orders={orders}
      cancelOrder={cancelOrder}
      cancelling={cancelling}
    />
  );
  // a11y (WS6): the cell is already a <button> (Enter/Space select it
  // natively), but a screen reader hears only the bare numbers without a
  // label. Spell out side + strike + action, mark the selected cell with
  // aria-pressed, and add a keyboard path to the quick-order popover (the
  // mouse-only right-click / long-press is otherwise unreachable): Shift+Enter
  // or the ContextMenu key opens it, anchored at the cell's center.
  const actionLabel = disabled
    ? `${side} ${strike} — unavailable (market closed or no 0DTE today)`
    : `Select ${side} option at strike ${strike}, ${
        hasQuote
          ? `bid ${bid.toFixed(2)} ask ${ask.toFixed(2)}`
          : `premium ${price.toFixed(2)}`
      }. Shift+Enter for a quick order.`;
  const cellRef = useRef<HTMLButtonElement>(null);
  const openQuickFromKeyboard = () => {
    if (disabled) return;
    const r = cellRef.current?.getBoundingClientRect();
    onQuickOrder({
      x: r ? r.left + r.width / 2 : 0,
      y: r ? r.top + r.height / 2 : 0,
    });
  };
  const cellButton = (
    <button
        key="cell"
        ref={cellRef}
        type="button"
        aria-label={actionLabel}
        aria-pressed={selected}
        onClick={() => {
          // Swallow the click synthesized right after a long-press.
          if (longFired.current) {
            longFired.current = false;
            return;
          }
          onClick();
        }}
        onKeyDown={(e) => {
          // Keyboard equivalent of right-click → quick order.
          if (e.key === "ContextMenu" || (e.key === "Enter" && e.shiftKey)) {
            e.preventDefault();
            openQuickFromKeyboard();
          }
        }}
        onContextMenu={(e) => {
          if (disabled) return;
          e.preventDefault();
          onQuickOrder({ x: e.clientX, y: e.clientY });
        }}
        onTouchStart={(e) => {
          if (disabled) return;
          longFired.current = false;
          const t = e.touches[0];
          const x = t?.clientX ?? 0;
          const y = t?.clientY ?? 0;
          clearPress();
          pressTimer.current = window.setTimeout(() => {
            longFired.current = true;
            onQuickOrder({ x, y });
          }, LONG_PRESS_MS);
        }}
        onTouchEnd={clearPress}
        onTouchMove={clearPress}
        onTouchCancel={clearPress}
        disabled={disabled}
        className={[
          "h-full px-2 tabular-nums font-medium flex flex-col justify-center leading-tight min-w-0",
          align === "right" ? "items-end" : "items-start",
          baseColor,
          disabled ? "" : "hover:text-amber",
        ].join(" ")}
        style={{ fontSize: 12, fontWeight: 500 }}
        title={
          disabled
            ? "Market closed or no 0DTE today"
            : `Select ${side} at ${strike} · ${
                hasQuote
                  ? `bid ${bid.toFixed(2)} × ask ${ask.toFixed(2)} · mid ${price.toFixed(2)}`
                  : source === "bs"
                    ? `BS-model price ${price.toFixed(2)} (no live quote)`
                    : `indicative mid ${price.toFixed(2)} (no live quote)`
              } · Δ ${delta.toFixed(2)} · Θ ${theta.toFixed(2)}/day · vol ${
                volume != null ? fmtCount(volume) : "—"
              } · OI ${
                openInterest != null ? fmtCount(openInterest) : "—"
              } · right-click to quick-order`
        }
      >
        {priceEl}
        {subEl}
      </button>
  );
  // Badge sits OUTBOARD of the price (away from the strike column): left of
  // the price on the call side, right of it on the put side.
  return (
    <div
      className={[
        "h-full flex items-center gap-1",
        align === "right" ? "justify-end" : "justify-start",
      ].join(" ")}
    >
      {align === "right" ? [badge, cellButton] : [cellButton, badge]}
    </div>
  );
}

/**
 * Resting-order overlay badge — qty + trigger price of the working order(s)
 * on a call/put cell, with an inline cancel "×" that calls the existing
 * cancel-order mutation. When multiple orders stack on one cell the qty is
 * summed and the cancel hits the most recent; the title lists each.
 */
function WorkingBadge({
  orders,
  cancelOrder,
  cancelling,
}: {
  orders: WorkingOrderAtCell[];
  cancelOrder: (id: number) => void;
  cancelling: boolean;
}) {
  const totalQty = orders.reduce((s, o) => s + o.contracts, 0);
  // Show the first order's trigger; the title spells out each when stacked.
  const first = orders[0];
  const trig = first.trigger;
  const label = trig != null ? `${totalQty}@${trig.toFixed(2)}` : `${totalQty}`;
  const detail = orders
    .map(
      (o) =>
        `${o.action} ${o.contracts} ${o.orderType}${
          o.trigger != null ? ` @ $${o.trigger.toFixed(2)}` : ""
        }`,
    )
    .join(" · ");
  return (
    <span
      className="inline-flex items-center gap-0.5 border border-amber text-amber rounded-hair leading-none shrink-0"
      style={{ fontSize: 10, paddingInline: 2, paddingBlock: 1 }}
      title={`Resting: ${detail} — awaiting fill`}
    >
      <span
        className="inline-block rounded-full bg-amber animate-pulse"
        style={{ width: 4, height: 4 }}
        aria-hidden
      />
      <span className="tabular-nums uppercase tracking-label-up">{label}</span>
      <button
        type="button"
        onClick={(e) => {
          e.stopPropagation();
          // Cancel the most recently placed order on this cell.
          cancelOrder(orders[orders.length - 1].trade.id);
        }}
        disabled={cancelling}
        aria-label={`Cancel ${totalQty > 1 ? "an " : ""}order at this strike`}
        className="text-amber hover:text-bearish disabled:opacity-50 leading-none"
        style={{ fontSize: 12 }}
      >
        ×
      </button>
    </span>
  );
}

/** Compact count for volume/OI — 12345 → "12.3k". */
function fmtCount(v: number): string {
  if (!Number.isFinite(v)) return "—";
  if (Math.abs(v) >= 1000) return `${(v / 1000).toFixed(1)}k`;
  return `${Math.round(v)}`;
}

/** HH:MM:SS in ET — the quotes stamp in the chain header. */
function formatClockEtSeconds(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso.slice(11, 19);
  try {
    return d.toLocaleTimeString("en-US", {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hour12: false,
      timeZone: "America/New_York",
    });
  } catch {
    return iso.slice(11, 19);
  }
}

function EmptyMessage({
  children,
  tone,
}: {
  children: React.ReactNode;
  tone?: "warning" | "bearish";
}) {
  const cls =
    tone === "bearish"
      ? "text-bearish"
      : tone === "warning"
        ? "text-warning"
        : "text-fg-tertiary";
  return (
    <div className={`flex-1 flex items-center justify-center text-tiny ${cls} px-4 py-6 text-center`}>
      {children}
    </div>
  );
}

/**
 * Strict-0DTE empty state. Instead of a dead "Loading…" spinner (or a raw
 * 409 echo), tell the user this symbol has no same-day expiry and give them
 * one-click chips to switch the chart to a tradeable 0DTE symbol. Works even
 * while holding a position — PositionsPage no longer re-locks the symbol.
 */
function NoZeroDteEmpty({
  symbol,
  options,
  loadingOptions,
  onPick,
}: {
  symbol: string | null;
  options: string[];
  loadingOptions: boolean;
  onPick: (sym: string) => void;
}) {
  return (
    <EmptyMessage tone="warning">
      <div className="flex flex-col items-center gap-2">
        <span>No 0DTE expiry for {symbol ?? "—"} today.</span>
        {options.length > 0 ? (
          <>
            <span className="text-fg-tertiary-2" style={{ fontSize: 11 }}>
              Trade a same-day-expiry symbol:
            </span>
            <div className="flex flex-wrap items-center justify-center gap-1.5">
              {options.map((sym) => (
                <button
                  key={sym}
                  type="button"
                  onClick={() => onPick(sym)}
                  className="inline-flex items-center border border-amber text-amber px-2 py-0.5 uppercase tracking-label-up rounded-btn hover:bg-tier-2"
                  style={{ fontSize: 12 }}
                  title={`Switch chart to ${sym}`}
                >
                  {sym}
                </button>
              ))}
            </div>
          </>
        ) : (
          !loadingOptions && (
            <span className="text-fg-tertiary-2" style={{ fontSize: 11 }}>
              No 0DTE-eligible symbols available right now.
            </span>
          )
        )}
      </div>
    </EmptyMessage>
  );
}
