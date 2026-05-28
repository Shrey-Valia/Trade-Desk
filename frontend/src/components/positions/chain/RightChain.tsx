import { useEffect, useRef } from "react";

import { useChainTable } from "@/hooks/useChainTable";
import { useMarketStatus } from "@/hooks/useMarket";
import { useOpenZeroDteLeg } from "@/hooks/useOpenZeroDteLeg";
import { useOpenZeroDteStraddle } from "@/hooks/useOpenZeroDteStraddle";
import { useTradeIntent } from "@/stores/tradeIntent";
import { useUserSettings } from "@/stores/userSettings";
import type { ChainStrikeRow } from "@/types/zerodte";

/**
 * Upper-right column option chain — dense Bloomberg-style layout
 * intended to fit in a ~452px wide column. ~16 strikes visible
 * without scrolling (8 above ATM, 8 below).
 *
 * Layout: CALL price (right) | STRIKE (center) | PUT price (left).
 * ATM row: amber left-border + bg-tier-1 fill + amber values.
 *
 * Click semantics (preserved from the legacy bottom-panel ChainPanel):
 *   - Call cell  → open one-leg call at that strike (current action)
 *   - Put cell   → open one-leg put at that strike
 *   - Strike cell on ATM row → open straddle
 *   - Strike cell off ATM → open one-leg call
 *
 * Phase 4 keeps the legacy click-to-trade behavior. Phase 5 will
 * intercept these clicks via a tradeTicket store so the action flows
 * through the new BUY/SELL ticket below the chain instead of firing
 * mutations directly.
 *
 * Read-only states (dim cells, no-op clicks):
 *   - market closed
 *   - chain query returned "No 0DTE for {symbol} today"
 */
interface Props {
  symbol: string | null;
}

// 16 strike rows visible at 18px each = 288px of chain body.
const ROW_HEIGHT = 18;
const CALL_W = 168;
const STRIKE_W = 88;
const PUT_W = 168;
const GRID = `${CALL_W}px ${STRIKE_W}px ${PUT_W}px`;

export function RightChain({ symbol }: Props) {
  // Pull 8 strikes above + 8 below ATM ⇒ ask for 8 in each direction.
  const { data, isLoading, isError, error } = useChainTable(symbol, 8);
  const legMutation = useOpenZeroDteLeg();
  const straddleMutation = useOpenZeroDteStraddle();
  const action = useTradeIntent((s) => s.action);
  const defaultContracts = useUserSettings((s) => s.defaultContracts);
  const { data: marketStatus } = useMarketStatus();
  const marketOpen = marketStatus?.status === "open";

  const bodyRef = useRef<HTMLDivElement>(null);
  const atmStrike = data?.atm_strike ?? null;

  // Auto-scroll ATM row to center on symbol change.
  useEffect(() => {
    if (!bodyRef.current || atmStrike == null) return;
    const row = bodyRef.current.querySelector<HTMLElement>(
      `[data-strike="${atmStrike}"]`,
    );
    if (row) row.scrollIntoView({ block: "center", behavior: "auto" });
  }, [atmStrike, symbol]);

  const chainErrMsg = isError ? (error as Error)?.message ?? "" : "";
  const noZeroDteToday = chainErrMsg.startsWith("No 0DTE for");
  const readOnly = !marketOpen || noZeroDteToday;

  const onClickCall = (row: ChainStrikeRow) => {
    if (readOnly || !data) return;
    legMutation.mutate({
      symbol: data.underlying,
      side: "call",
      action,
      strike: row.strike,
      entry_price: row.call_price,
      contracts: defaultContracts,
    });
  };
  const onClickPut = (row: ChainStrikeRow) => {
    if (readOnly || !data) return;
    legMutation.mutate({
      symbol: data.underlying,
      side: "put",
      action,
      strike: row.strike,
      entry_price: row.put_price,
      contracts: defaultContracts,
    });
  };
  const onClickStrike = (row: ChainStrikeRow) => {
    if (readOnly || !data) return;
    if (row.is_atm) {
      straddleMutation.mutate({
        symbol: data.underlying,
        action,
        contracts: defaultContracts,
      });
      return;
    }
    legMutation.mutate({
      symbol: data.underlying,
      side: "call",
      action,
      strike: row.strike,
      entry_price: row.call_price,
      contracts: defaultContracts,
    });
  };

  return (
    <section className="flex flex-col h-full min-h-0 bg-tier-0">
      <Header
        symbol={data?.underlying ?? symbol ?? "—"}
        expiry={data?.expiry ?? null}
        spot={data?.spot ?? null}
        atm={data?.atm_strike ?? null}
        iv={data?.iv_used ?? null}
      />
      <ColumnHeader />
      <div
        ref={bodyRef}
        className="flex-1 min-h-0 overflow-y-auto"
        style={{ scrollbarGutter: "stable" }}
      >
        {!symbol && <EmptyMessage>Pick a ticker in the header.</EmptyMessage>}
        {symbol && isLoading && !data && (
          <EmptyMessage>Loading {symbol} chain…</EmptyMessage>
        )}
        {noZeroDteToday && (
          <EmptyMessage tone="warning">{chainErrMsg}</EmptyMessage>
        )}
        {isError && !noZeroDteToday && (
          <EmptyMessage tone="bearish">{chainErrMsg}</EmptyMessage>
        )}
        {data && data.rows.length > 0 && (
          <div className="flex flex-col items-center">
            {data.rows.map((row) => (
              <Row
                key={row.strike}
                row={row}
                action={action}
                disabled={readOnly}
                onClickCall={() => onClickCall(row)}
                onClickPut={() => onClickPut(row)}
                onClickStrike={() => onClickStrike(row)}
              />
            ))}
          </div>
        )}
      </div>
      {(legMutation.isError || straddleMutation.isError) && (
        <div className="px-3 py-1 border-t border-hairline bg-tier-1 text-tiny text-bearish">
          {(legMutation.error as Error)?.message ??
            (straddleMutation.error as Error)?.message ??
            "open failed"}
        </div>
      )}
    </section>
  );
}

function Header({
  symbol,
  expiry,
  spot,
  atm,
  iv,
}: {
  symbol: string;
  expiry: string | null;
  spot: number | null;
  atm: number | null;
  iv: number | null;
}) {
  return (
    <div className="border-b border-hairline bg-tier-1 shrink-0">
      <div className="flex items-baseline gap-2 px-3 pt-1.5 tabular-nums">
        <span className="text-tiny uppercase tracking-label-up text-fg-secondary">
          Option chain
        </span>
        <span className="text-tiny text-fg-primary">{symbol}</span>
        <span className="text-tiny text-fg-tertiary-2">
          0DTE · exp {expiry ?? "today"}
        </span>
        <span
          className="ml-auto uppercase tracking-label-up text-fg-tertiary-2"
          style={{ fontSize: 9 }}
        >
          indicative pricing
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
      <span className="text-fg-tertiary-2 uppercase mr-1" style={{ fontSize: 9 }}>
        {label}
      </span>
      <span className="text-fg-secondary">{value}</span>
    </span>
  );
}

function ColumnHeader() {
  return (
    <div className="flex justify-center border-b border-hairline bg-tier-0 shrink-0">
      <div
        className="grid items-center text-tiny uppercase tracking-label-up text-fg-tertiary-2"
        style={{
          gridTemplateColumns: GRID,
          fontSize: 9,
          letterSpacing: "0.08em",
          height: ROW_HEIGHT,
        }}
      >
        <span className="text-right pr-3">Call</span>
        <span className="text-center">Strike</span>
        <span className="text-left pl-3">Put</span>
      </div>
    </div>
  );
}

function Row({
  row,
  action,
  disabled,
  onClickCall,
  onClickPut,
  onClickStrike,
}: {
  row: ChainStrikeRow;
  action: "buy" | "sell";
  disabled: boolean;
  onClickCall: () => void;
  onClickPut: () => void;
  onClickStrike: () => void;
}) {
  const rowCls = row.is_atm
    ? "bg-tier-1 border-l-2 border-amber"
    : "border-l-2 border-transparent hover:bg-tier-1";
  return (
    <div
      data-strike={row.strike}
      className={`grid items-center text-tiny tabular-nums border-b border-hairline ${rowCls}`}
      style={{
        gridTemplateColumns: GRID,
        height: ROW_HEIGHT,
        fontSize: 11,
      }}
    >
      <Cell
        align="right"
        price={row.call_price}
        source={row.call_source}
        disabled={disabled || row.call_price <= 0}
        action={action}
        side="call"
        strike={row.strike}
        isAtm={row.is_atm}
        onClick={onClickCall}
      />
      <button
        type="button"
        onClick={onClickStrike}
        disabled={disabled}
        className={[
          "text-center px-1 h-full border-l border-r border-hairline",
          row.is_atm ? "text-amber font-medium" : "text-fg-primary",
          disabled
            ? "text-fg-disabled cursor-not-allowed"
            : "hover:bg-tier-2",
        ].join(" ")}
        title={
          disabled
            ? "Market closed or no 0DTE today"
            : row.is_atm
              ? `${action === "buy" ? "Buy" : "Sell"} straddle at ${row.strike}`
              : `${action === "buy" ? "Long" : "Short"} call at ${row.strike}`
        }
      >
        {row.strike}
      </button>
      <Cell
        align="left"
        price={row.put_price}
        source={row.put_source}
        disabled={disabled || row.put_price <= 0}
        action={action}
        side="put"
        strike={row.strike}
        isAtm={row.is_atm}
        onClick={onClickPut}
      />
    </div>
  );
}

function Cell({
  align,
  price,
  source,
  disabled,
  action,
  side,
  strike,
  isAtm,
  onClick,
}: {
  align: "left" | "right";
  price: number;
  source: "quote" | "bs";
  disabled: boolean;
  action: "buy" | "sell";
  side: "call" | "put";
  strike: number;
  isAtm: boolean;
  onClick: () => void;
}) {
  const dim = source === "bs";
  // Disabled cells render with fg-disabled per the redesign discipline.
  const baseColor = disabled
    ? "text-fg-disabled cursor-not-allowed"
    : isAtm
      ? "text-amber"
      : dim
        ? "text-fg-tertiary-2"
        : "text-fg-primary";
  const verb = action === "buy" ? "Long" : "Short";
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className={[
        "h-full px-2 tabular-nums",
        align === "right" ? "text-right" : "text-left",
        baseColor,
        disabled ? "" : "hover:bg-tier-2",
      ].join(" ")}
      title={
        disabled
          ? "Market closed or no 0DTE today"
          : `${verb} ${side} at ${strike} · ${
              source === "bs" ? "BS-model price (no live quote)" : "indicative quote"
            }`
      }
    >
      {price.toFixed(2)}
      {source === "bs" && (
        <span
          className="text-fg-tertiary ml-0.5"
          style={{ fontSize: 8 }}
          aria-hidden
        >
          ·m
        </span>
      )}
    </button>
  );
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
