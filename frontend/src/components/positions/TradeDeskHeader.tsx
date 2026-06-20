import { useEffect, useMemo, useState } from "react";
import { keepPreviousData, useQueries } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";

import { SymbolSearchModal } from "@/components/positions/SymbolSearchModal";
import { useAccountState } from "@/hooks/useAccountState";
import { useActivateCombine } from "@/hooks/useCombines";
import { useCombineStatus } from "@/hooks/useCombineStatus";
import { useMarketStatus } from "@/hooks/useMarket";
import { useTickerDetail } from "@/hooks/useTickerDetail";
import { useTrades } from "@/hooks/useTrades";
import { fetchTradeAnalytics } from "@/lib/api";
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

  // Global keyboard shortcuts: "/" or Cmd/Ctrl+K opens the modal from
  // anywhere on the page. We skip the shortcut if the user is typing
  // in another input (e.g. the trade-entry form) so "/" still types a
  // literal slash where it should.
  useEffect(() => {
    function handle(e: KeyboardEvent) {
      const targetTag = (e.target as HTMLElement | null)?.tagName ?? "";
      const isEditable =
        targetTag === "INPUT" ||
        targetTag === "TEXTAREA" ||
        (e.target as HTMLElement | null)?.isContentEditable === true;
      const isCmdK =
        (e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k";
      const isSlash = e.key === "/" && !isEditable;
      if (isCmdK || isSlash) {
        e.preventDefault();
        setSearchOpen(true);
      }
    }
    window.addEventListener("keydown", handle);
    return () => window.removeEventListener("keydown", handle);
  }, []);

  return (
    <header
      className="flex flex-wrap md:flex-nowrap items-center gap-2 border-b border-hairline bg-tier-1 px-3 py-2 md:py-0 min-h-[64px] md:h-16 shrink-0 relative"
    >
      <CombineSelector />
      <SearchTrigger
        symbol={symbol}
        onClick={() => setSearchOpen(true)}
      />
      <PriceReadout symbol={symbol} />
      <div className="ml-auto flex items-center" style={{ gap: 6 }}>
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

/**
 * Combine selector — Topstep-style account dropdown.
 *
 * Lists every combine the user owns (name | account code, tier,
 * status badge), active one highlighted; switching activates via
 * POST /api/combines/{id}/activate with a direct cache swap. With
 * zero combines (fresh signup) the pill becomes a START A COMBINE CTA.
 */
function CombineSelector() {
  const { data, isError } = useAccountState();
  const activate = useActivateCombine();
  const [open, setOpen] = useState(false);
  const navigate = useNavigate();

  const noCombine = isError || data?.combine_id == null;
  if (noCombine) {
    return (
      <button
        type="button"
        onClick={() => navigate("/combines/new")}
        className="h-10 px-3 rounded-btn uppercase tracking-label-up flex items-center gap-2 border border-amber text-amber bg-tier-2 hover:bg-tier-3 transition-colors duration-100"
        style={{ fontSize: 12, fontWeight: 500 }}
        title="You don't own a combine yet — start one to unlock trading"
      >
        + Start a combine
      </button>
    );
  }

  const combines = data?.combines ?? [];
  const breached = data ? data.balance < data.mll : false;
  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className={[
          "h-10 px-3 rounded-btn tabular-nums",
          "flex items-center gap-2 transition-colors duration-100",
          breached
            ? "bg-tier-2 border border-bearish text-bearish"
            : "bg-tier-2 border border-tier-3 text-fg-primary hover:bg-tier-3",
        ].join(" ")}
        style={{ fontSize: 12, fontWeight: 500 }}
        aria-haspopup="listbox"
        aria-expanded={open}
        title={`${data?.account_code ?? ""} — click to switch combines`}
      >
        <span className="uppercase tracking-label-up truncate" style={{ maxWidth: 132 }}>
          {data?.combine_name ?? "Combine"}
        </span>
        <span className="text-fg-tertiary-2" style={{ fontSize: 12 }}>
          ▾
        </span>
      </button>
      {open && (
        <div
          role="listbox"
          className="absolute left-0 top-full mt-1 z-30 bg-tier-2 border border-tier-3 rounded-btn overflow-hidden"
          style={{ minWidth: 280 }}
        >
          {combines.map((c) => {
            const active = c.id === data?.combine_id;
            const archived = c.status === "archived";
            return (
              <button
                key={c.id}
                type="button"
                disabled={archived}
                onClick={() => {
                  if (!active && !archived) activate.mutate(c.id);
                  setOpen(false);
                }}
                className={[
                  "w-full text-left px-3 py-1.5 text-tiny tabular-nums",
                  archived
                    ? "text-fg-disabled cursor-not-allowed"
                    : active
                      ? "text-amber bg-tier-3"
                      : "text-fg-secondary hover:bg-tier-3 hover:text-fg-primary",
                ].join(" ")}
              >
                <div className="flex items-center gap-2">
                  <span className="uppercase tracking-label-up" style={{ fontSize: 11 }}>
                    {c.name}
                  </span>
                  {archived && (
                    <span
                      className="border border-tier-3 text-fg-tertiary-2 px-1 uppercase tracking-label-up"
                      style={{ fontSize: 11, borderRadius: 2 }}
                    >
                      archived
                    </span>
                  )}
                </div>
                <div className="text-fg-tertiary-2" style={{ fontSize: 12 }}>
                  {c.tier} · {c.account_code}
                </div>
              </button>
            );
          })}
          <button
            type="button"
            onClick={() => {
              setOpen(false);
              navigate("/combines/new");
            }}
            className="w-full text-left px-3 py-1.5 text-tiny text-amber hover:bg-tier-3 border-t border-tier-3 uppercase tracking-label-up"
            style={{ fontSize: 12 }}
          >
            + Start a new combine
          </button>
        </div>
      )}
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
    </div>
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

  // Header UP&L is an account-level number: the live unrealized P&L
  // summed across ALL open positions on the active tier, independent of
  // which row (if any) is selected on the chart. This is why the pill no
  // longer reads $0.00 just because nothing is selected. We deliberately
  // use live analytics (no scrubber override) — the theta scrubber is a
  // per-position what-if for the chart/payoff panel, not something that
  // should move the account's balance readout.
  const openPositions = useMemo(
    () =>
      (tradesData?.trades ?? []).filter(
        (t) => t.status === "open" && (t.tier ?? "50K") === activeTier,
      ),
    [tradesData, activeTier],
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

  const bal = (account?.balance ?? 0) + upl;
  const trailing =
    account?.tiers.find((t) => t.key === activeTier)?.trailing_distance ?? 1;
  // Combine engine verdict — floors tested CONTINUOUSLY against live net
  // (realized + URPL). The MLL pill is the hero ("how close to blowing
  // up"); FAILED is permanent, DAY-LOCK lifts at the 5pm-PT settlement.
  const combine = useCombineStatus();
  const mll = combine.mllFloor;
  const cushion = combine.mllCushion;
  const mllTone =
    combine.status === "failed"
      ? "text-bearish font-medium"
      : mllToneClass(combine.balanceLive, combine.mllFloor, trailing);
  // Profit-target pole — how close to PASSING.
  const tgtTone = combine.passed
    ? "text-bullish font-medium"
    : combine.passBlockedReason
      ? "text-warning"
      : combine.targetProximity >= 1
        ? "text-bullish"
        : combine.targetProximity >= 0.5
          ? "text-fg-primary"
          : "text-fg-secondary";
  const passBadge = combine.passed
    ? "PASSED"
    : combine.targetMet && !combine.minDaysMet
      ? "MIN DAYS"
      : combine.targetMet && !combine.consistencyOk
        ? "CONSIST"
        : combine.targetMet
          ? "TARGET"
          : null;

  // DLL budget — the backend resolves the active combine's budget (the
  // user's per-tier Settings override clamped to the band, else the tier
  // default) and enforces it on opens, so we read it straight off the snapshot.
  const dllBudget = account?.dll_budget ?? 0;
  // dll_used from backend is realized-only. Fold in any negative UPL
  // from the active position on this tier (positive UPL doesn't reduce
  // DLL_used — see services/account_tiers, the spec). Mirrors how BAL
  // folds UPL on top of the realized-only balance.
  const dllUsed = Math.max(0, (account?.dll_used ?? 0) + Math.max(0, -upl));
  const dllTone = dllToneClass(dllUsed, dllBudget);
  const dllHit = combine.dayLocked;

  return (
    <>
      <MetricPill label="BAL" value={formatDollar(bal)} />
      <MetricPill
        label="MLL"
        value={formatDollar(mll)}
        valueClass={mllTone}
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
      <MetricPill
        label="TGT"
        value={formatDollar(combine.realizedProfit)}
        valueClass={tgtTone}
        className="hidden min-[1280px]:flex"
        title={`Profit target ${formatDollar(combine.profitTarget)} (6%). Realized ${formatDollar(
          combine.realizedProfit,
        )}${combine.targetMet ? " — target MET" : ""}. Min ${combine.minTradingDays} trading days (traded ${combine.daysTraded}). Consistency: largest day ${Math.round(
          combine.largestDayPct,
        )}% of profit${combine.consistencyOk ? " (ok)" : " — exceeds 50%"}.${
          combine.passBlockedReason ? " " + combine.passBlockedReason : ""
        }`}
      >
        <span className="ml-1 tabular-nums text-fg-tertiary-2" style={{ fontSize: 11 }}>
          / ${Math.round(combine.profitTarget / 1000)}K · D{combine.daysTraded}/
          {combine.minTradingDays}
        </span>
        {passBadge && (
          <span
            className={`ml-1 inline-flex items-center px-1 border uppercase tracking-label-up rounded-btn ${
              combine.passed
                ? "border-bullish text-bullish"
                : passBadge === "TARGET"
                  ? "border-bullish text-bullish"
                  : "border-warning text-warning"
            }`}
            style={{ fontSize: 11, height: 14 }}
            title={
              combine.passBlockedReason ??
              (combine.passed ? "Combine PASSED." : "Profit target reached.")
            }
          >
            {passBadge}
          </span>
        )}
      </MetricPill>
      <MetricPill
        label="DLL"
        value={formatDllUsage(dllUsed, dllBudget)}
        valueClass={dllTone}
        title={
          dllHit
            ? "Daily loss limit hit — DAY LOCK: no further trading today (account survives). Lifts at the 5pm-PT settlement."
            : "Daily loss limit (live, incl. open URPL) — resets at the 5pm-PT settlement."
        }
      >
        {dllHit && (
          <span
            className="ml-1 inline-flex items-center px-1 border border-bearish text-bearish uppercase tracking-label-up rounded-btn"
            style={{ fontSize: 11, height: 14 }}
            title="Daily loss limit hit — DAY LOCK: no further trading today."
          >
            DAY LOCK
          </span>
        )}
      </MetricPill>
      {/* Progressive disclosure so the header never clips: BAL/MLL/DLL/MKT
          are always shown; TGT joins at ≥1280px; RP&L/UP&L (fully derivable
          from the bottom strip's TODAY column + the position panel) only
          appear at ≥1560px, where there's real room for all seven. */}
      <MetricPill
        label="RP&L"
        value={formatSigned(todayRpl)}
        signed={todayRpl}
        className="hidden min-[1560px]:flex"
      />
      <MetricPill
        label="UP&L"
        value={formatSigned(upl)}
        signed={upl}
        className="hidden min-[1560px]:flex"
      />
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
  children?: React.ReactNode;
}

function MetricPill({
  label,
  value,
  signed,
  valueClass: valueClassOverride,
  title,
  className,
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
      className={`bg-tier-2 border border-tier-3 rounded-btn px-2 py-1 flex-col leading-tight shrink-0 ${className ?? "flex"}`}
      style={{ height: 44, minWidth: 72 }}
      title={title}
    >
      <span
        className="uppercase tracking-label-up text-fg-tertiary-2"
        style={{ fontSize: 12, letterSpacing: "0.08em" }}
      >
        {label}
      </span>
      <span
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
  const tone = isOpen ? "text-bullish" : "text-bearish";
  return (
    <div
      className="bg-tier-2 border border-tier-3 rounded-btn px-2 py-1 flex flex-col leading-tight shrink-0"
      style={{ height: 44 }}
      title={status?.label}
    >
      <span
        className="uppercase tracking-label-up text-fg-tertiary-2"
        style={{ fontSize: 12, letterSpacing: "0.08em" }}
      >
        MKT
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
