import { useMemo, useState } from "react";

import { TradeDeskLogo } from "@/components/branding/TradeDeskLogo";
import { useAccountState, useSwitchTier } from "@/hooks/useAccountState";
import { useMarketStatus } from "@/hooks/useMarket";
import { useTickerDetail } from "@/hooks/useTickerDetail";
import { useTradeAnalytics } from "@/hooks/useTradeAnalytics";
import { useTrades } from "@/hooks/useTrades";
import { formatPercent, formatPrice } from "@/lib/formatters";
import { useActivePosition } from "@/stores/activePosition";
import { isZeroDteTrade } from "@/types/journal";
import type { TierSpec } from "@/types/account";

/**
 * Persistent Trade-Desk top header (40px).
 *
 *   left   : wordmark + combine-tier pill (50K / 100K / 150K)
 *   mid    : SPY / QQQ / IWM ticker switcher + live price + change
 *   right  : account metrics — BAL · MLL · RP&L · UP&L · MKT
 *
 * BAL / MLL / RP&L track the active combine tier via /api/account/state.
 * MLL color-codes by proximity: fg-primary when comfortably above,
 * warning when within 25% of trailing distance, bearish when within
 * 10%, bright bearish + "MLL BREACHED" pill when balance < MLL.
 *
 * No enforcement — display only. Trades can still open if MLL is
 * breached. That's a deliberate scope choice for this phase.
 */
const TICKERS = ["SPY", "QQQ", "IWM"] as const;

interface Props {
  symbol: string | null;
  onSymbolChange: (s: string) => void;
}

export function TradeDeskHeader({ symbol, onSymbolChange }: Props) {
  return (
    <header
      className="flex items-center gap-3 border-b border-hairline bg-tier-0 px-3 shrink-0 relative"
      style={{ height: 40 }}
    >
      <TradeDeskLogo size="mini" />
      <TierPill />
      <TickerSwitcher value={symbol} onChange={onSymbolChange} />
      <PriceReadout symbol={symbol} />
      <div className="ml-auto" />
      <AccountCluster />
      <MarketCell />
    </header>
  );
}

/** Combine-tier indicator + switcher. Click to open a 3-option menu. */
function TierPill() {
  const { data } = useAccountState();
  const switchTier = useSwitchTier();
  const [open, setOpen] = useState(false);
  const tierKey = data?.active_tier ?? "50K";
  const tiers = data?.tiers ?? [];
  const breached = data ? data.balance < data.mll : false;
  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className={[
          "h-5 px-2 border uppercase tracking-label-up tabular-nums",
          breached
            ? "border-bearish text-bearish bg-tier-1"
            : "border-fg-tertiary text-fg-primary bg-tier-1 hover:bg-tier-2",
        ].join(" ")}
        style={{ borderRadius: 0, fontSize: 10, fontWeight: 500 }}
        aria-haspopup="listbox"
        aria-expanded={open}
        title="Active combine tier — click to switch"
      >
        {tierKey} COMBINE
        <span className="text-fg-tertiary-2 ml-1.5" style={{ fontSize: 8 }}>
          ▾
        </span>
      </button>
      {open && tiers.length > 0 && (
        <div
          role="listbox"
          className="absolute left-0 top-full mt-1 z-30 border border-hairline bg-tier-1 shadow-none"
          style={{ borderRadius: 0, minWidth: 160 }}
        >
          {tiers.map((t: TierSpec) => {
            const active = t.key === tierKey;
            return (
              <button
                key={t.key}
                type="button"
                onClick={() => {
                  if (!active) switchTier.mutate(t.key);
                  setOpen(false);
                }}
                className={[
                  "w-full text-left px-2 py-1 text-tiny tabular-nums border-b border-hairline last:border-b-0",
                  active
                    ? "text-amber bg-tier-2"
                    : "text-fg-secondary hover:bg-tier-2 hover:text-fg-primary",
                ].join(" ")}
                style={{ borderRadius: 0 }}
              >
                <div className="uppercase tracking-label-up" style={{ fontSize: 10 }}>
                  {t.key} Combine
                </div>
                <div className="text-fg-tertiary-2" style={{ fontSize: 9 }}>
                  ${(t.starting_balance / 1000).toFixed(0)}K · −${(t.trailing_distance).toLocaleString()} MLL
                </div>
              </button>
            );
          })}
        </div>
      )}
    </div>
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
      style={{ gap: 2 }}
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
              "h-5 px-2 text-tiny uppercase tracking-label-up tabular-nums border",
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
      <span className="text-tiny text-fg-tertiary tabular-nums">
        {symbol} —
      </span>
    );
  }
  const positive = detail.change_pct >= 0;
  const changeClass = positive ? "text-bullish" : "text-bearish";
  const sign = positive ? "+" : "";
  return (
    <div className="flex items-baseline gap-1.5 tabular-nums">
      <span className="text-medium font-medium text-fg-primary">
        {formatPrice(detail.price)}
      </span>
      <span className={`text-tiny ${changeClass}`} style={{ fontSize: 10 }}>
        {sign}
        {detail.change_dollar.toFixed(2)} ({formatPercent(detail.change_pct)})
      </span>
    </div>
  );
}

/**
 * BAL / MLL / RP&L / UP&L cluster.
 *
 * BAL  = active tier's balance (starting + realized) + active position's UPL
 * MLL  = trailing maximum-loss-limit from /api/account/state; color
 *        graded by proximity (see mllToneClass).
 * RP&L = today's closed-trade realized P&L (paper, active tier)
 * UP&L = active position's unrealized_pnl
 *
 * Color-coding: RP&L/UP&L green if >0, red if <0, fg-secondary at 0.
 */
function AccountCluster() {
  const { data: account } = useAccountState();
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

  // Today's realized — same math as before, but filter by the active
  // tier so switching combines doesn't double-count history.
  const activeTier = account?.active_tier ?? "50K";
  const todayRpl = useMemo(() => {
    if (!tradesData?.trades) return 0;
    const todayIso = new Date().toISOString().slice(0, 10);
    return tradesData.trades.reduce((sum, t) => {
      if (!t.is_paper) return sum;
      if (t.tier && t.tier !== activeTier) return sum;
      if (t.status !== "closed") return sum;
      if (!t.exit_date) return sum;
      if (!t.exit_date.startsWith(todayIso)) return sum;
      return sum + (t.realized_pnl ?? 0);
    }, 0);
  }, [tradesData, activeTier]);

  // Balance: server-computed (starting + realized) plus client-side UPL.
  const bal = (account?.balance ?? 0) + upl;
  const mll = account?.mll ?? 0;
  const trailing =
    account?.tiers.find((t) => t.key === activeTier)?.trailing_distance ?? 1;
  const mllTone = mllToneClass(bal, mll, trailing);
  const breached = bal < mll;

  return (
    <div className="flex items-stretch gap-2 tabular-nums">
      <MetricLabelValue label="BAL" value={formatDollar(bal)} />
      <MetricLabelValue label="MLL" value={formatDollar(mll)} valueClass={mllTone} />
      {breached && <BreachedPill />}
      <MetricLabelValue label="RP&L" value={formatSigned(todayRpl)} signed={todayRpl} />
      <MetricLabelValue label="UP&L" value={formatSigned(upl)} signed={upl} />
    </div>
  );
}

/**
 * Distance from current balance to MLL graded as a fraction of the
 * tier's trailing distance:
 *   ≥25% of trail → safe (fg-primary)
 *   <25%          → warning
 *   <10%          → bearish
 *   <0%           → bright bearish (breach state — pill rendered separately)
 */
function mllToneClass(balance: number, mll: number, trailing: number): string {
  if (balance < mll) return "text-bearish font-medium";
  const cushion = balance - mll;
  const ratio = trailing > 0 ? cushion / trailing : 1;
  if (ratio < 0.1) return "text-bearish";
  if (ratio < 0.25) return "text-warning";
  return "text-fg-primary";
}

function BreachedPill() {
  return (
    <span
      className="self-center px-1.5 py-0.5 border border-bearish text-bearish uppercase tracking-label-up"
      style={{ borderRadius: 0, fontSize: 9, fontWeight: 500 }}
      title="Balance is below the trailing maximum-loss limit."
    >
      MLL BREACHED
    </span>
  );
}

function MetricLabelValue({
  label,
  value,
  signed,
  muted,
  valueClass: valueClassOverride,
}: {
  label: string;
  value: string;
  signed?: number;
  muted?: boolean;
  /** Tailwind class override; wins over signed/muted defaults. */
  valueClass?: string;
}) {
  const valueClass =
    valueClassOverride ??
    (signed !== undefined
      ? signed > 0
        ? "text-bullish"
        : signed < 0
          ? "text-bearish"
          : "text-fg-primary"
      : muted
        ? "text-fg-tertiary-2"
        : "text-fg-primary");
  return (
    <div
      className="flex flex-col items-end leading-tight px-1"
      style={{ minWidth: 72 }}
    >
      <span
        className="uppercase tracking-label-up text-fg-tertiary-2"
        style={{ fontSize: 9, letterSpacing: "0.08em" }}
      >
        {label}
      </span>
      <span className={`text-tiny font-medium ${valueClass}`} style={{ fontSize: 12 }}>
        {value}
      </span>
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
    <div className="flex flex-col items-end leading-tight px-1">
      <span
        className="uppercase tracking-label-up text-fg-tertiary-2"
        style={{ fontSize: 9, letterSpacing: "0.08em" }}
      >
        MKT
      </span>
      <span
        className={`inline-flex items-center gap-1 px-1 border uppercase tracking-label-up tabular-nums ${cls}`}
        style={{ borderRadius: 0, fontSize: 9 }}
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
