import { useMemo, useState } from "react";

import { useChainTable } from "@/hooks/useChainTable";
import { useMonteCarlo } from "@/hooks/useMonteCarlo";
import { useTradeTicket } from "@/stores/tradeTicket";
import type { MonteCarloLeg, MonteCarloResult } from "@/types/zerodte";

/**
 * WS5 — Monte-Carlo scenario / backtest panel. Self-contained: simulates the
 * terminal-value distribution + P(profit) for the CURRENT ticket selection
 * (a leg or straddle) under a tunable vol / horizon / drift. Spot + ATM IV +
 * time-to-close come from the chain table; the trader can override vol and
 * apply a directional drift to explore "what if".
 *
 * Reads the selection from the ticket store; runs on demand (a mutation),
 * never on every keystroke. When nothing is selected it shows a hint.
 */
export function MonteCarloPanel() {
  const selection = useTradeTicket((s) => s.selection);
  const symbol = selection?.symbol ?? null;
  const { data: chain } = useChainTable(symbol, 5);
  const mc = useMonteCarlo();

  const spot = chain?.spot ?? null;
  const atmIv = chain?.iv_used ?? null;
  // 0DTE horizon in (trading-day) fraction: years-to-close × 252.
  const horizonDays = chain
    ? Math.max(0.01, chain.t_years_to_close * 252)
    : null;

  const [ivPct, setIvPct] = useState<number | null>(null);
  const [driftPct, setDriftPct] = useState<number>(0);
  const sigma = ivPct != null ? ivPct / 100 : atmIv;

  const legs = useMemo<MonteCarloLeg[] | null>(
    () => (selection ? legsFromSelection(selection) : null),
    [selection],
  );

  const canRun =
    !!legs && spot != null && sigma != null && horizonDays != null && !mc.isPending;

  const run = () => {
    if (!canRun || !legs || spot == null || sigma == null || horizonDays == null) return;
    mc.mutate({
      legs,
      spot,
      sigma,
      horizon_days: horizonDays,
      drift: driftPct !== 0 ? driftPct / 100 : null,
      paths: 10000,
      seed: 1,
    });
  };

  return (
    <div className="flex flex-col gap-1.5 px-3 py-2 tabular-nums">
      <div className="flex items-center justify-between">
        <span className="text-tiny uppercase tracking-label-up text-fg-secondary">
          Monte-Carlo
        </span>
        <span className="text-fg-tertiary-2" style={{ fontSize: 11 }}>
          {selection ? `${selection.symbol} terminal P&L` : "no selection"}
        </span>
      </div>

      {!selection ? (
        <span className="text-fg-tertiary-2" style={{ fontSize: 12 }}>
          Select a contract in the chain to simulate its outcome distribution.
        </span>
      ) : (
        <>
          <div className="grid grid-cols-3 gap-2">
            <Field
              label="vol %"
              value={ivPct ?? (atmIv != null ? round1(atmIv * 100) : null)}
              onChange={setIvPct}
              step={1}
              ariaLabel="Volatility percent"
            />
            <Field
              label="drift %"
              value={driftPct}
              onChange={(v) => setDriftPct(v ?? 0)}
              step={1}
              ariaLabel="Annualized drift percent"
            />
            <div className="flex flex-col gap-0.5" style={{ fontSize: 11 }}>
              <span className="uppercase tracking-label-up text-fg-tertiary-2">horizon</span>
              <span className="text-fg-secondary" style={{ fontSize: 12 }}>
                {horizonDays != null ? `${horizonDays.toFixed(2)}d` : "—"}
              </span>
            </div>
          </div>

          <button
            type="button"
            onClick={run}
            disabled={!canRun}
            className={[
              "self-start rounded-btn px-3 font-semibold uppercase tracking-label-up transition-colors duration-100",
              canRun
                ? "bg-tier-3 border border-amber text-amber hover:bg-tier-2"
                : "bg-tier-1 text-fg-disabled cursor-not-allowed",
            ].join(" ")}
            style={{ height: 26, fontSize: 11 }}
          >
            {mc.isPending ? "simulating…" : "run 10k paths"}
          </button>

          {mc.isError && (
            <span className="text-bearish" style={{ fontSize: 11 }}>
              {(mc.error as Error)?.message || "simulation failed"}
            </span>
          )}
          {mc.data && <Result data={mc.data} />}
        </>
      )}
    </div>
  );
}

function Result({ data }: { data: MonteCarloResult }) {
  const pop = Math.round(data.prob_profit * 100);
  const popTone =
    pop >= 60 ? "text-bullish" : pop >= 40 ? "text-warning" : "text-bearish";
  return (
    <div className="flex flex-col gap-1 pt-0.5" aria-live="polite">
      <div className="flex items-baseline justify-between" style={{ fontSize: 13 }}>
        <span className="uppercase tracking-label-up text-fg-tertiary-2" style={{ fontSize: 11 }}>
          P(profit)
        </span>
        <span className={`tabular-nums font-medium ${popTone}`}>{pop}%</span>
      </div>
      <Histogram data={data} />
      <div className="grid grid-cols-2 gap-x-3 gap-y-0.5 pt-0.5" style={{ fontSize: 12 }}>
        <Stat label="exp. P&L" value={signed(data.expected_pnl)} tone={data.expected_pnl >= 0 ? "bull" : "bear"} />
        <Stat label="median" value={signed(data.median_pnl)} tone={data.median_pnl >= 0 ? "bull" : "bear"} />
        <Stat label="5th %ile" value={signed(data.pnl_p05)} tone="bear" />
        <Stat label="95th %ile" value={signed(data.pnl_p95)} tone="bull" />
        <Stat label="95% VaR" value={`$${fmt(data.var_95)}`} tone="bear" />
        <Stat label="cost basis" value={signed(-data.cost_basis)} />
      </div>
    </div>
  );
}

/** Terminal-value P&L distribution as a tiny SVG histogram. Green bars above
 *  break-even (P&L ≥ 0), red below; a magenta line marks zero. */
function Histogram({ data }: { data: MonteCarloResult }) {
  const W = 220;
  const H = 48;
  const counts = data.hist_counts;
  const edges = data.hist_bin_edges;
  const maxCount = Math.max(1, ...counts);
  const n = counts.length;
  const bw = W / n;
  const min = edges[0];
  const max = edges[edges.length - 1];
  const zeroX =
    max > min ? ((0 - min) / (max - min)) * W : W / 2;
  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      width="100%"
      height={H}
      role="img"
      aria-label="Terminal P&L distribution"
      style={{ display: "block" }}
    >
      {counts.map((c, i) => {
        const h = (c / maxCount) * (H - 2);
        const x = i * bw;
        const binMid = (edges[i] + edges[i + 1]) / 2;
        const fill = binMid >= 0 ? "var(--color-bullish)" : "var(--color-bearish)";
        return (
          <rect
            key={i}
            x={x + 0.3}
            y={H - h}
            width={Math.max(0.5, bw - 0.6)}
            height={h}
            fill={fill}
            opacity={0.85}
          />
        );
      })}
      {zeroX >= 0 && zeroX <= W && (
        <line
          x1={zeroX}
          y1={0}
          x2={zeroX}
          y2={H}
          stroke="var(--color-position, #d946ef)"
          strokeWidth={1}
          strokeDasharray="2 2"
        />
      )}
    </svg>
  );
}

function Stat({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone?: "bull" | "bear";
}) {
  const color =
    tone === "bull" ? "text-bullish" : tone === "bear" ? "text-bearish" : "text-fg-secondary";
  return (
    <div className="flex items-baseline justify-between">
      <span className="uppercase tracking-label-up text-fg-tertiary-2" style={{ fontSize: 11 }}>
        {label}
      </span>
      <span className={`tabular-nums ${color}`}>{value}</span>
    </div>
  );
}

function Field({
  label,
  value,
  onChange,
  step,
  ariaLabel,
}: {
  label: string;
  value: number | null;
  onChange: (v: number | null) => void;
  step: number;
  ariaLabel: string;
}) {
  return (
    <label className="flex flex-col gap-0.5" style={{ fontSize: 11 }}>
      <span className="uppercase tracking-label-up text-fg-tertiary-2">{label}</span>
      <input
        type="number"
        inputMode="decimal"
        step={step}
        value={value ?? ""}
        onChange={(e) => {
          const v = parseFloat(e.target.value);
          onChange(Number.isFinite(v) ? v : null);
        }}
        aria-label={ariaLabel}
        className="bg-tier-2 border border-tier-3 rounded-btn text-fg-primary tabular-nums text-right px-1.5 w-full"
        style={{ height: 24, fontSize: 12 }}
      />
    </label>
  );
}

// --- helpers ---------------------------------------------------------------

interface SelectionLike {
  kind: "leg" | "straddle";
  side?: "call" | "put";
  strike: number;
  price: number;
}

/** Build Monte-Carlo legs (long, 1 contract) from the ticket selection. The
 *  straddle is long call + long put at the strike; a leg is the chosen side.
 *  The selection's `price` is the per-share premium; a straddle's price is
 *  call+put, so we split it evenly as a reasonable per-leg basis. */
export function legsFromSelection(sel: SelectionLike): MonteCarloLeg[] {
  if (sel.kind === "straddle") {
    const each = sel.price / 2;
    return [
      { side: "call", action: "buy", strike: sel.strike, contracts: 1, entry_price: each },
      { side: "put", action: "buy", strike: sel.strike, contracts: 1, entry_price: each },
    ];
  }
  return [
    {
      side: sel.side ?? "call",
      action: "buy",
      strike: sel.strike,
      contracts: 1,
      entry_price: sel.price,
    },
  ];
}

function signed(v: number): string {
  const s = v >= 0 ? "+" : "−";
  return `${s}$${fmt(Math.abs(v))}`;
}

function fmt(v: number): string {
  return v.toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 0 });
}

function round1(v: number): number {
  return Math.round(v * 10) / 10;
}
