import { useMemo } from "react";

import { TradeDeskLogo } from "@/components/branding/TradeDeskLogo";
import { useMarketStatus } from "@/hooks/useMarket";
import { useTickerDetail } from "@/hooks/useTickerDetail";
import { useTradeAnalytics } from "@/hooks/useTradeAnalytics";
import { useTrades } from "@/hooks/useTrades";
import { formatPercent, formatPrice } from "@/lib/formatters";
import { useActivePosition } from "@/stores/activePosition";
import { isZeroDteTrade } from "@/types/journal";
import { STARTING_BALANCE } from "@/types/zerodte";

/**
 * Persistent Trade-Desk top header (56px).
 *
 *   left   : wordmark
 *   mid    : SPY / QQQ / IWM ticker switcher + live price + change
 *   right  : account metrics cluster — BAL · DLL · RP&L · UP&L · MKT
 *
 * Replaces the old TradeDeskToolbar's left/center cluster. The
 * timeframe selector retires from the header; the new chart toolbar
 * (Phase 3) owns timeframe selection.
 *
 * Values persistently render — none of the metrics drop out when their
 * value is zero or unknown; they render "—" instead. DLL has no
 * backend yet (no day-loss-limit guard service); rendered as "—" with
 * a TODO tracked in REDESIGN_REPORT.md.
 */
const TICKERS = ["SPY", "QQQ", "IWM"] as const;

interface Props {
  symbol: string | null;
  onSymbolChange: (s: string) => void;
}

export function TradeDeskHeader({ symbol, onSymbolChange }: Props) {
  return (
    <header
      className="flex items-center gap-6 border-b border-hairline bg-tier-0 px-4 shrink-0"
      style={{ height: 56 }}
    >
      <TradeDeskLogo size="compact" />
      <TickerSwitcher value={symbol} onChange={onSymbolChange} />
      <PriceReadout symbol={symbol} />
      <div className="ml-auto" />
      <AccountCluster />
      <MarketCell />
    </header>
  );
}

function TickerSwitcher({
  value,
  onChange,
}: {
  value: string | null;
  onChange: (s: string) => void;
}) {
  return (
    <div
      className="flex"
      role="group"
      aria-label="Ticker"
      style={{ gap: 4 }}
    >
      {TICKERS.map((t) => {
        const active = value === t;
        return (
          <button
            key={t}
            type="button"
            onClick={() => onChange(t)}
            aria-pressed={active}
            className={[
              "h-7 px-3 text-xs2 uppercase tracking-label-up tabular-nums border",
              active
                ? "border-amber text-amber bg-tier-3"
                : "border-hairline text-fg-secondary hover:bg-tier-2 hover:text-fg-primary",
            ].join(" ")}
            style={{ borderRadius: 0, fontWeight: active ? 500 : 400 }}
          >
            {t}
          </button>
        );
      })}
    </div>
  );
}

function PriceReadout({ symbol }: { symbol: string | null }) {
  const { data: detail } = useTickerDetail(symbol);
  if (!symbol) return null;
  if (!detail) {
    return (
      <span className="text-xs2 text-fg-tertiary tabular-nums">
        {symbol} —
      </span>
    );
  }
  const positive = detail.change_pct >= 0;
  const changeClass = positive ? "text-bullish" : "text-bearish";
  const sign = positive ? "+" : "";
  return (
    <div className="flex items-baseline gap-3 tabular-nums">
      <span className="text-display font-medium text-fg-primary">
        {formatPrice(detail.price)}
      </span>
      <span className={`text-xs2 ${changeClass}`}>
        {sign}
        {detail.change_dollar.toFixed(2)} ({formatPercent(detail.change_pct)})
      </span>
    </div>
  );
}

/**
 * BAL / DLL / RP&L / UP&L cluster.
 *
 * BAL  = STARTING_BALANCE + today's realized P&L + active position's UPL
 * DLL  = day loss limit (no backend yet — "—" placeholder)
 * RP&L = sum of today's closed paper trades' realized_pnl
 * UP&L = active 0DTE position's unrealized_pnl
 *
 * Color-coding: RP&L/UP&L green if >0, red if <0, fg-secondary at 0.
 */
function AccountCluster() {
  const { data: tradesData } = useTrades();
  const activeTradeId = useActivePosition((s) => s.tradeId);
  const scrubberDte = useActivePosition((s) => s.scrubberDte);
  const elapsedHours = useActivePosition((s) => s.elapsedHours);

  const activeTrade = useMemo(
    () =>
      (tradesData?.trades ?? []).find((t) => t.id === activeTradeId) ?? null,
    [tradesData, activeTradeId],
  );
  const isIntraday = useMemo(() => isZeroDteTrade(activeTrade), [activeTrade]);
  const analyticsQuery = useTradeAnalytics(activeTradeId, scrubberDte, {
    intraday: isIntraday,
    elapsedHours,
  });
  const upl = analyticsQuery.data?.unrealized_pnl ?? 0;

  const todayRpl = useMemo(() => {
    if (!tradesData?.trades) return 0;
    const todayIso = new Date().toISOString().slice(0, 10);
    return tradesData.trades.reduce((sum, t) => {
      if (!t.is_paper) return sum;
      if (t.status !== "closed") return sum;
      if (!t.exit_date) return sum;
      if (!t.exit_date.startsWith(todayIso)) return sum;
      return sum + (t.realized_pnl ?? 0);
    }, 0);
  }, [tradesData]);

  const bal = STARTING_BALANCE + todayRpl + upl;

  return (
    <div className="flex items-stretch gap-5 tabular-nums">
      <MetricLabelValue label="BAL" value={formatDollar(bal)} />
      <MetricLabelValue label="DLL" value="—" muted />
      <MetricLabelValue label="RP&L" value={formatSigned(todayRpl)} signed={todayRpl} />
      <MetricLabelValue label="UP&L" value={formatSigned(upl)} signed={upl} />
    </div>
  );
}

function MetricLabelValue({
  label,
  value,
  signed,
  muted,
}: {
  label: string;
  value: string;
  signed?: number;
  muted?: boolean;
}) {
  const valueClass =
    signed !== undefined
      ? signed > 0
        ? "text-bullish"
        : signed < 0
          ? "text-bearish"
          : "text-fg-primary"
      : muted
        ? "text-fg-tertiary-2"
        : "text-fg-primary";
  return (
    <div className="flex flex-col items-end leading-tight">
      <span
        className="uppercase tracking-label-up text-fg-tertiary-2"
        style={{ fontSize: 9, letterSpacing: "0.08em" }}
      >
        {label}
      </span>
      <span className={`text-medium font-medium ${valueClass}`}>{value}</span>
    </div>
  );
}

function MarketCell() {
  const { data: status } = useMarketStatus();
  const isOpen = status?.status === "open";
  const cls = isOpen
    ? "text-bullish border-bullish"
    : "text-bearish border-bearish";
  const detail = useMemo(() => {
    if (!status) return "—";
    if (isOpen) {
      if (status.next_close) {
        return `until ${formatClockEt(status.next_close)} ET`;
      }
      return status.label;
    }
    if (status.next_open) {
      return `until ${formatClockEt(status.next_open)} ET`;
    }
    return status.label;
  }, [status, isOpen]);
  return (
    <div className="flex flex-col items-end leading-tight">
      <span
        className="uppercase tracking-label-up text-fg-tertiary-2"
        style={{ fontSize: 9, letterSpacing: "0.08em" }}
      >
        MKT
      </span>
      <span
        className={`inline-flex items-center gap-1 px-1.5 py-px border text-tiny uppercase tracking-label-up tabular-nums ${cls}`}
        style={{ borderRadius: 0, fontSize: 10 }}
        title={status?.label}
      >
        {isOpen ? "OPEN" : "CLOSED"}
        <span className="text-fg-tertiary-2">·</span>
        <span className={isOpen ? "text-bullish" : "text-bearish"}>
          {detail}
        </span>
      </span>
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

function formatSigned(v: number): string {
  if (!Number.isFinite(v)) return "$0.00";
  const sign = v > 0 ? "+" : v < 0 ? "−" : "";
  return `${sign}$${Math.abs(v).toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

function formatClockEt(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  try {
    return d.toLocaleTimeString("en-US", {
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
      timeZone: "America/New_York",
    });
  } catch {
    return d.toISOString().slice(11, 16);
  }
}
