import { useEffect, useRef } from "react";

import { useChainTable } from "@/hooks/useChainTable";
import { useMarketStatus } from "@/hooks/useMarket";
import { useOpenZeroDteLeg } from "@/hooks/useOpenZeroDteLeg";
import { useOpenZeroDteStraddle } from "@/hooks/useOpenZeroDteStraddle";
import { useTradeIntent } from "@/stores/tradeIntent";
import type { ChainStrikeRow } from "@/types/zerodte";

/**
 * Interactive option-chain trading ticket.
 *
 * Layout follows the convention from professional chains (thinkorswim,
 * tastytrade, TradingView):
 *
 *   CALL price │ STRIKE │ PUT price
 *
 * Three fixed-width columns centered in the panel so calls/puts hug
 * the strike they belong to instead of stretching across the full
 * panel width. ATM row is amber-highlighted and auto-scrolled into
 * view. Tight rows (~18px) match the density of a real desk chain.
 *
 * No OI columns: the free Alpaca feed doesn't ship reliable open
 * interest, and a column of "—" is dead space. If/when OI becomes
 * available it can be added compactly.
 *
 * Clicking a CALL or PUT price opens a single leg at that strike in
 * the current direction (the BUY/SELL toggle in the panel header).
 * Clicking the STRIKE itself opens an ATM straddle (when the row is
 * ATM) or a single call (off-ATM).
 *
 * Pricing: "quote" cells come from the indicative Alpaca feed; "bs"
 * cells use Black-Scholes against the ATM-implied IV — those are
 * dimmed slightly and tagged with a small "·m" marker.
 */
interface Props {
  symbol: string | null;
}

// Compact column widths so the chain reads like a desk ticket, not a
// table spread across the panel. CALL_W and PUT_W are equal so the
// strike column sits dead-center.
const CALL_W = 84;
const STRIKE_W = 64;
const PUT_W = 84;
const CHAIN_GRID = `${CALL_W}px ${STRIKE_W}px ${PUT_W}px`;
// One row of the chain table. Tighter than the previous py-0.5 so more
// strikes fit without scrolling; still legible at IBM Plex Mono 11px.
const ROW_HEIGHT = 18;

export function ChainTable({ symbol }: Props) {
  const { data, isLoading, isError, error } = useChainTable(symbol);
  const legMutation = useOpenZeroDteLeg();
  const straddleMutation = useOpenZeroDteStraddle();
  const action = useTradeIntent((s) => s.action);
  const { data: marketStatus } = useMarketStatus();
  const marketOpen = marketStatus?.status === "open";

  const containerRef = useRef<HTMLDivElement>(null);
  const atmStrike = data?.atm_strike ?? null;

  // Scroll ATM into view roughly center on first/changed render.
  useEffect(() => {
    if (!containerRef.current || atmStrike == null) return;
    const atmRow = containerRef.current.querySelector<HTMLElement>(
      `[data-strike="${atmStrike}"]`,
    );
    if (atmRow) atmRow.scrollIntoView({ block: "center", behavior: "auto" });
  }, [atmStrike, symbol]);

  if (!symbol) {
    return <EmptyState>Select a ticker to load the chain.</EmptyState>;
  }
  if (isLoading && !data) {
    return <EmptyState>Loading {symbol} chain…</EmptyState>;
  }
  if (isError) {
    const msg = (error as Error)?.message ?? "chain unavailable";
    // Specific 0DTE-missing state from the backend's strict-0DTE 409.
    // Render it as a clear panel-level message (amber, not bearish-red)
    // — this is a "today doesn't have it" condition, not a failure.
    if (msg.startsWith("No 0DTE for")) {
      return (
        <div className="flex-1 flex flex-col items-center justify-center gap-1 text-center px-4">
          <span className="text-medium text-amber tabular-nums">{msg}</span>
          <span
            className="uppercase tracking-label-up text-fg-tertiary"
            style={{ fontSize: 9, letterSpacing: "0.08em" }}
          >
            Same-day expiry not listed — try a different 0DTE-eligible symbol.
          </span>
        </div>
      );
    }
    return <EmptyState tone="bearish">{msg}</EmptyState>;
  }
  if (!data) return <EmptyState>—</EmptyState>;

  const onClickCall = (row: ChainStrikeRow) => {
    if (!marketOpen) return;
    legMutation.mutate({
      symbol: data.underlying,
      side: "call",
      action,
      strike: row.strike,
      entry_price: row.call_price,
      contracts: 1,
    });
  };
  const onClickPut = (row: ChainStrikeRow) => {
    if (!marketOpen) return;
    legMutation.mutate({
      symbol: data.underlying,
      side: "put",
      action,
      strike: row.strike,
      entry_price: row.put_price,
      contracts: 1,
    });
  };
  const onClickStrike = (row: ChainStrikeRow) => {
    if (!marketOpen) return;
    if (row.is_atm) {
      straddleMutation.mutate({ symbol: data.underlying, action });
      return;
    }
    legMutation.mutate({
      symbol: data.underlying,
      side: "call",
      action,
      strike: row.strike,
      entry_price: row.call_price,
      contracts: 1,
    });
  };

  const disabled =
    !marketOpen || legMutation.isPending || straddleMutation.isPending;

  return (
    <div className="flex flex-col h-full min-h-0">
      <ChainHeader
        symbol={data.underlying}
        expiry={data.expiry}
        spot={data.spot}
        atm={data.atm_strike}
        iv={data.iv_used}
      />
      <ColumnHeader />
      <div
        ref={containerRef}
        className="flex-1 min-h-0 overflow-y-auto bg-tier-0"
        style={{ scrollbarGutter: "stable" }}
      >
        <div className="flex flex-col items-center">
          {data.rows.map((row) => (
            <ChainRow
              key={row.strike}
              row={row}
              action={action}
              onClickCall={() => onClickCall(row)}
              onClickPut={() => onClickPut(row)}
              onClickStrike={() => onClickStrike(row)}
              disabled={disabled}
            />
          ))}
        </div>
      </div>
      {(legMutation.isError || straddleMutation.isError) && (
        <div className="px-3 py-1 border-t border-hairline bg-tier-1 text-tiny text-bearish">
          {(legMutation.error as Error)?.message ??
            (straddleMutation.error as Error)?.message ??
            "open failed"}
        </div>
      )}
    </div>
  );
}

function ChainHeader({
  symbol,
  expiry,
  spot,
  atm,
  iv,
}: {
  symbol: string;
  expiry: string;
  spot: number;
  atm: number;
  iv: number;
}) {
  return (
    <div className="flex items-center gap-4 px-3 py-1 border-b border-hairline bg-tier-1 shrink-0 tabular-nums">
      <span className="text-tiny uppercase tracking-label-up text-fg-secondary">
        Option chain
      </span>
      <span className="text-tiny text-fg-primary">{symbol}</span>
      <span className="text-tiny text-fg-tertiary">exp {expiry}</span>
      <span className="text-tiny text-fg-tertiary">spot ${spot.toFixed(2)}</span>
      <span className="text-tiny text-fg-tertiary">ATM ${atm}</span>
      <span className="text-tiny text-fg-tertiary">IV {(iv * 100).toFixed(1)}%</span>
      <span
        className="ml-auto text-tiny uppercase tracking-label-up text-fg-tertiary"
        style={{ fontSize: 9 }}
      >
        indicative pricing
      </span>
    </div>
  );
}

function ColumnHeader() {
  return (
    <div className="flex justify-center border-b border-hairline bg-tier-0 shrink-0">
      <div
        className="grid items-center text-tiny uppercase tracking-label-up text-fg-tertiary"
        style={{
          gridTemplateColumns: CHAIN_GRID,
          fontSize: 9,
          letterSpacing: "0.08em",
          height: ROW_HEIGHT,
        }}
      >
        <span className="text-right pr-2">Call</span>
        <span className="text-center">Strike</span>
        <span className="text-left pl-2">Put</span>
      </div>
    </div>
  );
}

function ChainRow({
  row,
  action,
  onClickCall,
  onClickPut,
  onClickStrike,
  disabled,
}: {
  row: ChainStrikeRow;
  action: "buy" | "sell";
  onClickCall: () => void;
  onClickPut: () => void;
  onClickStrike: () => void;
  disabled: boolean;
}) {
  const rowCls = row.is_atm
    ? "bg-tier-1 border-l-2 border-amber"
    : "border-l-2 border-transparent hover:bg-tier-1";
  return (
    <div
      data-strike={row.strike}
      className={`grid items-center text-tiny tabular-nums border-b border-hairline ${rowCls}`}
      style={{ gridTemplateColumns: CHAIN_GRID, height: ROW_HEIGHT }}
    >
      <ChainCell
        onClick={onClickCall}
        disabled={disabled || row.call_price <= 0}
        source={row.call_source}
        align="right"
        price={row.call_price}
        action={action}
        side="call"
        strike={row.strike}
      />
      <button
        type="button"
        onClick={onClickStrike}
        disabled={disabled}
        className={[
          "text-center px-1 h-full border-l border-r border-hairline",
          row.is_atm ? "text-amber font-medium" : "text-fg-primary",
          "hover:bg-tier-2 disabled:opacity-50 disabled:cursor-not-allowed",
        ].join(" ")}
        title={
          row.is_atm
            ? `${action === "buy" ? "Buy" : "Sell"} straddle at ${row.strike}`
            : `${action === "buy" ? "Long" : "Short"} call at ${row.strike}`
        }
      >
        {row.strike}
      </button>
      <ChainCell
        onClick={onClickPut}
        disabled={disabled || row.put_price <= 0}
        source={row.put_source}
        align="left"
        price={row.put_price}
        action={action}
        side="put"
        strike={row.strike}
      />
    </div>
  );
}

function ChainCell({
  onClick,
  disabled,
  source,
  align,
  price,
  action,
  side,
  strike,
}: {
  onClick: () => void;
  disabled: boolean;
  source: "quote" | "bs";
  align: "left" | "right";
  price: number;
  action: "buy" | "sell";
  side: "call" | "put";
  strike: number;
}) {
  const dim = source === "bs";
  const verb = action === "buy" ? "Long" : "Short";
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className={[
        "h-full px-2 hover:bg-tier-2 disabled:opacity-30 disabled:cursor-not-allowed tabular-nums",
        align === "right" ? "text-right" : "text-left",
        dim ? "text-fg-secondary" : "text-fg-primary",
      ].join(" ")}
      title={`${verb} ${side} at ${strike} · ${
        source === "bs" ? "BS-model price (no live quote)" : "indicative quote"
      }`}
    >
      {price.toFixed(2)}
      {source === "bs" && (
        <span className="text-fg-tertiary ml-0.5" style={{ fontSize: 8 }}>
          ·m
        </span>
      )}
    </button>
  );
}

function EmptyState({
  children,
  tone,
}: {
  children: React.ReactNode;
  tone?: "bearish";
}) {
  return (
    <div className="flex-1 flex items-center justify-center text-tiny text-fg-tertiary">
      <span className={tone === "bearish" ? "text-bearish" : ""}>{children}</span>
    </div>
  );
}
