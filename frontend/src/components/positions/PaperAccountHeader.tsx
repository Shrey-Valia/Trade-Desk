import { useMemo } from "react";

import { useTrades } from "@/hooks/useTrades";

/**
 * UPL / RPL / Balance band — shown above the chart when a paper 0DTE
 * position is open. Mirrors the prototype's session header logic, now
 * read from real Trade records instead of localStorage:
 *
 *   UPL     — unrealized P&L on the active 0DTE trade (analytics result)
 *   RPL     — realized P&L summed across today's closed paper trades
 *   Balance — STARTING_BALANCE + RPL + UPL
 *
 * Hidden by the caller when no paper 0DTE trade is active; this
 * component just renders the row given the numbers.
 */
const STARTING_BALANCE = 10_000;

interface Props {
  /** Unrealized P&L on the active position (dollars, signed). */
  upl: number;
}

export function PaperAccountHeader({ upl }: Props) {
  const { data } = useTrades();
  const todayPaperRpl = useMemo(() => {
    if (!data?.trades) return 0;
    const todayIso = new Date().toISOString().slice(0, 10);
    return data.trades.reduce((sum, t) => {
      if (!t.is_paper) return sum;
      if (t.status !== "closed") return sum;
      if (!t.exit_date) return sum;
      if (!t.exit_date.startsWith(todayIso)) return sum;
      return sum + (t.realized_pnl ?? 0);
    }, 0);
  }, [data]);
  const balance = STARTING_BALANCE + todayPaperRpl + upl;
  return (
    <div className="flex items-stretch border-b border-hairline bg-tier-1 shrink-0">
      <Cell label="UPL" value={upl} signed />
      <Cell label="RPL · today (paper)" value={todayPaperRpl} signed />
      <Cell label="Balance" value={balance} />
      <div className="flex-1" />
    </div>
  );
}

function Cell({
  label,
  value,
  signed,
}: {
  label: string;
  value: number;
  signed?: boolean;
}) {
  const cls = signed
    ? value > 0
      ? "text-bullish"
      : value < 0
        ? "text-bearish"
        : "text-fg-secondary"
    : "text-fg-primary";
  const sign = signed && value > 0 ? "+" : value < 0 ? "−" : "";
  const formatted = `${sign}$${Math.abs(value).toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
  return (
    <div
      className="flex flex-col px-3 py-1 border-r border-hairline"
      style={{ minWidth: 124 }}
    >
      <span
        className="uppercase tracking-label-up text-fg-tertiary"
        style={{ fontSize: 9, letterSpacing: "0.08em" }}
      >
        {label}
      </span>
      <span className={`text-medium font-medium tabular-nums ${cls}`}>
        {formatted}
      </span>
    </div>
  );
}
