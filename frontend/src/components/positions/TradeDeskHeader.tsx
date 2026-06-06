import { useEffect, useMemo, useState } from "react";

import { SymbolSearchModal } from "@/components/positions/SymbolSearchModal";
import { useAccountState, useSwitchTier } from "@/hooks/useAccountState";
import { useMarketStatus } from "@/hooks/useMarket";
import { useTickerDetail } from "@/hooks/useTickerDetail";
import { useTradeAnalytics } from "@/hooks/useTradeAnalytics";
import { useTrades } from "@/hooks/useTrades";
import { formatPercent, formatPrice } from "@/lib/formatters";
import { useActivePosition } from "@/stores/activePosition";
import { useUserSettings } from "@/stores/userSettings";
import { isZeroDteTrade } from "@/types/journal";
import type { TierKey, TierSpec } from "@/types/account";

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
      className="flex items-center gap-3 border-b border-hairline bg-tier-1 px-3 shrink-0 relative"
      style={{ height: 64 }}
    >
      <TierPill />
      <SearchTrigger
        symbol={symbol}
        onClick={() => setSearchOpen(true)}
      />
      <PriceReadout symbol={symbol} />
      <div className="ml-auto flex items-center" style={{ gap: 8 }}>
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
      style={{ width: 220, fontSize: 13 }}
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
        style={{ fontSize: 10, lineHeight: 1.2 }}
      >
        /
      </kbd>
    </button>
  );
}

/** Combine-tier indicator + switcher. Restyled to the new pill chrome. */
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
          "h-10 px-3 rounded-btn uppercase tracking-label-up tabular-nums",
          "flex items-center gap-2 transition-colors duration-100",
          breached
            ? "bg-tier-2 border border-bearish text-bearish"
            : "bg-tier-2 border border-tier-3 text-fg-primary hover:bg-tier-3",
        ].join(" ")}
        style={{ fontSize: 12, fontWeight: 500 }}
        aria-haspopup="listbox"
        aria-expanded={open}
        title="Active combine tier — click to switch"
      >
        <span>{tierKey} Combine</span>
        <span className="text-fg-tertiary-2" style={{ fontSize: 10 }}>
          ▾
        </span>
      </button>
      {open && tiers.length > 0 && (
        <div
          role="listbox"
          className="absolute left-0 top-full mt-1 z-30 bg-tier-2 border border-tier-3 rounded-btn overflow-hidden"
          style={{ minWidth: 180 }}
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
                  "w-full text-left px-3 py-1.5 text-tiny tabular-nums",
                  active ? "text-amber bg-tier-3" : "text-fg-secondary hover:bg-tier-3 hover:text-fg-primary",
                ].join(" ")}
              >
                <div className="uppercase tracking-label-up" style={{ fontSize: 11 }}>
                  {t.key} Combine
                </div>
                <div className="text-fg-tertiary-2" style={{ fontSize: 10 }}>
                  ${(t.starting_balance / 1000).toFixed(0)}K · −${t.trailing_distance.toLocaleString()} MLL
                </div>
              </button>
            );
          })}
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
        style={{ fontSize: 10 }}
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
  const activeTradeId = useActivePosition((s) => s.tradeId);
  const scrubberDte = useActivePosition((s) => s.scrubberDte);
  const elapsedHours = useActivePosition((s) => s.elapsedHours);
  const dllOverrides = useUserSettings((s) => s.dllOverrides);
  const activeTier = (account?.active_tier ?? "50K") as TierKey;

  // Tier-filtered active trade. If the active trade was opened on a
  // different combine than the one currently selected, it must not
  // contribute its UPL to this tier's header — clear the analytics
  // query's enabling condition by treating it as no-trade.
  const activeTrade = useMemo(
    () =>
      (tradesData?.trades ?? []).find(
        (t) => t.id === activeTradeId && (t.tier ?? "50K") === activeTier,
      ) ?? null,
    [tradesData, activeTradeId, activeTier],
  );
  const isIntraday = useMemo(() => isZeroDteTrade(activeTrade), [activeTrade]);
  // Only fetch + use analytics when the active trade matches the
  // active tier. Passing null disables the query — UPL stays at 0.
  const analyticsTradeId = activeTrade ? activeTradeId : null;
  const analyticsQuery = useTradeAnalytics(analyticsTradeId, scrubberDte, {
    intraday: isIntraday,
    elapsedHours,
  });
  const upl = analyticsQuery.data?.unrealized_pnl ?? 0;
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
  const mll = account?.mll ?? 0;
  const trailing =
    account?.tiers.find((t) => t.key === activeTier)?.trailing_distance ?? 1;
  const mllTone = mllToneClass(bal, mll, trailing);
  const breached = bal < mll;

  // DLL budget — user can override per-tier in Settings; default falls
  // back to the active tier's spec (Topstep-aligned 3% of starting
  // balance, served by the backend). Display-only — no enforcement.
  const dllBudget =
    dllOverrides[activeTier] ??
    account?.tiers.find((t) => t.key === activeTier)?.dll_amount ??
    account?.dll_budget ??
    0;
  // dll_used from backend is realized-only. Fold in any negative UPL
  // from the active position on this tier (positive UPL doesn't reduce
  // DLL_used — see services/account_tiers, the spec). Mirrors how BAL
  // folds UPL on top of the realized-only balance.
  const dllUsed = Math.max(0, (account?.dll_used ?? 0) + Math.max(0, -upl));
  const dllTone = dllToneClass(dllUsed, dllBudget);
  const dllHit = dllBudget > 0 && dllUsed > dllBudget;

  return (
    <>
      <MetricPill label="BAL" value={formatDollar(bal)} />
      <MetricPill label="MLL" value={formatDollar(mll)} valueClass={mllTone}>
        {breached && (
          <span
            className="ml-1 inline-flex items-center px-1 border border-bearish text-bearish uppercase tracking-label-up rounded-btn"
            style={{ fontSize: 8, height: 14 }}
            title="Balance is below the trailing maximum-loss limit."
          >
            BREACH
          </span>
        )}
      </MetricPill>
      <MetricPill
        label="DLL"
        value={formatDllUsage(dllUsed, dllBudget)}
        valueClass={dllTone}
        title={
          dllHit
            ? "Daily loss limit hit — display only, trade open is not blocked."
            : "Daily loss limit — resets at the next ET trading day."
        }
      >
        {dllHit && (
          <span
            className="ml-1 inline-flex items-center px-1 border border-bearish text-bearish uppercase tracking-label-up rounded-btn"
            style={{ fontSize: 8, height: 14 }}
            title="Daily loss limit hit — display only, trade open is not blocked."
          >
            DLL HIT
          </span>
        )}
      </MetricPill>
      <MetricPill
        label="RP&L"
        value={formatSigned(todayRpl)}
        signed={todayRpl}
      />
      <MetricPill label="UP&L" value={formatSigned(upl)} signed={upl} />
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
  children?: React.ReactNode;
}

function MetricPill({
  label,
  value,
  signed,
  valueClass: valueClassOverride,
  title,
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
      className="bg-tier-2 border border-tier-3 rounded-btn px-2.5 py-1 flex flex-col leading-tight"
      style={{ height: 44, minWidth: 110 }}
      title={title}
    >
      <span
        className="uppercase tracking-label-up text-fg-tertiary-2"
        style={{ fontSize: 10, letterSpacing: "0.08em" }}
      >
        {label}
      </span>
      <span
        className={`tabular-nums font-medium ${valueClass}`}
        style={{ fontSize: 15, marginTop: 2 }}
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
      className="bg-tier-2 border border-tier-3 rounded-btn px-2.5 py-1 flex flex-col leading-tight"
      style={{ height: 44, minWidth: 150 }}
      title={status?.label}
    >
      <span
        className="uppercase tracking-label-up text-fg-tertiary-2"
        style={{ fontSize: 10, letterSpacing: "0.08em" }}
      >
        MKT
      </span>
      <span
        className={`tabular-nums font-medium uppercase tracking-label-up ${tone}`}
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
