import { useState } from "react";

import { PayoffCurveSvg } from "@/components/analytics/PayoffCurveSvg";
import { PanelHeader } from "@/components/positions/panelChrome";
import { useContractPreview } from "@/hooks/useContractPreview";
import { useTradeTicket } from "@/stores/tradeTicket";
import type { ContractPreview } from "@/types/zerodte";

type Direction = "long" | "short";

/**
 * Contract-detail panel — Webull-style. Fills the space below the trade
 * ticket once a chain contract is selected: a P&L payoff diagram + a
 * greeks/stats block. A LONG/SHORT toggle flips between buying and writing
 * the contract — a short position's P&L is exactly the negative of the
 * long's (break-evens unchanged), so we flip client-side off the same
 * preview. Reads the selection from the ticket store; data via
 * useContractPreview (works on indicative pricing).
 */
export function ContractDetailPanel() {
  const selection = useTradeTicket((s) => s.selection);
  const { data, isLoading, isError, refetch } = useContractPreview();
  const [dir, setDir] = useState<Direction>("long");

  // No selection → keep the original empty spacer (fills the column).
  if (!selection) return <div className="flex-1 bg-tier-0" />;

  const sideLabel =
    selection.kind === "straddle" ? "STRADDLE" : (selection.side ?? "call").toUpperCase();
  const title = `${selection.symbol} ${selection.strike} ${sideLabel}`;
  const v = data ? viewFor(data, dir) : null;

  return (
    <div className="flex-1 min-h-0 flex flex-col border-t border-hairline bg-tier-0 overflow-y-auto">
      <PanelHeader
        left={title}
        right={v ? `${formatDollar(v.premium)} ${dir === "long" ? "db" : "cr"}` : ""}
        headerControl={<DirToggle dir={dir} onChange={setDir} />}
      />
      {isLoading && !data ? (
        <Centered>Loading contract…</Centered>
      ) : isError && !data ? (
        <ErrorState onRetry={() => refetch()} />
      ) : data && v ? (
        <>
          <div className="px-2 pt-2 shrink-0" style={{ height: 152 }}>
            <PayoffCurveSvg
              prices={data.prices}
              payoffExpiration={v.payoffExpiration}
              payoffToday={v.payoffToday}
              breakevens={data.breakevens}
              spot={data.spot}
            />
          </div>

          <div className="px-3 pt-2 grid grid-cols-4 gap-x-3 gap-y-1">
            <Greek label="Δ Delta" value={v.greeks.delta.toFixed(2)} />
            <Greek label="Γ Gamma" value={v.greeks.gamma.toFixed(3)} />
            <Greek label="Θ Theta" value={v.greeks.theta.toFixed(2)} />
            <Greek label="ν Vega" value={v.greeks.vega.toFixed(2)} />
          </div>

          <div className="px-3 py-2 grid grid-cols-2 gap-x-4 gap-y-1">
            <Row label="IV" value={`${(data.iv * 100).toFixed(1)}%`} />
            <Row
              label="Open int."
              value={data.open_interest != null ? data.open_interest.toLocaleString() : "—"}
            />
            <Row
              label="Break-even"
              value={
                data.breakevens.length
                  ? data.breakevens.map((b) => b.toFixed(2)).join(" / ")
                  : "—"
              }
            />
            <Row label={dir === "long" ? "Cost" : "Credit"} value={formatDollar(v.premium)} />
            <Row label="Max loss" value={maxLabel(v.maxLoss)} tone="bearish" />
            <Row label="Max profit" value={maxLabel(v.maxProfit)} tone="bullish" />
          </div>

          <div className="px-3 pb-2 text-fg-tertiary" style={{ fontSize: 11 }}>
            {dir === "long" ? "Long" : "Short"}{" "}
            {selection.kind === "straddle" ? "straddle" : selection.side ?? "call"} ·{" "}
            {data.dte_label} · {data.contracts} contract
            {data.contracts === 1 ? "" : "s"} · indicative pricing
          </div>
        </>
      ) : null}
    </div>
  );
}

interface PreviewView {
  payoffToday: number[];
  payoffExpiration: number[];
  greeks: { delta: number; gamma: number; theta: number; vega: number };
  maxProfit: number | null; // null = unbounded
  maxLoss: number | null; // null = unbounded; otherwise negative
  premium: number; // debit (long) or credit (short), magnitude
}

/**
 * Long uses the preview as-is. Short is the mirror image: negate the P&L
 * curves and greeks, and swap max profit/loss (long's max loss becomes
 * short's max profit, and long's unbounded upside becomes short's
 * unbounded downside). Break-even prices are identical either way.
 */
function viewFor(d: ContractPreview, dir: Direction): PreviewView {
  if (dir === "long") {
    return {
      payoffToday: d.payoff_today,
      payoffExpiration: d.payoff_expiration,
      greeks: d.greeks,
      maxProfit: d.max_profit,
      maxLoss: d.max_loss,
      premium: Math.abs(d.cost),
    };
  }
  return {
    payoffToday: d.payoff_today.map((x) => -x),
    payoffExpiration: d.payoff_expiration.map((x) => -x),
    greeks: {
      delta: -d.greeks.delta,
      gamma: -d.greeks.gamma,
      theta: -d.greeks.theta,
      vega: -d.greeks.vega,
    },
    // Short max profit = the premium collected (− long max loss).
    maxProfit: -d.max_loss,
    // Short max loss = − long max profit (unbounded if long was unbounded).
    maxLoss: d.max_profit == null ? null : -d.max_profit,
    premium: Math.abs(d.cost),
  };
}

function maxLabel(v: number | null): string {
  if (v == null) return "Unlimited";
  return formatDollar(Math.abs(v));
}

function DirToggle({
  dir,
  onChange,
}: {
  dir: Direction;
  onChange: (d: Direction) => void;
}) {
  return (
    <span className="flex items-center gap-1" style={{ fontSize: 11 }}>
      <DirButton active={dir === "long"} onClick={() => onChange("long")}>
        Long
      </DirButton>
      <span className="text-fg-tertiary" aria-hidden>
        ·
      </span>
      <DirButton active={dir === "short"} onClick={() => onChange("short")}>
        Short
      </DirButton>
    </span>
  );
}

function DirButton({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={`uppercase tracking-label-up transition-colors duration-100 ${
        active ? "text-amber" : "text-fg-tertiary-2 hover:text-amber"
      }`}
    >
      {children}
    </button>
  );
}

function Greek({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col gap-0.5">
      <span
        className="uppercase tracking-label-up text-fg-tertiary-2"
        style={{ fontSize: 11 }}
      >
        {label}
      </span>
      <span className="text-body tabular-nums text-fg-primary">{value}</span>
    </div>
  );
}

function Row({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone?: "bullish" | "bearish";
}) {
  const cls =
    tone === "bullish"
      ? "text-bullish"
      : tone === "bearish"
        ? "text-bearish"
        : "text-fg-secondary";
  return (
    <div className="flex items-baseline justify-between gap-2 text-tiny">
      <span className="uppercase tracking-label-up text-fg-tertiary-2" style={{ fontSize: 11 }}>
        {label}
      </span>
      <span className={`tabular-nums ${cls}`}>{value}</span>
    </div>
  );
}

function Centered({ children }: { children: string }) {
  return (
    <div className="flex-1 flex items-center justify-center text-tiny text-fg-tertiary-2">
      {children}
    </div>
  );
}

function ErrorState({ onRetry }: { onRetry: () => void }) {
  return (
    <div className="flex-1 flex flex-col items-center justify-center gap-1.5 px-4 text-center">
      <span className="text-tiny text-fg-tertiary">Contract detail unavailable</span>
      <button
        type="button"
        onClick={onRetry}
        className="text-tiny uppercase tracking-label-up text-fg-tertiary-2 hover:text-amber transition-colors duration-100"
        style={{ fontSize: 11 }}
      >
        retry
      </button>
    </div>
  );
}

function formatDollar(v: number): string {
  if (!Number.isFinite(v)) return "—";
  return `$${v.toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}
