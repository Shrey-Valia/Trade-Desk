import { useEffect, useMemo, useState } from "react";
import { keepPreviousData, useQueries } from "@tanstack/react-query";
import { AlertsBell } from "@/components/alerts/AlertsBell";
import { CombineSwitcher } from "@/components/combines/CombineSwitcher";
import { SymbolSearchModal } from "@/components/positions/SymbolSearchModal";
import { useAccountState } from "@/hooks/useAccountState";
import { useCachedChainTable } from "@/hooks/useChainTable";
import { useCombineStatus } from "@/hooks/useCombineStatus";
import { usePreLiquidationWarnings } from "@/hooks/usePreLiquidationWarnings";
import { useMarketStatus } from "@/hooks/useMarket";
import { useTickerDetail } from "@/hooks/useTickerDetail";
import { useTrades } from "@/hooks/useTrades";
import { fetchTradeAnalytics } from "@/lib/api";
import { isActiveCombineTrade } from "@/lib/combineScope";
import { expectedMoveFromChain } from "@/lib/expectedMove";
import { formatPercent, formatPrice } from "@/lib/formatters";
import { isZeroDteTrade } from "@/types/journal";
import type { TierKey } from "@/types/account";

/**
 * Persistent Trade-Desk top header (64px).
 *
 *   left   : combine-tier pill (50K COMBINE ▾) — slightly larger,
 *            bg-tier-2 fill, 4px radius, monospace.
 *   mid    : ticker search box (replaces SPY/QQQ/IWM buttons) +
 *            live price + change%.
 *   right  : Topstep-style metric pills — BAL · MLL · RP&L · UP&L · MKT.
 *
 * The Trade Desk wordmark is RETIRED from the header — the new
 * TradeDeskMark sits in the left rail. The header is for trading
 * state, not branding.
 */
interface Props {
  symbol: string | null;
  onSymbolChange: (s: string) => void;
}

export function TradeDeskHeader({ symbol, onSymbolChange }: Props) {
  const [searchOpen, setSearchOpen] = useState(false);

  // Symbol-search shortcut: "/" opens the modal from anywhere on the page.
  // We skip it while the user is typing in another input (e.g. the trade-entry
  // form) so "/" still types a literal slash there. ⌘K/Ctrl-K is now owned by
  // the WS6 command palette (whose first entry is symbol search), so it's no
  // longer handled here.
  useEffect(() => {
    function handle(e: KeyboardEvent) {
      const targetTag = (e.target as HTMLElement | null)?.tagName ?? "";
      const isEditable =
        targetTag === "INPUT" ||
        targetTag === "TEXTAREA" ||
        (e.target as HTMLElement | null)?.isContentEditable === true;
      if (e.key === "/" && !isEditable) {
        e.preventDefault();
        setSearchOpen(true);
      }
    }
    window.addEventListener("keydown", handle);
    return () => window.removeEventListener("keydown", handle);
  }, []);

  return (
    <header
      className="flex flex-wrap items-center gap-2 border-b border-hairline bg-tier-1 px-3 py-2 min-h-[64px] md:min-h-16 shrink-0 relative"
    >
      <CombineSwitcher size="md" />
      <SearchTrigger
        symbol={symbol}
        onClick={() => setSearchOpen(true)}
      />
      <PriceReadout symbol={symbol} />
      <div className="ml-auto flex flex-wrap items-center justify-end gap-1.5 min-w-0">
        <AlertsBell symbol={symbol} />
        <MetricPills />
      </div>
      <SymbolSearchModal
        open={searchOpen}
        activeSymbol={symbol}
        onClose={() => setSearchOpen(false)}
        onSelect={(sym) => onSymbolChange(sym)}
      />
    </header>
  );
}

/**
 * Replaces the old inline TickerSearchBox dropdown. Renders as a
 * button-shaped readout: search icon + "{SYMBOL} · search ticker..." +
 * "⌘K" hint. Click opens the modal; same shortcut keys work too.
 */
function SearchTrigger({
  symbol,
  onClick,
}: {
  symbol: string | null;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={[
        "h-9 pl-2.5 pr-2 bg-tier-2 border rounded-btn",
        "border-tier-3 hover:border-tier-4 hover:bg-tier-3",
        "flex items-center gap-2 text-left transition-colors duration-75",
      ].join(" ")}
      style={{ width: 184, fontSize: 13 }}
      aria-label="Open symbol search"
      title="Open symbol search (/ or ⌘K)"
    >
      <span
        aria-hidden
        className="text-fg-tertiary-2"
        style={{ fontSize: 12 }}
      >
        ⌕
      </span>
      <span
        className="text-fg-tertiary-2 font-mono tabular-nums truncate flex-1"
      >
        {symbol ? `${symbol} · search ticker…` : "Search ticker…"}
      </span>
      <kbd
        className="text-fg-tertiary-2 border border-tier-3 px-1 rounded-btn font-mono"
        style={{ fontSize: 12, lineHeight: 1.2 }}
      >
        /
      </kbd>
    </button>
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
    <div className="flex items-baseline gap-2 tabular-nums">
      <span
        className="uppercase tracking-label-up text-fg-tertiary-2"
        style={{ fontSize: 12 }}
      >
        {symbol}
      </span>
      <span className="text-fg-primary font-medium" style={{ fontSize: 16 }}>
        {formatPrice(detail.price)}
      </span>
      <span className={changeClass} style={{ fontSize: 11 }}>
        {sign}
        {detail.change_dollar.toFixed(2)} ({formatPercent(detail.change_pct)})
      </span>
      <ExpectedMovePill symbol={symbol} spot={detail.price} />
      <FreshnessPill asOf={detail.as_of ?? null} servedStale={detail.served_stale ?? false} />
    </div>
  );
}

/**
 * Expected-move readout (ToS "MMM"-style): the ATM straddle mid off the
 * chain table the terminal ALREADY polls (passive cache read — no extra
 * request). "±$X.XX (±Y.Y%)" is the options market's implied move by
 * today's close; it visibly shrinks on each chain refetch as theta burns.
 * Hidden entirely when the chain or spot isn't available.
 */
function ExpectedMovePill({ symbol, spot }: { symbol: string; spot: number }) {
  const chain = useCachedChainTable(symbol);
  const em = useMemo(
    () => expectedMoveFromChain(chain?.rows, spot),
    [chain, spot],
  );
  if (!em) return null;
  return (
    <span
      className="text-fg-secondary tabular-nums whitespace-nowrap"
      style={{ fontSize: 11 }}
      title={`Expected move to today's close — the ATM (${em.strike}) straddle price: what the options market charges for a move in either direction by the bell. Shrinks through the day as theta burns.`}
      aria-label={`Expected move plus or minus $${em.em.toFixed(2)} (${em.pct.toFixed(1)} percent)`}
    >
      EM ±${em.em.toFixed(2)}{" "}
      <span className="text-fg-tertiary-2">(±{em.pct.toFixed(1)}%)</span>
    </span>
  );
}

/**
 * Data-freshness readout beside the price — every real terminal shows one.
 * Normal: a quiet "as of HH:MM:SS". Degraded (server flagged served_stale,
 * or the stamp is old): a loud STALE badge — the trader must never watch a
 * frozen price believing it's live.
 */
function FreshnessPill({ asOf, servedStale }: { asOf: string | null; servedStale: boolean }) {
  const STALE_AFTER_MS = 60_000;
  const ageMs = asOf ? Date.now() - new Date(asOf).getTime() : null;
  const isStale = servedStale || (ageMs != null && ageMs > STALE_AFTER_MS);
  if (asOf == null && !servedStale) return null;
  if (isStale) {
    return (
      <span
        className="inline-flex items-center px-1 border border-bearish text-bearish uppercase tracking-label-up rounded-btn"
        style={{ fontSize: 11, height: 14 }}
        title={
          servedStale
            ? "The data feed stalled — this is the last good snapshot, not a live price."
            : `Last update ${formatClockEt(asOf!)} ET — older than ${STALE_AFTER_MS / 1000}s.`
        }
      >
        STALE
      </span>
    );
  }
  return (
    <span
      className="text-fg-tertiary-2"
      style={{ fontSize: 11 }}
      title="Timestamp of the quote behind this price."
    >
      as of {formatClockEt(asOf!)}
    </span>
  );
}

/**
 * Topstep-style metric pills cluster — BAL / MLL / RP&L / UP&L / MKT.
 *
 * Each pill is bg-tier-2 with a 1px bg-tier-3 border, 4px radius,
 * ~110×44. Label (10px uppercase) top-left, value (15px) below.
 */
function MetricPills() {
  const { data: account } = useAccountState();
  const { data: tradesData } = useTrades();
  const activeTier = (account?.active_tier ?? "50K") as TierKey;
  const combineId = account?.combine_id;

  // Header UP&L is an account-level number: the live unrealized P&L
  // summed across ALL open positions on the ACTIVE COMBINE, independent of
  // which row (if any) is selected on the chart. This is why the pill no
  // longer reads $0.00 just because nothing is selected. We deliberately
  // use live analytics (no scrubber override) — the theta scrubber is a
  // per-position what-if for the chart/payoff panel, not something that
  // should move the account's balance readout. Scope by combine id (not tier)
  // so a second same-tier combine's UPL never bleeds into this header.
  const openPositions = useMemo(
    () =>
      (tradesData?.trades ?? []).filter(
        (t) => t.status === "open" && isActiveCombineTrade(t, combineId, activeTier),
      ),
    [tradesData, activeTier, combineId],
  );
  // One analytics query per open position. Keys/staleTime/poll cadence
  // mirror useTradeAnalytics so the cache is shared with the chart's
  // per-position query; 0DTE positions keep their 5s live poll.
  const positionAnalytics = useQueries({
    queries: openPositions.map((t) => {
      const intraday = isZeroDteTrade(t);
      return {
        queryKey: ["trade-analytics", t.id, null, intraday ? "intraday" : "day", null],
        queryFn: () => fetchTradeAnalytics(t.id, { dteOverride: null, elapsedHours: null }),
        staleTime: intraday ? 3_000 : 10_000,
        refetchInterval: intraday ? 5_000 : (false as const),
        placeholderData: keepPreviousData,
      };
    }),
  });
  const upl = useMemo(
    () =>
      positionAnalytics.reduce(
        (sum, q) => sum + (q.data?.unrealized_pnl ?? 0),
        0,
      ),
    [positionAnalytics],
  );
  // Daily RPL comes straight from the backend (signed realized within the
  // current 5pm-PT trading day) so it matches the DLL / settlement window —
  // not a calendar-day client sum.
  const rpl = account?.today_realized ?? 0;
  const eod = account?.eod_balance ?? 0;
  // BAL is the live balance. Kept as balance + URPL (robust: the backend
  // balance is always present), which equals EOD + RPL + URPL by construction
  // (balance == eod_balance + today_realized). The tooltip shows that split.
  const bal = (account?.balance ?? 0) + upl;
  const balTitle = `Balance = EOD ${formatDollar(eod)} + RPL ${formatSigned(
    rpl,
  )} + URPL ${formatSigned(upl)}`;
  const trailing =
    account?.tiers.find((t) => t.key === activeTier)?.trailing_distance ?? 1;
  // Combine engine verdict — floors tested CONTINUOUSLY against live net
  // (realized + URPL). The MLL pill is the hero ("how close to blowing
  // up"); FAILED is permanent, DAY-LOCK lifts at the 5pm-PT settlement.
  const combine = useCombineStatus();
  // Pre-liquidation early warnings: fires sticky toasts once per threshold
  // crossing and returns the urgency flags that pulse the MLL/DLL pills.
  const urgency = usePreLiquidationWarnings();
  const mll = combine.mllFloor;
  const cushion = combine.mllCushion;
  const mllTone =
    combine.status === "failed"
      ? "text-bearish font-medium"
      : mllToneClass(combine.balanceLive, combine.mllFloor, trailing);

  // DLL budget — the backend resolves the active combine's budget (the
  // user's per-tier Settings override clamped to the band, else the tier
  // default) and enforces it on opens, so we read it straight off the snapshot.
  const dllBudget = account?.dll_budget ?? 0;
  // dll_used from backend is realized-only. Fold in any negative UPL
  // from the active position on this tier (positive UPL doesn't reduce
  // DLL_used — see services/account_tiers, the spec). Mirrors how BAL
  // folds UPL on top of the realized-only balance.
  const dllUsed = Math.max(0, (account?.dll_used ?? 0) + Math.max(0, -upl));
  const dllDisabled = combine.dllDisabled;
  const dllTone = dllDisabled ? "text-fg-tertiary-2" : dllToneClass(dllUsed, dllBudget);
  const dllHit = combine.dayLocked;

  return (
    <>
      <MetricPill label="BAL" value={formatDollar(bal)} title={balTitle} />
      <MetricPill
        label="MLL"
        value={formatDollar(mll)}
        valueClass={mllTone}
        pulse={urgency.mllNearFloor}
        title={`Fixed-intraday MLL floor — how close to blowing up. Live cushion ${
          cushion >= 0 ? "+" : "−"
        }$${Math.round(Math.abs(cushion)).toLocaleString()} (balance incl. open URPL vs the floor). Re-baselines up only at the 5pm-PT settlement.`}
      >
        <span className="ml-1 tabular-nums text-fg-tertiary-2" style={{ fontSize: 11 }}>
          {cushion >= 0
            ? `+$${Math.round(cushion).toLocaleString()}`
            : `−$${Math.round(-cushion).toLocaleString()}`}
        </span>
        {combine.status === "failed" ? (
          <span
            className="ml-1 inline-flex items-center px-1 border border-bearish text-bearish uppercase tracking-label-up rounded-btn"
            style={{ fontSize: 11, height: 14 }}
            title="MLL floor breached — combine FAILED (permanent)."
          >
            FAILED
          </span>
        ) : cushion < 0 ? (
          <span
            className="ml-1 inline-flex items-center px-1 border border-bearish text-bearish uppercase tracking-label-up rounded-btn"
            style={{ fontSize: 11, height: 14 }}
            title="Live balance (incl. URPL) is below the MLL floor."
          >
            BREACH
          </span>
        ) : null}
      </MetricPill>
      {/* Daily P&L in place of the old TGT tile: realized (today, 5pm-PT
          window) + live unrealized across all open positions. BAL = EOD +
          RPL + URPL, so these two plus the EOD baseline reconcile to BAL. */}
      <MetricPill
        label="RP&L"
        value={formatSigned(rpl)}
        signed={rpl}
        className="hidden min-[1440px]:flex"
        title="Realized P&L today — closed trades in the current 5pm-PT trading day."
      />
      <MetricPill
        label="UP&L"
        value={formatSigned(upl)}
        signed={upl}
        className="hidden min-[1440px]:flex"
        title="Unrealized P&L — live, summed across all open positions on this tier."
      />
      <MetricPill
        label="DLL"
        value={dllDisabled ? "off" : formatDllUsage(dllUsed, dllBudget)}
        valueClass={dllTone}
        pulse={!dllDisabled && urgency.dllNearLimit}
        title={
          dllDisabled
            ? "Daily loss limit switched OFF for this tier (Settings → Risk). Only the MLL floor binds — matching Topstep, which dropped the DLL in 2024."
            : dllHit
              ? "Daily loss limit hit — DAY LOCK: no further trading today (account survives). Lifts at the 5pm-PT settlement."
              : "Daily loss limit (live, incl. open URPL) — resets at the 5pm-PT settlement."
        }
      >
        {dllDisabled ? (
          <span
            className="ml-1 inline-flex items-center px-1 border border-tier-3 text-fg-tertiary-2 uppercase tracking-label-up rounded-btn"
            style={{ fontSize: 11, height: 14 }}
            title="Daily loss limit disabled for this tier."
          >
            OFF
          </span>
        ) : dllHit ? (
          <span
            className="ml-1 inline-flex items-center px-1 border border-bearish text-bearish uppercase tracking-label-up rounded-btn"
            style={{ fontSize: 11, height: 14 }}
            title="Daily loss limit hit — DAY LOCK: no further trading today."
          >
            DAY LOCK
          </span>
        ) : null}
      </MetricPill>
      <MarketPill />
    </>
  );
}

function mllToneClass(balance: number, mll: number, trailing: number): string {
  if (balance < mll) return "text-bearish font-medium";
  const cushion = balance - mll;
  const ratio = trailing > 0 ? cushion / trailing : 1;
  if (ratio < 0.1) return "text-bearish";
  if (ratio < 0.25) return "text-warning";
  return "text-fg-primary";
}

/** DLL tone — used/budget thresholds: <50% normal, 50-90% warn, 90-100%
 * bear-red, >100% bright-bearish font-medium with the "DLL HIT" badge. */
function dllToneClass(used: number, budget: number): string {
  if (budget <= 0) return "text-fg-primary";
  const ratio = used / budget;
  if (ratio > 1) return "text-bearish font-medium";
  if (ratio >= 0.9) return "text-bearish";
  if (ratio >= 0.5) return "text-warning";
  return "text-fg-primary";
}

interface MetricPillProps {
  label: string;
  value: string;
  signed?: number;
  valueClass?: string;
  title?: string;
  /** Extra classes on the pill shell — used to priority-hide the
   * derivable pills (RP&L/UP&L) at narrow widths. */
  className?: string;
  /** When true, the pill border pulses bearish-red — the pre-liquidation
   * urgency state (MLL cushion <15% / DLL >80%). */
  pulse?: boolean;
  children?: React.ReactNode;
}

function MetricPill({
  label,
  value,
  signed,
  valueClass: valueClassOverride,
  title,
  className,
  pulse,
  children,
}: MetricPillProps) {
  const valueClass =
    valueClassOverride ??
    (signed !== undefined
      ? signed > 0
        ? "text-bullish"
        : signed < 0
          ? "text-bearish"
          : "text-fg-primary"
      : "text-fg-primary");
  return (
    <div
      className={`bg-tier-2 border border-tier-3 rounded-btn px-2 py-1 flex-col leading-tight shrink-0 ${
        pulse ? "td-pulse-warn" : ""
      } ${className ?? "flex"}`}
      style={
        pulse
          ? // Drive the keyframe's border/shadow to bearish-red for danger.
            ({ height: 44, minWidth: 72, ["--td-pulse-color" as string]: "#E5484D" } as React.CSSProperties)
          : { height: 44, minWidth: 72 }
      }
      title={title}
    >
      <span
        className="uppercase tracking-label-up text-fg-tertiary-2"
        style={{ fontSize: 12, letterSpacing: "0.08em" }}
      >
        {label}
      </span>
      <span
        // a11y (WS6): the live risk/P&L readouts update on the account poll;
        // aria-live=polite so a screen reader announces a changed balance, MLL
        // cushion, or P&L without stealing focus mid-task. The label is read
        // alongside the value so "BAL $52,310" is announced, not a bare number.
        aria-live="polite"
        aria-label={`${label} ${value}`}
        className={`tabular-nums font-medium whitespace-nowrap ${valueClass}`}
        style={{ fontSize: 13, marginTop: 2 }}
      >
        {value}
        {children}
      </span>
    </div>
  );
}

function MarketPill() {
  const { data: status } = useMarketStatus();
  const isOpen = status?.status === "open";
  const earlyClose = status?.is_early_close === true;
  const detail = useMemo(() => {
    if (!status) return "—";
    if (isOpen) {
      // On half days the close time IS the risk event — 0DTE settles at the
      // early bell, so lead with it.
      if (earlyClose && status.today_close) {
        return `early close ${formatClockEt(status.today_close)} ET`;
      }
      if (status.next_close) {
        return `until ${formatClockEt(status.next_close)} ET`;
      }
      return status.label;
    }
    if (status.next_open) {
      return `until ${formatClockEt(status.next_open)} ET`;
    }
    return status.label;
  }, [status, isOpen, earlyClose]);
  const tone = isOpen ? (earlyClose ? "text-warning" : "text-bullish") : "text-bearish";
  return (
    <div
      className="bg-tier-2 border border-tier-3 rounded-btn px-2 py-1 flex flex-col leading-tight shrink-0"
      style={{ height: 44 }}
      title={
        earlyClose && status?.today_close
          ? `Early close today — the session (and every 0DTE contract) ends at ${formatClockEt(status.today_close)} ET.`
          : status?.label
      }
    >
      <span
        className="uppercase tracking-label-up text-fg-tertiary-2"
        style={{ fontSize: 12, letterSpacing: "0.08em" }}
      >
        {earlyClose ? "MKT ⚠" : "MKT"}
      </span>
      <span
        className={`tabular-nums font-medium uppercase tracking-label-up whitespace-nowrap ${tone}`}
        style={{ fontSize: 11, marginTop: 4 }}
      >
        {isOpen ? "OPEN" : "CLOSED"}
        <span className="text-fg-tertiary-2 mx-1">·</span>
        <span style={{ textTransform: "lowercase" }}>{detail}</span>
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

/** "−$120 / $1,500" when used > 0; "$0 / $1,500" otherwise. Whole-dollar
 * formatting — DLL budgets are round numbers and the pill is narrow. */
function formatDllUsage(used: number, budget: number): string {
  const usedTxt =
    used > 0
      ? `−$${Math.round(used).toLocaleString("en-US")}`
      : "$0";
  const budgetTxt = `$${Math.round(budget).toLocaleString("en-US")}`;
  return `${usedTxt} / ${budgetTxt}`;
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
