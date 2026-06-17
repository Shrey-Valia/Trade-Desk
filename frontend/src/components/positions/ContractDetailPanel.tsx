import { PayoffCurveSvg } from "@/components/analytics/PayoffCurveSvg";
import { PanelHeader } from "@/components/positions/panelChrome";
import { useContractPreview } from "@/hooks/useContractPreview";
import { useTradeTicket } from "@/stores/tradeTicket";

/**
 * Contract-detail panel — Webull-style. Fills the space below the trade
 * ticket once a chain contract is selected: a P&L payoff diagram for the
 * (long) contract + a greeks/stats block. Reads the selection from the
 * ticket store; data via useContractPreview (works on indicative pricing).
 */
export function ContractDetailPanel() {
  const selection = useTradeTicket((s) => s.selection);
  const { data, isLoading, isError, refetch } = useContractPreview();

  // No selection → keep the original empty spacer (fills the column).
  if (!selection) return <div className="flex-1 bg-tier-0" />;

  const sideLabel =
    selection.kind === "straddle" ? "STRADDLE" : (selection.side ?? "call").toUpperCase();
  const title = `${selection.symbol} ${selection.strike} ${sideLabel}`;

  return (
    <div className="flex-1 min-h-0 flex flex-col border-t border-hairline bg-tier-0 overflow-y-auto">
      <PanelHeader
        left={title}
        right={data ? `${formatDollar(data.entry_price)} db` : ""}
      />
      {isLoading && !data ? (
        <Centered>Loading contract…</Centered>
      ) : isError && !data ? (
        <ErrorState onRetry={() => refetch()} />
      ) : data ? (
        <>
          <div className="px-2 pt-2 shrink-0" style={{ height: 152 }}>
            <PayoffCurveSvg
              prices={data.prices}
              payoffExpiration={data.payoff_expiration}
              payoffToday={data.payoff_today}
              breakevens={data.breakevens}
              spot={data.spot}
            />
          </div>

          <div className="px-3 pt-2 grid grid-cols-4 gap-x-3 gap-y-1">
            <Greek label="Δ Delta" value={data.greeks.delta.toFixed(2)} />
            <Greek label="Γ Gamma" value={data.greeks.gamma.toFixed(3)} />
            <Greek label="Θ Theta" value={data.greeks.theta.toFixed(2)} />
            <Greek label="ν Vega" value={data.greeks.vega.toFixed(2)} />
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
            <Row label="Cost" value={formatDollar(data.cost)} />
            <Row label="Max loss" value={formatDollar(Math.abs(data.max_loss))} tone="bearish" />
            <Row
              label="Max profit"
              value={data.max_profit == null ? "Unlimited" : formatDollar(data.max_profit)}
              tone="bullish"
            />
          </div>

          <div
            className="px-3 pb-2 text-fg-tertiary"
            style={{ fontSize: 9 }}
          >
            Long {selection.kind === "straddle" ? "straddle" : selection.side ?? "call"} ·{" "}
            {data.dte_label} · {data.contracts} contract
            {data.contracts === 1 ? "" : "s"} · indicative pricing
          </div>
        </>
      ) : null}
    </div>
  );
}

function Greek({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col gap-0.5">
      <span
        className="uppercase tracking-label-up text-fg-tertiary-2"
        style={{ fontSize: 9 }}
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
      <span className="uppercase tracking-label-up text-fg-tertiary-2" style={{ fontSize: 9 }}>
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
        style={{ fontSize: 9 }}
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
