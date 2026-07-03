import { useMarketStatus } from "@/hooks/useMarket";
import { useNow } from "@/hooks/useNow";
import {
  formatCountdown,
  hourlyThetaBurn,
  remainingSessionMs,
} from "@/lib/thetaBurn";
import type { TradeAnalytics } from "@/types/journal";

/**
 * Compact one-row management strip — greeks + risk for the ACTIVE
 * position. Sourced from the existing /api/journal/trades/{id}/analytics
 * payload; this component does no math (the 0DTE theta-burn translation
 * lives in lib/thetaBurn, unit-tested).
 *
 * Layout convention (DESIGN.md):
 *   * Single 28px-ish band, hairline-bordered.
 *   * Each cell: 9px uppercase label + tiny tabular value.
 *   * No rounded corners, no shadows, no decorative chrome.
 *   * Signed greeks colored bullish/bearish; risk values fg-primary.
 *
 * Hidden by the parent when there is no active position — caller passes
 * null in that case and the component renders nothing.
 */
interface Props {
  analytics: TradeAnalytics | null;
  /** Display label for the position (e.g. "AAPL · long_straddle"). */
  contextLabel?: string;
}

export function PositionRiskStrip({ analytics, contextLabel }: Props) {
  // Split so the hooks (market status + ticking clock) only run while a
  // position is actually rendered — the empty strip stays hook-free.
  if (!analytics) return null;
  return <RiskStripBody analytics={analytics} contextLabel={contextLabel} />;
}

function RiskStripBody({
  analytics,
  contextLabel,
}: {
  analytics: TradeAnalytics;
  contextLabel?: string;
}) {
  // ── 0DTE theta-burn clock ─────────────────────────────────────────────
  // Only meaningful when the position expires TODAY (current_dte_days 0);
  // multi-day positions keep the plain per-day theta cell. Session close
  // comes from market status (covers early-close half days), falling back
  // to 4:00pm ET; useNow ticks the countdown + $/hr live.
  const isZeroDte = analytics.current_dte_days === 0;
  const { data: market } = useMarketStatus();
  const now = useNow(1_000);
  const remainingMs = remainingSessionMs(
    now.getTime(),
    market?.today_close ?? null,
  );
  // Market-status "open" gates the live state; when the status hasn't
  // loaded yet we trust the clock alone (degrade gracefully, never blank).
  const marketOpen = market ? market.status === "open" : true;
  const sessionLive = marketOpen && remainingMs > 0;

  const { greeks } = analytics;
  const maxGain = analytics.unlimited_gain
    ? "unlimited"
    : formatDollar(analytics.max_profit ?? 0);
  const maxLoss = analytics.unlimited_loss
    ? "unlimited"
    : formatDollar(analytics.max_loss ?? 0);

  return (
    <div
      className="flex items-stretch border-b border-hairline bg-tier-0 shrink-0 tabular-nums"
      role="region"
      aria-label="Position management — greeks and risk"
    >
      {contextLabel && (
        <div
          className="flex items-center px-3 border-r border-hairline text-tiny uppercase tracking-label-up text-fg-tertiary"
          style={{ fontSize: 11 }}
        >
          {contextLabel}
        </div>
      )}
      <Cell label="Delta" value={greeks.delta} signed />
      <Cell label="Gamma" value={greeks.gamma} />
      {isZeroDte ? (
        <ThetaBurnCell
          theta={greeks.theta}
          remainingMs={remainingMs}
          sessionLive={sessionLive}
        />
      ) : (
        <Cell label="Theta" value={greeks.theta} signed />
      )}
      <Cell label="Vega" value={greeks.vega} signed />
      <div className="border-r border-hairline" />
      <Cell label="UPL" value={analytics.unrealized_pnl} signed dollar />
      <Cell label="Cost" value={analytics.cost_basis} dollar />
      <Cell label="Max gain" valueText={maxGain} />
      <Cell label="Max loss" valueText={maxLoss} tone={analytics.unlimited_loss ? "bearish" : undefined} />
      <div className="flex-1" />
    </div>
  );
}

/**
 * 0DTE theta-burn clock cell — translates per-day theta into
 * remaining-session decay ("Θ −$42/day · ≈ −$18/hr") plus an "expires in
 * H:MM" countdown. Sign convention: a net-credit (short) position
 * COLLECTS theta → positive/green; a net-debit (long) pays it → red.
 * After the close: "session over · settles at close" (no negative hours).
 */
function ThetaBurnCell({
  theta,
  remainingMs,
  sessionLive,
}: {
  theta: number;
  remainingMs: number;
  sessionLive: boolean;
}) {
  const perHour = sessionLive
    ? hourlyThetaBurn(theta, remainingMs / 3_600_000)
    : null;
  const cls =
    theta > 0 ? "text-bullish" : theta < 0 ? "text-bearish" : "text-fg-secondary";
  const title =
    theta > 0
      ? "Net-credit position — you COLLECT theta. The whole day's decay accrues over what's left of the session, so $/hr = per-day theta ÷ hours to the close."
      : "Per-day theta compressed into the remaining session — a 0DTE's decay all lands before the close, so $/hr = per-day theta ÷ hours to the close.";
  return (
    <div
      className="flex flex-col px-2.5 py-0.5 border-r border-hairline justify-center"
      style={{ minWidth: 150 }}
      title={title}
    >
      <span
        className="text-tiny uppercase tracking-label-up text-fg-tertiary"
        style={{ fontSize: 11, letterSpacing: "0.08em" }}
      >
        {sessionLive ? `Theta burn · expires in ${formatCountdown(remainingMs)}` : "Theta burn"}
      </span>
      {sessionLive && perHour != null ? (
        <span className={`text-tiny ${cls}`}>
          Θ {formatDollar(theta, true)}/day · ≈ {formatDollar(perHour, true)}/hr
        </span>
      ) : (
        <span className="text-tiny text-fg-tertiary-2">
          session over · settles at close
        </span>
      )}
    </div>
  );
}

function Cell({
  label,
  value,
  valueText,
  signed,
  dollar,
  tone,
}: {
  label: string;
  value?: number;
  valueText?: string;
  signed?: boolean;
  dollar?: boolean;
  tone?: "bearish";
}) {
  const display =
    valueText ??
    (value === undefined
      ? "—"
      : dollar
        ? formatDollar(value, signed)
        : formatNumber(value, signed));
  const cls = signed && value !== undefined
    ? value > 0
      ? "text-bullish"
      : value < 0
        ? "text-bearish"
        : "text-fg-secondary"
    : tone === "bearish"
      ? "text-bearish"
      : "text-fg-primary";
  return (
    <div
      className="flex flex-col px-2.5 py-0.5 border-r border-hairline justify-center"
      style={{ minWidth: 78 }}
    >
      <span
        className="text-tiny uppercase tracking-label-up text-fg-tertiary"
        style={{ fontSize: 11, letterSpacing: "0.08em" }}
      >
        {label}
      </span>
      <span className={`text-tiny ${cls}`}>{display}</span>
    </div>
  );
}

function formatDollar(v: number, signed: boolean = false): string {
  if (!Number.isFinite(v)) return "$0.00";
  const sign = signed ? (v > 0 ? "+" : v < 0 ? "−" : "") : v < 0 ? "−" : "";
  return `${sign}$${Math.abs(v).toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

function formatNumber(v: number, signed: boolean = false): string {
  if (!Number.isFinite(v)) return "0";
  const abs = Math.abs(v);
  const sign = signed ? (v > 0 ? "+" : v < 0 ? "−" : "") : v < 0 ? "−" : "";
  // Gamma is tiny per-share but we report position-dollar greeks here
  // (scaled by CONTRACT_MULTIPLIER server-side); 4 decimals keeps it
  // readable for both intraday (huge gamma) and multi-day (near-zero).
  if (abs >= 100) return `${sign}${abs.toFixed(2)}`;
  if (abs >= 1) return `${sign}${abs.toFixed(3)}`;
  return `${sign}${abs.toFixed(4)}`;
}
