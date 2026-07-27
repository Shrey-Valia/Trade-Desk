import { useEffect, useMemo, useState } from "react";
import { keepPreviousData, useQueries } from "@tanstack/react-query";
import { AlertsBell } from "@/components/alerts/AlertsBell";
import { CombineSwitcher } from "@/components/combines/CombineSwitcher";
import { NotificationsBell } from "@/components/notifications/NotificationsBell";
import { SymbolSearchModal } from "@/components/positions/SymbolSearchModal";
import { colors } from "@/lib/design";
import { useAccountState } from "@/hooks/useAccountState";
import { useCachedChainTable } from "@/hooks/useChainTable";
import { useCombineStatus } from "@/hooks/useCombineStatus";
import { usePortfolioGreeks } from "@/hooks/usePortfolioGreeks";
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
        <NotificationsBell />
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
  // Combine engine verdict — floors tested CONTINUOUSLY against live net
  // (realized + URPL). The CUSHION-to-MLL readout is the header HERO ("how
  // close to blowing up"); FAILED is permanent, DAY-LOCK lifts at 5pm-PT.
  const combine = useCombineStatus();
  // Pre-liquidation early warnings: fires sticky toasts once per threshold
  // crossing and returns the urgency flags that pulse the cushion / DLL.
  const urgency = usePreLiquidationWarnings();
  const mll = combine.mllFloor;
  const cushion = combine.mllCushion;

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
  const dllHit = combine.dayLocked;

  // Cold load: until useAccountState resolves every value falls back to 0, so
  // without this the hero would flash a zeroed-out account ($0.00 / MLL $0) for
  // a beat on first paint. Render a muted placeholder cluster instead.
  if (!account) {
    return <MetricPillsSkeleton />;
  }

  return (
    <div className="flex items-stretch gap-2.5">
      <CushionHero
        cushion={cushion}
        proximity={combine.mllProximity}
        floor={mll}
        status={combine.status}
        pulse={urgency.mllNearFloor}
      />
      <div className="flex items-center gap-3 pl-0.5">
        <MiniStat label="Bal" value={formatDollar(bal)} title={balTitle} />
        <MiniStat
          label="RP&L"
          value={formatSigned(rpl)}
          valueClass={signedClass(rpl)}
          title="Realized P&L today — closed trades in the current 5pm-PT trading day."
        />
        <MiniStat
          label="UP&L"
          value={formatSigned(upl)}
          valueClass={signedClass(upl)}
          title="Unrealized P&L — live, summed across all open positions on this tier."
        />
        <PortfolioGreeksMini openCount={openPositions.length} />
        {account?.buying_power != null && (
          <MiniStat
            label="BP"
            value={formatDollar(account.buying_power)}
            valueClass={
              account.buying_power <= 0 ? "text-bearish" : "text-fg-primary"
            }
            title={
              `Buying power for NEW opens = realized balance − margin committed ` +
              `($${(account.margin_used ?? 0).toFixed(0)} across open + working ` +
              `positions). Defined-risk structures require their max loss; naked ` +
              `short sides carry a Reg-T-style requirement. Open URPL is governed ` +
              `by the MLL/DLL gates, not folded in here.`
            }
          />
        )}
        <DllMini
          used={dllUsed}
          budget={dllBudget}
          disabled={dllDisabled}
          hit={dllHit}
          pulse={!dllDisabled && urgency.dllNearLimit}
        />
        <MiniMarket />
      </div>
    </div>
  );
}

function signedClass(v: number): string {
  return v > 0 ? "text-bullish" : v < 0 ? "text-bearish" : "text-fg-primary";
}

/**
 * Placeholder cluster shown while the account snapshot is still loading, so the
 * header never flashes a zeroed-out account on cold load. Mirrors the live
 * cluster's shape (hero block + a row of labelled pills) with muted em-dashes.
 */
function MetricPillsSkeleton() {
  const labels = ["Bal", "RP&L", "UP&L", "BP", "DLL", "MKT"];
  return (
    <div className="flex items-stretch gap-2.5" aria-busy="true">
      <div
        className="bg-tier-2 border border-tier-3 rounded-btn px-3 py-1.5 flex flex-col justify-center shrink-0"
        style={{ minWidth: 176 }}
      >
        <span
          className="uppercase tracking-label-up text-fg-tertiary-2"
          style={{ fontSize: 10, letterSpacing: "0.08em" }}
        >
          Cushion
        </span>
        <span
          className="tabular-nums text-fg-tertiary-2"
          style={{ fontSize: 15, marginTop: 2 }}
        >
          —
        </span>
      </div>
      <div className="flex items-center gap-3 pl-0.5">
        {labels.map((label) => (
          <MiniStat key={label} label={label} value="—" valueClass="text-fg-tertiary-2" />
        ))}
      </div>
    </div>
  );
}

/**
 * The HERO of the terminal header: cushion to the MLL floor — "how close to
 * blowing up" — as a dominant number with a green→amber→red buffer gauge. In a
 * trailing-max-loss product the distance to failure must be the loudest thing
 * on screen, not tile #2 of six identical pills.
 */
function cushionTone(
  status: string,
  proximity: number,
  cushion: number,
): { text: string; bar: string } {
  if (status === "failed" || cushion < 0)
    return { text: "text-breach", bar: colors.accentBreach };
  if (proximity < 0.1) return { text: "text-bearish", bar: colors.bearish };
  if (proximity < 0.25) return { text: "text-warning", bar: colors.warning };
  return { text: "text-bullish", bar: colors.bullish };
}

function CushionHero({
  cushion,
  proximity,
  floor,
  status,
  pulse,
}: {
  cushion: number;
  proximity: number;
  floor: number;
  status: string;
  pulse: boolean;
}) {
  const tone = cushionTone(status, proximity, cushion);
  const failed = status === "failed";
  const breach = cushion < 0;
  const pct = Math.max(0, Math.min(1, proximity)) * 100;
  const value =
    cushion >= 0
      ? `+$${Math.round(cushion).toLocaleString()}`
      : `−$${Math.round(-cushion).toLocaleString()}`;
  return (
    <div
      className={`bg-tier-2 border rounded-btn px-3 py-1.5 flex flex-col justify-center shrink-0 ${
        failed || breach ? "border-breach" : "border-tier-3"
      } ${pulse ? "td-pulse-warn" : ""}`}
      style={
        pulse
          ? ({ minWidth: 176, ["--td-pulse-color" as string]: colors.accentBreach } as React.CSSProperties)
          : { minWidth: 176 }
      }
      title={`Cushion to the MLL floor — how close to blowing up. Live balance (incl. open URPL) vs the fixed-intraday floor $${Math.round(
        floor,
      ).toLocaleString()}. Re-baselines up only at the 5pm-PT settlement.`}
    >
      <div className="flex items-center justify-between gap-3">
        <span
          className="uppercase tracking-label-up text-fg-tertiary-2 whitespace-nowrap"
          style={{ fontSize: 10, letterSpacing: "0.08em" }}
        >
          {failed ? "Account failed" : breach ? "Below floor" : "Cushion"}
        </span>
        <span className="text-fg-tertiary-2 tabular-nums whitespace-nowrap" style={{ fontSize: 10 }}>
          MLL ${Math.round(floor).toLocaleString()}
        </span>
      </div>
      <span
        aria-live="polite"
        aria-label={`Cushion to MLL floor ${value}`}
        className={`font-display tabular-nums ${tone.text}`}
        style={{ fontSize: 22, fontWeight: 600, lineHeight: 1.06, letterSpacing: "-0.01em", marginTop: 1 }}
      >
        {failed ? "FAILED" : value}
      </span>
      <div
        className="mt-1 overflow-hidden"
        style={{ height: 4, borderRadius: 2, background: colors.bgTier0 }}
      >
        <div
          style={{
            width: `${failed ? 0 : pct}%`,
            height: "100%",
            background: tone.bar,
            transition: "width 200ms ease-out",
          }}
        />
      </div>
    </div>
  );
}

/**
 * Net portfolio Greek book — the ThinkorSwim-Analyze top-line numbers.
 * Shows the SPY-beta-weighted delta (equivalent SPY shares) and net theta
 * ($/day) while positions are open; the tooltip carries the full per-symbol
 * grid. Hidden on a flat book — an empty Δβ pill is noise.
 */
function PortfolioGreeksMini({ openCount }: { openCount: number }) {
  const { data } = usePortfolioGreeks(openCount > 0);
  if (openCount === 0 || !data || data.positions === 0) return null;
  const bw = data.beta_weighted_delta;
  const theta = data.net.theta;
  const lines = [
    `Net book exposure across ${data.positions} open position${data.positions === 1 ? "" : "s"}:`,
    `Δβ(SPY) ${bw == null ? "—" : bw.toFixed(1)} equivalent SPY shares · ` +
      `Δ ${data.net.delta.toFixed(1)} · Γ ${data.net.gamma.toFixed(3)} · ` +
      `Θ ${theta.toFixed(0)}$/day · ν ${data.net.vega.toFixed(0)}$/vol-pt`,
    ...data.by_symbol.map(
      (r) =>
        `${r.symbol} (β ${r.beta.toFixed(2)}): Δβ ${
          r.beta_weighted_delta == null ? "—" : r.beta_weighted_delta.toFixed(1)
        } · Θ ${r.theta.toFixed(0)}`,
    ),
  ];
  return (
    <MiniStat
      label="Δβ · Θ"
      value={`${bw == null ? "—" : (bw > 0 ? "+" : "") + bw.toFixed(0)} · ${theta.toFixed(0)}`}
      valueClass={
        bw == null
          ? "text-fg-secondary"
          : bw > 0
            ? "text-bullish"
            : bw < 0
              ? "text-bearish"
              : "text-fg-secondary"
      }
      title={lines.join("\n")}
    />
  );
}

function MiniStat({
  label,
  value,
  valueClass,
  title,
}: {
  label: string;
  value: string;
  valueClass?: string;
  title?: string;
}) {
  return (
    <div className="flex flex-col leading-tight shrink-0" title={title}>
      <span
        className="uppercase tracking-label-up text-fg-tertiary-2"
        style={{ fontSize: 10, letterSpacing: "0.07em" }}
      >
        {label}
      </span>
      <span
        aria-live="polite"
        aria-label={`${label} ${value}`}
        className={`tabular-nums whitespace-nowrap ${valueClass ?? "text-fg-primary"}`}
        style={{ fontSize: 12, marginTop: 2 }}
      >
        {value}
      </span>
    </div>
  );
}

function DllMini({
  used,
  budget,
  disabled,
  hit,
  pulse,
}: {
  used: number;
  budget: number;
  disabled: boolean;
  hit: boolean;
  pulse: boolean;
}) {
  const ratio = budget > 0 ? Math.min(1, used / budget) : 0;
  const tone = disabled
    ? "text-fg-tertiary-2"
    : hit
      ? "text-breach"
      : ratio >= 0.9
        ? "text-bearish"
        : ratio >= 0.5
          ? "text-warning"
          : "text-fg-primary";
  const barColor = hit
    ? colors.accentBreach
    : ratio >= 0.9
      ? colors.bearish
      : ratio >= 0.5
        ? colors.warning
        : colors.bullish;
  return (
    <div
      className={`flex flex-col leading-tight shrink-0 ${pulse ? "td-pulse-warn px-1 rounded-btn" : ""}`}
      style={pulse ? ({ ["--td-pulse-color" as string]: colors.accentBreach } as React.CSSProperties) : undefined}
      title={
        disabled
          ? "Daily loss limit switched OFF for this tier (Settings → Risk). Only the MLL floor binds — matching Topstep, which dropped the DLL in 2024."
          : hit
            ? "Daily loss limit hit — DAY LOCK: no further trading today (account survives). Lifts at the 5pm-PT settlement."
            : "Daily loss limit (live, incl. open URPL) — resets at the 5pm-PT settlement."
      }
    >
      <span
        className="uppercase tracking-label-up text-fg-tertiary-2"
        style={{ fontSize: 10, letterSpacing: "0.07em" }}
      >
        DLL{hit && !disabled ? " · lock" : ""}
      </span>
      <span className={`tabular-nums whitespace-nowrap ${tone}`} style={{ fontSize: 12, marginTop: 2 }}>
        {disabled ? "off" : formatDllUsage(used, budget)}
      </span>
      {!disabled && (
        <div
          className="mt-1 overflow-hidden"
          style={{ height: 3, width: 56, borderRadius: 2, background: colors.bgTier0 }}
        >
          <div style={{ width: `${ratio * 100}%`, height: "100%", background: barColor }} />
        </div>
      )}
    </div>
  );
}

function MiniMarket() {
  const { data: status } = useMarketStatus();
  const isOpen = status?.status === "open";
  const earlyClose = status?.is_early_close === true;
  const dotColor = isOpen
    ? earlyClose
      ? colors.warning
      : colors.bullish
    : colors.fgTertiary2;
  const detail = useMemo(() => {
    if (!status) return "—";
    if (isOpen) {
      if (earlyClose && status.today_close) return `early ${formatClockEt(status.today_close)}`;
      if (status.next_close) return `to ${formatClockEt(status.next_close)}`;
      return status.label;
    }
    if (status.next_open) return `opens ${formatClockEt(status.next_open)}`;
    return status.label;
  }, [status, isOpen, earlyClose]);
  return (
    <div
      className="flex flex-col leading-tight shrink-0"
      title={
        earlyClose && status?.today_close
          ? `Early close today — the session (and every 0DTE contract) ends at ${formatClockEt(status.today_close)} ET.`
          : status?.label
      }
    >
      <span
        className="uppercase tracking-label-up text-fg-tertiary-2"
        style={{ fontSize: 10, letterSpacing: "0.07em" }}
      >
        {earlyClose ? "Mkt ⚠" : "Mkt"}
      </span>
      <span className="flex items-center gap-1.5 whitespace-nowrap" style={{ fontSize: 11, marginTop: 3 }}>
        <span className="inline-block rounded-full" style={{ width: 6, height: 6, background: dotColor }} />
        <span className="tabular-nums text-fg-secondary" style={{ textTransform: "lowercase" }}>
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
