import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import {
  keepPreviousData,
  useMutation,
  useQueries,
  useQueryClient,
} from "@tanstack/react-query";

import { BottomNewsFeedTabs } from "@/components/positions/BottomNewsFeedTabs";
import { strikeStep } from "@/components/positions/tools/StrategyBuilder";
import { useAccountState } from "@/hooks/useAccountState";
import { useCachedChainTable } from "@/hooks/useChainTable";
import { useMarketStatus } from "@/hooks/useMarket";
import { useTickerAnnotations } from "@/hooks/useTickerChart";
import { useTickerMetrics } from "@/hooks/useTickerMetrics";
import { useTradeAnalytics } from "@/hooks/useTradeAnalytics";
import { useTrades } from "@/hooks/useTrades";
import {
  cancelOrder,
  clearCloseOrder,
  closeLeg,
  fetchTradeAnalytics,
  rollTrade,
  scaleOutTrade,
  setCloseOrder,
  updateTrade,
} from "@/lib/api";
import { flattenPositions, reversePositions } from "@/lib/zerodteOpen";
import { TOOLTIPS } from "@/lib/tooltips";
import { tradingDayStartMs } from "@/lib/tradingDay";
import { useActivePosition } from "@/stores/activePosition";
import { useChartPrefs } from "@/stores/chartPrefs";
import {
  isIntentFresh,
  useHotkeyActions,
  useHotkeyConsumer,
} from "@/stores/hotkeyActions";
import { useSelectedTicker } from "@/stores/selectedTicker";
import { toast } from "@/stores/toast";
import { isZeroDteTrade, STRATEGY_LABELS, type Trade, type TradeAnalytics } from "@/types/journal";

/**
 * Bottom management strip — ~280px tall, four equal-width columns
 * separated by hairline dividers.
 *
 *   COL 1 — OPEN POSITION
 *   COL 2 — THETA SCRUBBER + BE drift preview
 *   COL 3 — KEY LEVELS (EM↑/EM↓/CW/PW/MP/GF + IV) with "show on chart" toggle
 *   COL 4 — TODAY's trades + link to /journal
 */
export function BottomStrip() {
  const symbol = useSelectedTicker((s) => s.symbol);
  const activeTradeId = useActivePosition((s) => s.tradeId);
  const scrubberDte = useActivePosition((s) => s.scrubberDte);
  const elapsedHours = useActivePosition((s) => s.elapsedHours);

  const { data: tradesData } = useTrades();
  const trades = useMemo(() => tradesData?.trades ?? [], [tradesData]);
  const activeTrade = useMemo(
    () => trades.find((t) => t.id === activeTradeId) ?? null,
    [trades, activeTradeId],
  );
  const isIntraday = useMemo(() => isZeroDteTrade(activeTrade), [activeTrade]);
  const analyticsQuery = useTradeAnalytics(activeTradeId, scrubberDte, {
    intraday: isIntraday,
    elapsedHours,
  });
  const analytics = analyticsQuery.data ?? null;
  // LIVE (scrubber-independent) analytics for the active position. The
  // OPEN POSITION panel's UP&L — and the realized P&L booked on close —
  // must reflect REAL P&L, never the theta scrubber's what-if. This uses
  // the SAME per-position query key the header sums over (dteOverride +
  // elapsedHours both null), so it's deduped against the header's query —
  // zero new network calls. `analytics` above stays scrubbed and still
  // drives the what-if visualizations (greeks / BE / payoff drift).
  const liveAnalyticsQuery = useTradeAnalytics(activeTradeId, null, {
    intraday: isIntraday,
    elapsedHours: null,
  });
  const liveAnalytics = liveAnalyticsQuery.data ?? null;

  // All open positions on the active tier — drives the multi-position
  // selector so EVERY open contract is visible, not just the selected one.
  // One live analytics query each; the key matches the header's per-position
  // queries, so they're shared from cache (no extra network).
  const { data: account } = useAccountState();
  const activeTier = account?.active_tier ?? "50K";
  const openPositions = useMemo(
    () => trades.filter((t) => t.status === "open" && (t.tier ?? "50K") === activeTier),
    [trades, activeTier],
  );
  const openAnalytics = useQueries({
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
  const openList = useMemo(
    () =>
      openPositions.map((t, i) => ({
        trade: t,
        upl: openAnalytics[i]?.data?.unrealized_pnl ?? null,
      })),
    [openPositions, openAnalytics],
  );

  // Panic-key targets (F-F flatten / X-X cancel-all) live at strip level so
  // they work whenever the terminal is on screen — selection or not.
  const workingOrders = useMemo(
    () =>
      trades.filter(
        (t) => t.status === "working" && (t.tier ?? "50K") === activeTier,
      ),
    [trades, activeTier],
  );

  // No active position → pre-execution strip: KEY LEVELS inline + a TODAY
  // summary row, PLUS the live activity FEED (combine lifecycle events +
  // the user's own opens/closes). OPEN POSITION and THETA SCRUBBER stay
  // hidden (empty placeholders without a trade).
  if (!activeTrade) {
    return (
      <div
        className="border-t border-hairline bg-tier-0 shrink-0 flex flex-col"
        style={{ height: 150 }}
      >
        <BulkHotkeys openCount={openPositions.length} workingOrders={workingOrders} />
        <KeyLevelsInline symbol={symbol} />
        <TodayInline trades={trades} />
        <div className="flex-1 min-h-0 flex flex-col overflow-hidden border-t border-hairline">
          <BottomNewsFeedTabs symbol={symbol} />
        </div>
      </div>
    );
  }

  return (
    <div
      className="grid border-t border-hairline bg-tier-0 shrink-0 grid-cols-1 sm:grid-cols-2 md:grid-cols-5 md:h-[280px]"
    >
      <BulkHotkeys openCount={openPositions.length} workingOrders={workingOrders} />
      <Column>
        <OpenPositionCol
          trade={activeTrade}
          analytics={analytics}
          liveAnalytics={liveAnalytics}
          openList={openList}
          activeTradeId={activeTradeId}
        />
      </Column>
      <Column>
        <ScrubberCol trade={activeTrade} analytics={analytics} isIntraday={isIntraday} />
      </Column>
      <Column>
        <KeyLevelsCol symbol={symbol} />
      </Column>
      <Column>
        <TodayCol trades={trades} activeTradeId={activeTradeId} />
      </Column>
      <Column>
        <BottomNewsFeedTabs symbol={symbol} />
      </Column>
    </div>
  );
}

// -- collapsed single-row variants (no active position) ----------------------

function KeyLevelsInline({ symbol }: { symbol: string | null }) {
  const annotations = useTickerAnnotations(symbol, "1D");
  const metrics = useTickerMetrics(symbol);
  const a = annotations.data?.annotations;
  const m = metrics.data;
  const showOnChart = useChartPrefs((s) => s.showMarketAnnotations);
  const toggle = useChartPrefs((s) => s.toggleMarketAnnotations);

  // Only render the items that actually have a value. Six dashes in a
  // row was visual noise; better to drop empties and keep the row tight.
  const items: { label: string; value: string; tooltip?: string }[] = [];
  if (a?.expected_move_upper != null)
    items.push({
      label: "EM↑",
      value: fmtPrice(a.expected_move_upper),
      tooltip: LEVEL_TOOLTIP["EM↑"],
    });
  if (a?.expected_move_lower != null)
    items.push({
      label: "EM↓",
      value: fmtPrice(a.expected_move_lower),
      tooltip: LEVEL_TOOLTIP["EM↓"],
    });
  if (a?.call_wall)
    items.push({
      label: "CW",
      value: `$${a.call_wall.strike.toFixed(2)}`,
      tooltip: LEVEL_TOOLTIP.CW,
    });
  if (a?.put_wall)
    items.push({
      label: "PW",
      value: `$${a.put_wall.strike.toFixed(2)}`,
      tooltip: LEVEL_TOOLTIP.PW,
    });
  if (a?.max_pain != null)
    items.push({
      label: "MP",
      value: fmtPrice(a.max_pain),
      tooltip: LEVEL_TOOLTIP.MP,
    });
  if (a?.gamma_flip != null)
    items.push({
      label: "GF",
      value: fmtPrice(a.gamma_flip),
      tooltip: LEVEL_TOOLTIP.GF,
    });
  if (m?.iv_rank != null)
    items.push({
      label: "IV",
      value: `${m.iv_rank.toFixed(0)}`,
      tooltip: LEVEL_TOOLTIP.IV,
    });
  if (m?.pc_ratio != null)
    items.push({
      label: "P/C",
      value: m.pc_ratio.toFixed(2),
      tooltip: LEVEL_TOOLTIP["P/C"],
    });

  return (
    <div
      className="flex items-center px-3 border-b border-hairline bg-tier-1 tabular-nums"
      style={{ height: 44, gap: 16 }}
    >
      <span
        className="uppercase tracking-label-up text-fg-tertiary shrink-0"
        style={{ fontSize: 12, letterSpacing: "0.08em" }}
      >
        Key levels
      </span>
      <span className="text-fg-tertiary-2 shrink-0" style={{ fontSize: 11 }}>
        {symbol ?? ""}
      </span>
      {items.length === 0 ? (
        <span
          className="text-fg-tertiary-2"
          style={{ fontSize: 11 }}
          title="Expected move, call/put walls, max pain and gamma flip are computed from the day's option chain. They appear once chain data is available — typically during market hours."
        >
          No levels for {symbol ?? "—"} today
        </span>
      ) : (
        <div className="flex items-center" style={{ gap: 16 }}>
          {items.map((it) => (
            <InlineLevel
              key={it.label}
              label={it.label}
              value={it.value}
              tooltip={it.tooltip}
            />
          ))}
        </div>
      )}
      <div className="ml-auto flex items-center gap-2 shrink-0">
        <span
          className="uppercase tracking-label-up text-fg-tertiary"
          style={{ fontSize: 12, letterSpacing: "0.08em" }}
        >
          show on chart
        </span>
        <PillToggle on={showOnChart} onClick={toggle} />
      </div>
    </div>
  );
}

function InlineLevel({
  label,
  value,
  tooltip,
}: {
  label: string;
  value: string;
  tooltip?: string;
}) {
  return (
    <span
      className="inline-flex items-baseline gap-1.5 tabular-nums"
      title={tooltip}
    >
      <span
        className="uppercase tracking-label-up text-fg-tertiary"
        style={{ fontSize: 12, letterSpacing: "0.06em" }}
      >
        {label}
      </span>
      <span
        className="text-fg-primary font-medium"
        style={{ fontSize: 11 }}
      >
        {value}
      </span>
    </span>
  );
}

// Definition-grade tooltips from the shared vocabulary, with the
// volume-as-OI-proxy disclosure appended to the four volume-derived
// levels. EM and IV rank are straddle/IV-derived and carry no proxy note.
const VOL_PROXY_NOTE =
  "\n\nNote: computed from today's volume as an open-interest proxy (free data tier).";
const LEVEL_TOOLTIP = {
  "EM↑": TOOLTIPS.expected_move,
  "EM↓": TOOLTIPS.expected_move,
  CW: TOOLTIPS.call_wall + VOL_PROXY_NOTE,
  PW: TOOLTIPS.put_wall + VOL_PROXY_NOTE,
  MP: TOOLTIPS.max_pain + VOL_PROXY_NOTE,
  GF: TOOLTIPS.gamma_flip + VOL_PROXY_NOTE,
  IV: TOOLTIPS.iv_rank,
  "P/C": TOOLTIPS.pc_ratio,
} as const;

/**
 * Rounded pill toggle — 24×14, amber when on. Replaces the previous
 * 7×4 hairline-edged box used elsewhere; the cleaner KEY LEVELS strip
 * is the right place for the new affordance.
 */
function PillToggle({ on, onClick }: { on: boolean; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={on}
      aria-label="Show market-structure overlays on chart"
      className="relative shrink-0"
      style={{
        width: 24,
        height: 14,
        borderRadius: 9999,
        background: on ? "#D4A24C" : "#262C38",
        transition: "background 100ms ease-out",
      }}
    >
      <span
        aria-hidden
        className="absolute"
        style={{
          top: 2,
          left: on ? 12 : 2,
          width: 10,
          height: 10,
          borderRadius: 9999,
          background: "#E8ECF2",
          transition: "left 100ms ease-out",
        }}
      />
    </button>
  );
}

function TodayInline({ trades }: { trades: Trade[] }) {
  // ONE definition of "today": the backend's 5pm-PT accounting window — the
  // same number the header RP&L, the DLL and settlement all use. The old
  // UTC-calendar sum here could disagree with every money surface around it
  // (the audit's two-todays reconciliation trap).
  const { data: account } = useAccountState();
  const net = account?.today_realized ?? 0;
  const count = useMemo(() => {
    const start = tradingDayStartMs();
    const after = (iso: string | null | undefined) =>
      iso != null && Date.parse(iso) >= start;
    let c = 0;
    for (const t of trades) {
      // SAME population as the net (review wave 9, finding 8): the backend's
      // today_realized covers the ACTIVE combine's execution book only —
      // counting copy-follower mirrors in other combines or manual journal
      // rows beside it rebuilt the net-vs-count reconciliation mismatch.
      if (account?.combine_id != null && t.combine_id !== account.combine_id)
        continue;
      if (t.origin !== "execution") continue;
      if (t.status === "closed" && after(t.exit_date)) c += 1;
      else if (t.status === "open" && after(t.entry_date)) c += 1;
    }
    return c;
  }, [trades, account?.combine_id]);
  const netCls =
    net > 0 ? "text-bullish" : net < 0 ? "text-bearish" : "text-fg-secondary";
  return (
    <div
      className="flex items-center gap-3 px-3 tabular-nums"
      style={{ height: 36 }}
    >
      <span
        className="text-tiny uppercase tracking-label-up text-fg-secondary shrink-0"
        title="Realized P&L this trading day (5pm-PT accounting window) — the same window as the header RP&L, the daily loss limit and settlement."
      >
        Today
      </span>
      <span className={`text-tiny ${netCls}`}>{formatSignedDollar(net)}</span>
      <span className="text-tiny text-fg-tertiary-2">
        {count} trade{count === 1 ? "" : "s"}
      </span>
      <Link
        to="/journal"
        className="ml-auto text-tiny uppercase tracking-label-up text-fg-tertiary-2 hover:text-amber"
      >
        view full journal →
      </Link>
    </div>
  );
}

function Column({ children }: { children: React.ReactNode }) {
  // overflow-y-auto (not hidden): inside the fixed 280px strip, a tall column —
  // e.g. an open position stacking roll + close-limit + auto-close-countdown +
  // close + bulk rows — used to be silently CLIPPED. Auto keeps the layout
  // identical when content fits and adds a scrollbar only when it overflows, so
  // nothing is ever hidden. overflow-x stays clipped to avoid a spurious
  // horizontal bar from full-width children.
  return (
    <div className="border-r border-hairline last:border-r-0 flex flex-col min-h-0 overflow-y-auto overflow-x-hidden">
      {children}
    </div>
  );
}

// -- COL 1: OPEN POSITION -----------------------------------------------------

function OpenPositionCol({
  trade,
  analytics,
  liveAnalytics,
  openList,
  activeTradeId,
}: {
  trade: Trade | null;
  /** Scrubbed analytics — drives the what-if greeks / BE only. */
  analytics: TradeAnalytics | null;
  /** Live, scrubber-independent analytics — drives the UP&L + close. */
  liveAnalytics: TradeAnalytics | null;
  /** Every open position on the active tier + its live UP&L, for the
   *  selector list (shown when more than one is open). */
  openList: { trade: Trade; upl: number | null }[];
  /** The currently-selected position id (highlighted in the list). */
  activeTradeId: number | null;
}) {
  const queryClient = useQueryClient();
  const setActiveTradeId = useActivePosition((s) => s.setTradeId);
  // The position's true live unrealized P&L — independent of the theta
  // scrubber, shown BEST-EFFORT ('—' when the feed is stalled). The exit
  // itself never depends on it: the backend recomputes realized P&L
  // server-side from its own mark, so a close posts only status + exit_date.
  // A trader must be able to bail out of a losing 0DTE during a feed stall.
  const liveUpl = liveAnalytics?.unrealized_pnl ?? null;
  const commissionSide = liveAnalytics?.commission ?? 0;
  const close = useMutation({
    mutationFn: async () => {
      if (!trade) return null;
      return updateTrade(trade.id, {
        status: "closed",
        exit_date: new Date().toISOString(),
      });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["journal", "trades"] });
      // Account state polls every 5s; invalidate so the header
      // BAL/MLL/RP&L update immediately after the close books P&L.
      queryClient.invalidateQueries({ queryKey: ["account", "state"] });
      setActiveTradeId(null);
    },
    onError: (e) => {
      // A 409 here means the monitor already booked this close (bracket /
      // liquidation) while the row still rendered as open — a ghost. Refetch so
      // the closed state lands and the ghost disappears instead of lingering.
      queryClient.invalidateQueries({ queryKey: ["journal", "trades"] });
      queryClient.invalidateQueries({ queryKey: ["account", "state"] });
      toast.error((e as Error)?.message || "Could not close position");
    },
  });

  // Scale-out: close `closeQty` of `held` contracts (default = full). The
  // slice's realized is RECOMPUTED server-side (the payload's realized_pnl is
  // deprecated + ignored) — the estimate below is display-only, so a stalled
  // analytics feed never blocks the exit.
  const held = trade ? totalContracts(trade) : 1;
  const [rawCloseQty, setCloseQty] = useState<number | null>(null);
  const closeQty = Math.min(held, Math.max(1, rawCloseQty ?? held));
  const isPartial = closeQty < held;
  const sliceRealized =
    liveUpl != null && held > 0
      ? (liveUpl - commissionSide) * (closeQty / held)
      : null;
  const scaleOut = useMutation({
    mutationFn: async () => {
      if (!trade) return null;
      return scaleOutTrade(trade.id, {
        qty: closeQty,
        realized_pnl: 0, // deprecated — server recomputes from its own mark
      });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["journal", "trades"] });
      queryClient.invalidateQueries({ queryKey: ["account", "state"] });
      // The remaining position now holds fewer contracts — refetch its analytics
      // so UPL / greeks / the CLOSE "realize" amount reflect the smaller size.
      if (trade) queryClient.invalidateQueries({ queryKey: ["trade-analytics", trade.id] });
      setCloseQty(null); // reset to "full" for the now-smaller remaining position
    },
    onError: (e) => {
      // 409 → the position was closed concurrently (bracket / liquidation);
      // refetch so the stale "open" row reconciles to closed.
      queryClient.invalidateQueries({ queryKey: ["journal", "trades"] });
      queryClient.invalidateQueries({ queryKey: ["account", "state"] });
      toast.error((e as Error)?.message || "Could not scale out");
    },
  });

  // WS6 power-UX: the "C" hotkey (and the palette's "Close active position")
  // close the selected position at the live mark. SAFETY: closing realizes
  // round-trip P&L, so — like the B/S arm pattern — a single keystroke must
  // NOT fire. The first press ARMS (a sticky toast); a confirming second press
  // within 3s actually closes. The panel owns the close mutation; no-op when
  // nothing's open or a close is already in flight.
  const hotkeyIntent = useHotkeyActions((s) => s.intent);
  const hotkeyNonce = useHotkeyActions((s) => s.nonce);
  const consumeHotkey = useHotkeyActions((s) => s.consume);
  const closeArmRef = useRef<number>(0);
  useEffect(() => {
    if (hotkeyIntent !== "closeActive") return;
    consumeHotkey();
    if (!trade || close.isPending || scaleOut.isPending) return;
    const now = Date.now();
    if (now - closeArmRef.current > 3000) {
      // First press → arm; require a confirming second press.
      closeArmRef.current = now;
      toast.warning(`Press C again to close ${trade.symbol}`, 3000);
      return;
    }
    closeArmRef.current = 0;
    if (isPartial) scaleOut.mutate();
    else close.mutate();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hotkeyIntent, hotkeyNonce]);

  return (
    <>
      <ColHeader
        left="Open position"
        right={trade ? `DTE ${analytics?.current_dte_days ?? "—"}` : ""}
      />
      {/* Selector list — shown when more than one position is open, so every
          open contract is visible and the header's URPL reconciles with what
          you see. Click a row to drive the detail + chart selection. */}
      {openList.length > 1 && (
        <div className="px-3 pt-1 flex flex-col gap-px max-h-[68px] overflow-y-auto shrink-0">
          {openList.map(({ trade: t, upl }) => (
            <button
              key={t.id}
              type="button"
              onClick={() => setActiveTradeId(t.id)}
              className={`flex items-center justify-between gap-2 px-1 py-0.5 text-tiny border tabular-nums ${
                t.id === activeTradeId
                  ? "border-amber bg-tier-2 text-fg-primary"
                  : "border-transparent text-fg-secondary hover:bg-tier-2"
              }`}
              style={{ borderRadius: 0 }}
              title={`${t.symbol} ${STRATEGY_LABELS[t.strategy] ?? t.strategy} · ${totalContracts(t)} contract${totalContracts(t) === 1 ? "" : "s"}`}
            >
              <span className="truncate">
                {t.symbol} · {totalContracts(t)}c
              </span>
              <span
                className={
                  upl == null
                    ? "text-fg-tertiary"
                    : upl > 0
                      ? "text-bullish"
                      : upl < 0
                        ? "text-bearish"
                        : "text-fg-secondary"
                }
              >
                {upl == null ? "—" : formatSignedDollar(upl)}
              </span>
            </button>
          ))}
        </div>
      )}
      {!trade && (
        <Empty>No open position. Pick a strike in the chain ↑</Empty>
      )}
      {trade && (
        <div className="flex flex-col flex-1 min-h-0 px-3 py-1.5 tabular-nums">
          <div className="flex items-center gap-2 text-tiny">
            <PositionGlyph />
            <span className="text-fg-primary">{trade.symbol}</span>
            <span className="text-fg-tertiary-2">
              {STRATEGY_LABELS[trade.strategy] ?? trade.strategy}
            </span>
          </div>
          <div className="text-fg-tertiary-2 mt-0.5" style={{ fontSize: 12 }}>
            {summarizeLegs(trade)} · entry{" "}
            {formatTimestamp(trade.entry_date)} ET ·{" "}
            {totalContracts(trade)} contract{totalContracts(trade) === 1 ? "" : "s"}
          </div>
          <LegCloseList trade={trade} />
          {commissionSide > 0 && (
            <div
              className="text-fg-tertiary mt-0.5"
              style={{ fontSize: 11 }}
              title="Simulated commission — folded into UP&L; round trip (entry + exit) booked on close"
            >
              incl. commission −${commissionSide.toFixed(2)}/side ·
              −${(commissionSide * 2).toFixed(2)} round-trip
            </div>
          )}
          <div className="border-t border-hairline my-1.5" />
          <div className="flex items-baseline justify-between">
            <span
              className="uppercase tracking-label-up text-fg-tertiary-2"
              style={{ fontSize: 11 }}
            >
              UPL
            </span>
            <span
              className={`text-large font-medium ${
                liveUpl != null && liveUpl > 0
                  ? "text-bullish"
                  : liveUpl != null && liveUpl < 0
                    ? "text-bearish"
                    : "text-fg-secondary"
              }`}
            >
              {liveUpl == null ? "—" : formatSignedDollar(liveUpl)}
            </span>
          </div>
          {analytics && (
            <>
              <GreeksGrid g={analytics} />
              <BeRange be={analytics.breakevens_today} />
              <RiskRow analytics={analytics} />
            </>
          )}
          <div className="mt-auto pt-2 flex flex-col gap-1.5">
            {held > 1 && (
              <QtyStepper qty={closeQty} max={held} onChange={setCloseQty} />
            )}
            <RollRow trade={trade} />
            <CloseLimitRow trade={trade} liveAnalytics={liveAnalytics} />
            <AutoCloseCountdown />
            <CloseButton
              disabled={close.isPending || scaleOut.isPending}
              upl={isPartial ? sliceRealized : liveUpl}
              partialQty={isPartial ? closeQty : null}
              totalQty={held}
              onClick={() => (isPartial ? scaleOut.mutate() : close.mutate())}
            />
            <BulkActions />
          </div>
        </div>
      )}
    </>
  );
}

/**
 * Invisible strip-level consumer for the panic hotkeys: F-F flattens every
 * open position, X-X cancels every working order. Mounted whenever the
 * terminal strip is on screen (selection or not) so the kill switches never
 * depend on what's focused. Same double-press arming as the C-C close —
 * a single keystroke must NOT liquidate a book.
 */
function BulkHotkeys({
  openCount,
  workingOrders,
}: {
  openCount: number;
  workingOrders: Trade[];
}) {
  const queryClient = useQueryClient();
  const setActiveTradeId = useActivePosition((s) => s.setTradeId);
  useHotkeyConsumer(["flattenAll", "cancelAllOrders"]);

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["journal", "trades"] });
    queryClient.invalidateQueries({ queryKey: ["account", "state"] });
  };

  const flatten = useMutation({
    mutationFn: flattenPositions,
    onSuccess: (r) => {
      invalidate();
      setActiveTradeId(null);
      toast.success(
        `Flattened ${r.closed.length} position${r.closed.length === 1 ? "" : "s"} · ` +
          `${formatSignedDollar(r.realized)} realized`,
      );
    },
    onError: (e) => toast.error((e as Error)?.message || "Could not flatten"),
  });

  const cancelAll = useMutation({
    mutationFn: async (orders: Trade[]) => {
      await Promise.all(orders.map((o) => cancelOrder(o.id)));
      return orders.length;
    },
    onSuccess: (n) => {
      invalidate();
      toast.success(`Cancelled ${n} working order${n === 1 ? "" : "s"}`);
    },
    onError: (e) => toast.error((e as Error)?.message || "Could not cancel orders"),
  });

  const intent = useHotkeyActions((s) => s.intent);
  const nonce = useHotkeyActions((s) => s.nonce);
  const ts = useHotkeyActions((s) => s.ts);
  const consume = useHotkeyActions((s) => s.consume);
  const flattenArmRef = useRef<number>(0);
  const cancelArmRef = useRef<number>(0);
  useEffect(() => {
    if (intent !== "flattenAll" && intent !== "cancelAllOrders") return;
    consume();
    if (!isIntentFresh(ts)) return; // stale replay from an earlier mount
    const now = Date.now();
    if (intent === "flattenAll") {
      if (openCount === 0) {
        toast.info("No open positions to flatten");
        return;
      }
      if (flatten.isPending) return;
      if (now - flattenArmRef.current > 3000) {
        flattenArmRef.current = now;
        toast.warning(
          `Press F again to FLATTEN ${openCount} position${openCount === 1 ? "" : "s"}`,
          3000,
        );
        return;
      }
      flattenArmRef.current = 0;
      flatten.mutate();
      return;
    }
    if (workingOrders.length === 0) {
      toast.info("No working orders to cancel");
      return;
    }
    if (cancelAll.isPending) return;
    if (now - cancelArmRef.current > 3000) {
      cancelArmRef.current = now;
      toast.warning(
        `Press X again to cancel ${workingOrders.length} working order${workingOrders.length === 1 ? "" : "s"}`,
        3000,
      );
      return;
    }
    cancelArmRef.current = 0;
    cancelAll.mutate(workingOrders);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [intent, nonce]);

  return null;
}

/**
 * Flatten-all / Reverse-all — combine-wide bulk actions. FLATTEN closes every
 * open position on the active combine; REVERSE flattens then re-opens the
 * opposite side of each. Both invalidate the trade + account queries so the
 * strip, header and chart reflect the new state immediately. Both ARM on the
 * first click and fire on a confirming second click within 3s — same safety
 * doctrine as the C-C hotkey close (the blast radius here is the whole book).
 */
function BulkActions() {
  const queryClient = useQueryClient();
  const setActiveTradeId = useActivePosition((s) => s.setTradeId);

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["journal", "trades"] });
    queryClient.invalidateQueries({ queryKey: ["account", "state"] });
  };

  const flatten = useMutation({
    mutationFn: flattenPositions,
    onSuccess: (r) => {
      invalidate();
      setActiveTradeId(null);
      toast.success(
        `Flattened ${r.closed.length} position${r.closed.length === 1 ? "" : "s"} · ` +
          `${formatSignedDollar(r.realized)} realized`,
      );
    },
    onError: (e) => toast.error((e as Error)?.message || "Could not flatten"),
  });

  const reverse = useMutation({
    mutationFn: reversePositions,
    onSuccess: (r) => {
      invalidate();
      setActiveTradeId(r.opened[0] ?? null);
      toast.success(
        `Reversed ${r.closed.length} → ${r.opened.length} position` +
          `${r.opened.length === 1 ? "" : "s"}`,
      );
    },
    onError: (e) => toast.error((e as Error)?.message || "Could not reverse"),
  });

  const [armed, setArmed] = useState<"flatten" | "reverse" | null>(null);
  useEffect(() => {
    if (!armed) return;
    const t = setTimeout(() => setArmed(null), 3000);
    return () => clearTimeout(t);
  }, [armed]);
  const fire = (which: "flatten" | "reverse") => {
    if (armed !== which) {
      setArmed(which);
      return;
    }
    setArmed(null);
    if (which === "flatten") flatten.mutate();
    else reverse.mutate();
  };

  const pending = flatten.isPending || reverse.isPending;
  return (
    <div className="grid grid-cols-2 gap-2">
      <BulkButton
        label={armed === "flatten" ? "CLICK AGAIN — FLATTEN" : "FLATTEN ALL"}
        title="Close every open position on this combine at the live mark. Click twice to confirm."
        disabled={pending}
        armed={armed === "flatten"}
        onClick={() => fire("flatten")}
      />
      <BulkButton
        label={armed === "reverse" ? "CLICK AGAIN — REVERSE" : "REVERSE ALL"}
        title="Flatten every position, then re-open the opposite side of each. Click twice to confirm."
        disabled={pending}
        armed={armed === "reverse"}
        onClick={() => fire("reverse")}
      />
    </div>
  );
}

function BulkButton({
  label,
  title,
  disabled,
  armed = false,
  onClick,
}: {
  label: string;
  title: string;
  disabled: boolean;
  /** Armed = one confirming click away from firing — escalated styling. */
  armed?: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      title={title}
      className={[
        "w-full h-7 rounded-btn font-semibold tabular-nums uppercase",
        "transition-colors duration-100 border",
        disabled
          ? "bg-tier-1 text-fg-disabled border-tier-2 cursor-not-allowed"
          : armed
            ? "bg-action-sell text-white border-action-sell hover:bg-action-sell-hover"
            : "bg-tier-1 text-fg-secondary border-tier-3 hover:bg-tier-2 hover:text-fg-primary",
      ].join(" ")}
      style={{ fontSize: 11, letterSpacing: "0.04em" }}
    >
      {label}
    </button>
  );
}

function PositionGlyph() {
  return (
    <span
      aria-hidden
      className="inline-block"
      style={{
        width: 0,
        height: 0,
        borderLeft: "4px solid transparent",
        borderRight: "4px solid transparent",
        borderBottom: "6px solid #C264D8",
      }}
    />
  );
}

function GreeksGrid({ g }: { g: TradeAnalytics }) {
  const theta = g.greeks.theta;
  const thetaCls =
    theta > 0 ? "text-bullish" : theta < 0 ? "text-bearish" : "text-fg-secondary";
  return (
    <div className="grid grid-cols-4 gap-1 mt-1 text-tiny">
      <Greek label="Δ" value={g.greeks.delta.toFixed(2)} />
      <Greek label="Γ" value={g.greeks.gamma.toFixed(3)} />
      <Greek label="Θ" value={g.greeks.theta.toFixed(2)} valueCls={thetaCls} />
      <Greek label="ν" value={g.greeks.vega.toFixed(2)} />
    </div>
  );
}

function Greek({
  label,
  value,
  valueCls,
}: {
  label: string;
  value: string;
  valueCls?: string;
}) {
  return (
    <div className="flex items-baseline gap-1">
      <span className="text-fg-tertiary-2" style={{ fontSize: 12 }}>
        {label}
      </span>
      <span className={`tabular-nums ${valueCls ?? "text-fg-secondary"}`}>
        {value}
      </span>
    </div>
  );
}

function BeRange({ be }: { be: number[] }) {
  if (!be || be.length === 0) return null;
  if (be.length === 1) {
    return (
      <div className="text-tiny text-position tabular-nums mt-1">
        BE ${be[0].toFixed(2)}
      </div>
    );
  }
  const sorted = [...be].sort((a, b) => a - b);
  return (
    <div className="text-tiny text-position tabular-nums mt-1">
      BE ${sorted[0].toFixed(2)} ↔ ${sorted[sorted.length - 1].toFixed(2)}
    </div>
  );
}

function RiskRow({ analytics }: { analytics: TradeAnalytics }) {
  const gain = analytics.unlimited_gain
    ? "unlimited"
    : formatSignedDollar(analytics.max_profit ?? 0);
  const loss = analytics.unlimited_loss
    ? "unlimited"
    : formatSignedDollar(analytics.max_loss ?? 0);
  return (
    <div className="flex items-baseline justify-between mt-1 tabular-nums">
      <RiskItem label="MAX LOSS" value={loss} tone="bearish" />
      {analytics.pop != null && (
        <div
          className="flex flex-col leading-tight"
          title="Probability this position, held to expiry, ends profitable FROM HERE — entry fills and commission included. A model number (risk-neutral, ATM IV), not a forecast."
        >
          <span
            className="uppercase tracking-label-up text-fg-tertiary-2"
            style={{ fontSize: 11 }}
          >
            POP
          </span>
          <span className="text-tiny tabular-nums text-fg-primary">
            {Math.round(analytics.pop * 100)}%
          </span>
        </div>
      )}
      <RiskItem label="MAX GAIN" value={gain} tone="bullish" />
    </div>
  );
}

function RiskItem({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone: "bullish" | "bearish";
}) {
  const cls = tone === "bullish" ? "text-bullish" : "text-bearish";
  return (
    <div className="flex flex-col leading-tight">
      <span
        className="uppercase tracking-label-up text-fg-tertiary-2"
        style={{ fontSize: 11 }}
      >
        {label}
      </span>
      <span className={`text-tiny tabular-nums ${cls}`}>{value}</span>
    </div>
  );
}

function QtyStepper({
  qty,
  max,
  onChange,
}: {
  qty: number;
  max: number;
  onChange: (q: number) => void;
}) {
  const clamp = (q: number) => Math.min(max, Math.max(1, q));
  return (
    <div className="flex items-center justify-between gap-2 text-tiny tabular-nums">
      <span className="uppercase tracking-label-up text-fg-tertiary-2" style={{ fontSize: 11 }}>
        Close qty
      </span>
      <div className="flex items-center gap-1">
        <button
          type="button"
          onClick={() => onChange(clamp(qty - 1))}
          disabled={qty <= 1}
          className="w-5 h-5 border border-hairline text-fg-secondary hover:bg-tier-2 disabled:opacity-40 disabled:cursor-not-allowed"
          style={{ borderRadius: 0 }}
          aria-label="decrease close quantity"
        >
          −
        </button>
        <span className="w-10 text-center text-fg-primary">
          {qty}/{max}
        </span>
        <button
          type="button"
          onClick={() => onChange(clamp(qty + 1))}
          disabled={qty >= max}
          className="w-5 h-5 border border-hairline text-fg-secondary hover:bg-tier-2 disabled:opacity-40 disabled:cursor-not-allowed"
          style={{ borderRadius: 0 }}
          aria-label="increase close quantity"
        >
          +
        </button>
      </div>
    </div>
  );
}

/**
 * Expiration-day auto-close countdown (audit wave 5 — completing wave 1's
 * policy). Far from the bell: a quiet static line stating the policy. Inside
 * 20 minutes of the CUTOFF (session close − expiry_closeout_minutes, half-day
 * aware via today_close): a live amber countdown; past the cutoff: red
 * "imminent". The window comes off the market-status payload so the display
 * always matches the enforced config. Ticks on a 15s clock — the flatten
 * itself is server-side; this is advance warning, not the trigger.
 */
function AutoCloseCountdown() {
  const { data: market } = useMarketStatus();
  const [nowMs, setNowMs] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNowMs(Date.now()), 15_000);
    return () => clearInterval(id);
  }, []);

  const windowMin = market?.expiry_closeout_minutes ?? 10;
  if (!windowMin || windowMin <= 0) return null; // policy disabled
  const staticLine = (
    <div
      className="text-fg-tertiary"
      style={{ fontSize: 10 }}
      title="Expiration-day policy: rather than model OCC assignment, the desk force-flattens 0DTE books shortly before the bell (half-day aware). Working orders on dying contracts are pulled at the same cutoff."
    >
      0DTE policy · auto-close ~{Math.round(windowMin)} min before the bell
    </div>
  );
  if (!market?.today_close || market.status !== "open") return staticLine;
  const closeMs = Date.parse(market.today_close);
  if (!Number.isFinite(closeMs)) return staticLine;
  const cutoffMs = closeMs - windowMin * 60_000;
  const remainMs = cutoffMs - nowMs;
  if (remainMs > 20 * 60_000) return staticLine;

  if (remainMs <= 0) {
    return (
      <div
        className="px-1.5 py-0.5 border border-bearish/60 bg-tier-1 text-bearish uppercase tracking-label-up"
        style={{ fontSize: 10 }}
        role="alert"
        title="The expiration-day close-out window is live — the desk is flattening 0DTE books and pulling working orders on dying contracts."
      >
        auto-close imminent — book is being flattened
      </div>
    );
  }
  const mins = Math.floor(remainMs / 60_000);
  const secs = Math.floor((remainMs % 60_000) / 1000);
  return (
    <div
      className="px-1.5 py-0.5 border border-warning/60 bg-tier-1 text-warning uppercase tracking-label-up"
      style={{ fontSize: 10 }}
      role="status"
      title="Expiration-day policy: open 0DTE positions are force-flattened at this cutoff (half-day aware). Close or roll before it if you want to name your own exit."
    >
      auto-close in {mins}:{String(secs).padStart(2, "0")} — close or roll to
      name your exit
    </div>
  );
}

/**
 * Per-leg close — buy back the tested short of a condor and let the far
 * side ride. Rendered only for multi-leg positions; each row is the leg
 * tape with an arm→confirm ✕ (a leg close books realized P&L). The backend
 * 409s while copy-followers mirror the trade; the toast surfaces that.
 */
function LegCloseList({ trade }: { trade: Trade }) {
  const queryClient = useQueryClient();
  const [armedIdx, setArmedIdx] = useState<number | null>(null);
  const armTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const close = useMutation({
    mutationFn: (idx: number) => closeLeg(trade.id, idx),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["journal", "trades"] });
      queryClient.invalidateQueries({ queryKey: ["account", "state"] });
      queryClient.invalidateQueries({ queryKey: ["trade-analytics", trade.id] });
    },
    onError: (e) => {
      queryClient.invalidateQueries({ queryKey: ["journal", "trades"] });
      toast.error((e as Error)?.message || "Could not close leg");
    },
    onSettled: () => setArmedIdx(null),
  });
  if (trade.legs.length < 2) return null;

  const fire = (idx: number) => {
    if (close.isPending) return;
    if (armedIdx !== idx) {
      setArmedIdx(idx);
      if (armTimer.current) clearTimeout(armTimer.current);
      armTimer.current = setTimeout(() => setArmedIdx(null), 3000);
      return;
    }
    if (armTimer.current) clearTimeout(armTimer.current);
    close.mutate(idx);
  };

  return (
    <div className="flex flex-col mt-0.5" style={{ gap: 1 }}>
      {trade.legs.map((leg, i) => (
        <div
          key={`${leg.side}-${leg.strike}-${i}`}
          className="flex items-center gap-1.5 tabular-nums text-fg-tertiary-2"
          style={{ fontSize: 11 }}
        >
          <span className={leg.action === "buy" ? "text-bullish" : "text-bearish"}>
            {leg.action === "buy" ? "+" : "−"}
            {(leg.contracts ?? 1) > 1 ? `${leg.contracts}×` : ""}
            {leg.strike}
            {leg.side === "call" ? "C" : "P"}
          </span>
          <span>@ {(leg.entry_price ?? 0).toFixed(2)}</span>
          <button
            type="button"
            onClick={() => fire(i)}
            disabled={close.isPending}
            className={[
              "ml-auto px-1 leading-none uppercase tracking-label-up disabled:opacity-40",
              armedIdx === i
                ? "text-warning"
                : "text-fg-tertiary hover:text-bearish",
            ].join(" ")}
            style={{ fontSize: 10 }}
            title="Close JUST this leg at the live mark — the rest of the structure keeps riding (press twice)"
            aria-label={`close leg ${leg.strike} ${leg.side}`}
          >
            {armedIdx === i ? "confirm ✕" : "✕ leg"}
          </button>
        </div>
      ))}
    </div>
  );
}

/**
 * Roll row — the core management action on every real options platform:
 * close + reopen the same structure at shifted strikes as ONE action.
 * [↓ step] shifts every leg down one grid step, [atm] re-centers the anchor
 * leg on the current ATM, [↑ step] shifts up. Strike step comes from the
 * cached chain the ladder already polls (no extra request). Two-press arm
 * like the C-C close — a roll books realized P&L.
 */
function RollRow({ trade }: { trade: Trade }) {
  const queryClient = useQueryClient();
  const setActiveTradeId = useActivePosition((s) => s.setTradeId);
  const chain = useCachedChainTable(trade.symbol);
  const step = useMemo(
    () => strikeStep((chain?.rows ?? []).map((r) => r.strike).sort((a, b) => a - b)),
    [chain],
  );
  const [armed, setArmed] = useState<"down" | "atm" | "up" | null>(null);
  const armTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const roll = useMutation({
    mutationFn: (opts: { strikeShift?: number; toAtm?: boolean }) =>
      rollTrade(trade.id, opts),
    onSuccess: (r) => {
      queryClient.invalidateQueries({ queryKey: ["journal", "trades"] });
      queryClient.invalidateQueries({ queryKey: ["account", "state"] });
      setActiveTradeId(r.opened);
      toast.success(
        `Rolled · realized ${formatSignedDollar(r.realized)} · new net ${formatSignedDollar(r.net_debit_credit)}`,
      );
    },
    onError: (e) => {
      queryClient.invalidateQueries({ queryKey: ["journal", "trades"] });
      toast.error((e as Error)?.message || "Could not roll");
    },
    onSettled: () => setArmed(null),
  });

  const fire = (which: "down" | "atm" | "up") => {
    if (roll.isPending) return;
    if (armed !== which) {
      setArmed(which);
      if (armTimer.current) clearTimeout(armTimer.current);
      armTimer.current = setTimeout(() => setArmed(null), 3000);
      return;
    }
    if (armTimer.current) clearTimeout(armTimer.current);
    if (which === "atm") roll.mutate({ toAtm: true });
    else roll.mutate({ strikeShift: which === "up" ? step : -step });
  };

  const btn = (which: "down" | "atm" | "up", label: string, title: string) => (
    <button
      type="button"
      onClick={() => fire(which)}
      disabled={roll.isPending}
      className={[
        "flex-1 h-6 border uppercase tracking-label-up disabled:opacity-40",
        armed === which
          ? "border-warning text-warning bg-tier-2"
          : "border-hairline text-fg-tertiary-2 hover:text-fg-secondary hover:bg-tier-2",
      ].join(" ")}
      style={{ fontSize: 10, borderRadius: 0 }}
      title={title}
    >
      {armed === which ? "confirm" : label}
    </button>
  );

  return (
    <div className="flex items-center gap-1">
      <span
        className="uppercase tracking-label-up text-fg-tertiary-2 shrink-0"
        style={{ fontSize: 10 }}
        title="Roll: close this position at the live mark and reopen the same structure at shifted strikes as one action. Premium TP/SL and trailing stops carry over; stale underlying brackets are dropped."
      >
        roll
      </span>
      {btn("down", `↓ ${step}`, `Shift every leg DOWN ${step} (press twice)`)}
      {btn("atm", "atm", "Re-center the anchor leg on the current ATM (press twice)")}
      {btn("up", `↑ ${step}`, `Shift every leg UP ${step} (press twice)`)}
    </div>
  );
}

/** Base size of the structure = gcd of the leg quantities — the unit the
 *  backend's close_limit_price is quoted in (signed net premium per 1×). */
function structureBase(trade: Trade): number {
  const gcd = (a: number, b: number): number => (b === 0 ? a : gcd(b, a % b));
  let base = 0;
  for (const leg of trade.legs) base = gcd(base, Math.max(1, leg.contracts ?? 1));
  return Math.max(1, base);
}

/** Signed net ENTRY premium per 1× structure (debit positive / credit
 *  negative) — decides which way the close-limit points. */
function entryNet1x(trade: Trade): number {
  let net = 0;
  for (const leg of trade.legs) {
    const sign = leg.action === "buy" ? 1 : -1;
    net += sign * (leg.contracts ?? 1) * (leg.entry_price ?? 0);
  }
  return net / structureBase(trade);
}

/**
 * Resting close-limit — the take-profit half of the order lifecycle. A
 * net-debit position names the value to SELL at; a net-credit position
 * names the buy-back cost. The user always types a positive premium; the
 * sign convention (credit = negative net) is applied before the API call.
 * While one rests, the row collapses to a working chip with a cancel ✕.
 */
function CloseLimitRow({
  trade,
  liveAnalytics,
}: {
  trade: Trade;
  liveAnalytics: TradeAnalytics | null;
}) {
  const queryClient = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [raw, setRaw] = useState("");
  const [confirmPull, setConfirmPull] = useState(false);

  const isCredit = entryNet1x(trade) < 0;
  const base = structureBase(trade);
  // Live per-1× net premium magnitude — the natural seed for the input.
  const liveNet1x =
    liveAnalytics != null
      ? Math.abs(liveAnalytics.current_value) / 100 / base
      : null;

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["journal", "trades"] });
  };
  const place = useMutation({
    mutationFn: async (limit1x: number) =>
      setCloseOrder(trade.id, isCredit ? -Math.abs(limit1x) : Math.abs(limit1x)),
    onSuccess: () => {
      invalidate();
      setEditing(false);
      setRaw("");
    },
    onError: (e) =>
      toast.error((e as Error)?.message || "Could not place close limit"),
  });
  const pull = useMutation({
    mutationFn: async () => clearCloseOrder(trade.id),
    onSuccess: invalidate,
    onError: (e) => {
      invalidate(); // 409 → filled/closed underneath; reconcile
      toast.error((e as Error)?.message || "Could not cancel close limit");
    },
  });

  const resting = trade.close_limit_price;
  if (resting != null) {
    return (
      <div
        className="flex items-center justify-between gap-2 px-1.5 py-1 border border-amber/50 bg-tier-2 text-tiny tabular-nums"
        style={{ borderRadius: 0 }}
      >
        <span className="text-amber uppercase" style={{ fontSize: 11 }}>
          {isCredit ? "Buy back ≤" : "Close ≥"} ${Math.abs(resting).toFixed(2)}{" "}
          · working
        </span>
        {confirmPull ? (
          <span className="flex items-center gap-1.5">
            <button
              type="button"
              onClick={() => pull.mutate()}
              disabled={pull.isPending}
              className="uppercase tracking-label-up text-bearish disabled:opacity-40"
              style={{ fontSize: 10 }}
              aria-label="confirm cancel resting close limit"
            >
              cancel?
            </button>
            <button
              type="button"
              onClick={() => setConfirmPull(false)}
              className="uppercase tracking-label-up text-fg-tertiary-2 hover:text-fg-primary"
              style={{ fontSize: 10 }}
              aria-label="keep resting close limit"
            >
              keep
            </button>
          </span>
        ) : (
          <button
            type="button"
            onClick={() => setConfirmPull(true)}
            disabled={pull.isPending}
            className="text-fg-tertiary-2 hover:text-bearish disabled:opacity-40 px-1"
            aria-label="cancel resting close limit"
            title="Cancel the resting close limit"
          >
            ✕
          </button>
        )}
      </div>
    );
  }

  if (!editing) {
    return (
      <button
        type="button"
        onClick={() => {
          setEditing(true);
          if (liveNet1x != null && liveNet1x > 0) setRaw(liveNet1x.toFixed(2));
        }}
        className="w-full h-6 border border-hairline text-fg-tertiary-2 hover:text-fg-secondary hover:bg-tier-2 uppercase tracking-label-up"
        style={{ fontSize: 11, borderRadius: 0 }}
        title={
          isCredit
            ? "Rest a buy-back limit: closes when the premium decays to your price"
            : "Rest a closing limit: closes at your price when the mark reaches it"
        }
      >
        + close at limit
      </button>
    );
  }

  const parsed = Number.parseFloat(raw);
  const valid = Number.isFinite(parsed) && parsed > 0;
  return (
    <div className="flex items-center gap-1 text-tiny tabular-nums">
      <span
        className="uppercase tracking-label-up text-fg-tertiary-2 shrink-0"
        style={{ fontSize: 11 }}
      >
        {isCredit ? "Buy back ≤" : "Close ≥"}
      </span>
      <input
        value={raw}
        onChange={(e) => setRaw(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && valid && !place.isPending) place.mutate(parsed);
          if (e.key === "Escape") setEditing(false);
        }}
        inputMode="decimal"
        placeholder={liveNet1x != null ? liveNet1x.toFixed(2) : "0.00"}
        className="w-full min-w-0 h-6 px-1 bg-tier-1 border border-hairline text-fg-primary"
        style={{ fontSize: 12, borderRadius: 0 }}
        autoFocus
        aria-label="close limit net premium per 1x structure"
      />
      <button
        type="button"
        onClick={() => place.mutate(parsed)}
        disabled={!valid || place.isPending}
        className="h-6 px-2 border border-amber/60 text-amber hover:bg-tier-2 disabled:opacity-40 uppercase"
        style={{ fontSize: 11, borderRadius: 0 }}
      >
        rest
      </button>
      <button
        type="button"
        onClick={() => setEditing(false)}
        className="h-6 px-1 text-fg-tertiary-2 hover:text-fg-secondary"
        style={{ fontSize: 12 }}
        aria-label="cancel editing close limit"
      >
        ✕
      </button>
    </div>
  );
}

function CloseButton({
  disabled,
  upl,
  partialQty,
  totalQty,
  onClick,
}: {
  disabled: boolean;
  /** Best-effort display estimate — null when the analytics feed is stalled.
   *  The close itself never depends on it (the server books its own number). */
  upl: number | null;
  /** When set, this is a PARTIAL close of `partialQty` of `totalQty` contracts. */
  partialQty?: number | null;
  totalQty?: number;
  onClick: () => void;
}) {
  // SAFETY: a mouse click realizes round-trip P&L, so — like the C-C keyboard
  // close and the FLATTEN ALL button — a single click must NOT fire. The first
  // click ARMS (escalated "CLICK AGAIN" label); a confirming second click
  // within 3s closes. Auto-disarms after 3s, and whenever the button goes
  // disabled (a close already fired) or the close size changes under the arm.
  const [armed, setArmed] = useState(false);
  const armTimer = useRef<number | null>(null);
  useEffect(
    () => () => {
      if (armTimer.current) window.clearTimeout(armTimer.current);
    },
    [],
  );
  useEffect(() => {
    setArmed(false);
  }, [disabled, partialQty, totalQty]);

  const label = partialQty != null ? `SCALE OUT ${partialQty}/${totalQty}` : "CLOSE";
  const handleClick = () => {
    if (!armed) {
      setArmed(true);
      if (armTimer.current) window.clearTimeout(armTimer.current);
      armTimer.current = window.setTimeout(() => setArmed(false), 3000);
      return;
    }
    if (armTimer.current) window.clearTimeout(armTimer.current);
    setArmed(false);
    onClick();
  };

  // Filled bearish-red treatment to match the SELL action button —
  // smaller (h-8) since CLOSE doesn't need to compete with BUY/SELL
  // for visual weight, just sit beside them with the same chrome.
  return (
    <button
      type="button"
      onClick={handleClick}
      disabled={disabled}
      title="Realizes round-trip P&L. Click twice to confirm."
      className={[
        "w-full h-8 rounded-btn font-semibold tabular-nums uppercase",
        "transition-colors duration-100",
        disabled
          ? "bg-tier-1 text-fg-disabled cursor-not-allowed"
          : armed
            ? "bg-action-sell-active text-white ring-1 ring-inset ring-white/40"
            : "bg-action-sell hover:bg-action-sell-hover active:bg-action-sell-active text-white",
      ].join(" ")}
      style={{ fontSize: 12, letterSpacing: "0.04em" }}
    >
      {armed ? (
        `CLICK AGAIN — ${label}`
      ) : (
        <>
          {label} · realize{" "}
          <span className="ml-1">{upl == null ? "—" : formatSignedDollar(upl)}</span>
        </>
      )}
    </button>
  );
}

// -- COL 2: THETA SCRUBBER ----------------------------------------------------

function ScrubberCol({
  trade,
  analytics,
  isIntraday,
}: {
  trade: Trade | null;
  analytics: TradeAnalytics | null;
  isIntraday: boolean;
}) {
  const scrubberDte = useActivePosition((s) => s.scrubberDte);
  const elapsedHoursStore = useActivePosition((s) => s.elapsedHours);
  const setScrubberDte = useActivePosition((s) => s.setScrubberDte);
  const setElapsedHours = useActivePosition((s) => s.setElapsedHours);

  if (!trade || !analytics) {
    return (
      <>
        <ColHeader left="Theta scrubber" right="simulate decay →" />
        <Empty>Open a position to simulate decay.</Empty>
      </>
    );
  }

  if (isIntraday) {
    return (
      <HoursScrubber
        trade={trade}
        analytics={analytics}
        scrubberHours={elapsedHoursStore}
        onChange={setElapsedHours}
      />
    );
  }
  return (
    <DaysScrubber
      analytics={analytics}
      scrubberDte={scrubberDte ?? analytics.current_dte_days}
      onChange={setScrubberDte}
    />
  );
}

function HoursScrubber({
  trade,
  analytics,
  scrubberHours,
  onChange,
}: {
  trade: Trade;
  analytics: TradeAnalytics;
  scrubberHours: number | null;
  onChange: (h: number | null) => void;
}) {
  const entry = new Date(trade.entry_date).getTime();
  const expiry = trade.legs[0]?.expiry ?? "";
  const close = new Date(`${expiry}T16:00:00-04:00`).getTime();
  const totalHours = Math.max(0.01, (close - entry) / 3_600_000);
  const liveElapsed = Math.max(
    0,
    Math.min(totalHours, (Date.now() - entry) / 3_600_000),
  );
  const value = scrubberHours ?? liveElapsed;
  const pct = totalHours > 0 ? value / totalHours : 0;

  return (
    <>
      <ColHeader left="Theta scrubber" right="simulate decay →" />
      <div className="px-3 py-1.5 flex flex-col gap-1.5 flex-1 min-h-0 tabular-nums">
        <span
          className="text-fg-tertiary-2 uppercase tracking-label-up"
          style={{ fontSize: 11 }}
        >
          entry → exp
        </span>
        <ScrubberTrack
          pct={pct}
          min={0}
          max={totalHours}
          value={value}
          step={0.05}
          ariaLabel="Hours elapsed since entry"
          onChange={(v) => onChange(v >= totalHours - 0.01 ? totalHours : v)}
        />
        <div className="flex justify-between text-tiny text-fg-tertiary-2">
          <span>ENTRY · NOW {formatHours(value)}</span>
          <span>{formatHours(totalHours)} EXP</span>
        </div>
        <BeDriftPreview analytics={analytics} totalSpan={totalHours} mode="hours" />
        <div className="mt-auto flex items-center justify-between">
          <span
            className="text-tiny text-fg-tertiary-2"
            style={{ fontSize: 11 }}
          >
            BEs widen toward expiry as theta burns
          </span>
          {scrubberHours !== null && (
            <button
              type="button"
              onClick={() => onChange(null)}
              title="Snap the scrubber back to the current time"
              className="text-tiny uppercase tracking-label-up text-amber border border-amber px-1.5 hover:bg-tier-2"
              style={{ borderRadius: 0 }}
            >
              reset → now
            </button>
          )}
        </div>
      </div>
    </>
  );
}

function DaysScrubber({
  analytics,
  scrubberDte,
  onChange,
}: {
  analytics: TradeAnalytics;
  scrubberDte: number;
  onChange: (dte: number | null) => void;
}) {
  const currentDte = analytics.current_dte_days;
  const elapsed = Math.max(0, currentDte - scrubberDte);
  const pct = currentDte > 0 ? elapsed / currentDte : 0;
  return (
    <>
      <ColHeader left="Theta scrubber" right="simulate decay →" />
      <div className="px-3 py-1.5 flex flex-col gap-1.5 flex-1 min-h-0 tabular-nums">
        <span
          className="text-fg-tertiary-2 uppercase tracking-label-up"
          style={{ fontSize: 11 }}
        >
          days remaining
        </span>
        <ScrubberTrack
          pct={pct}
          min={0}
          max={Math.max(1, currentDte)}
          value={elapsed}
          step={1}
          ariaLabel="Days advanced toward expiry"
          onChange={(v) => onChange(currentDte - Math.round(v))}
        />
        <div className="flex justify-between text-tiny text-fg-tertiary-2">
          <span>NOW</span>
          <span>EXP · DTE {scrubberDte}</span>
        </div>
        <BeDriftPreview analytics={analytics} totalSpan={currentDte} mode="days" />
        <div className="mt-auto flex items-center justify-between">
          <span
            className="text-tiny text-fg-tertiary-2"
            style={{ fontSize: 11 }}
          >
            BEs widen toward expiry as theta burns
          </span>
          {scrubberDte !== currentDte && (
            <button
              type="button"
              onClick={() => onChange(null)}
              title="Snap the scrubber back to the current time"
              className="text-tiny uppercase tracking-label-up text-amber border border-amber px-1.5 hover:bg-tier-2"
              style={{ borderRadius: 0 }}
            >
              reset → now
            </button>
          )}
        </div>
      </div>
    </>
  );
}

function ScrubberTrack({
  pct,
  min,
  max,
  value,
  step,
  ariaLabel,
  onChange,
}: {
  pct: number;
  min: number;
  max: number;
  value: number;
  step: number;
  ariaLabel: string;
  onChange: (v: number) => void;
}) {
  return (
    <div className="relative h-3 flex items-center">
      <div className="absolute inset-x-0 h-1 rounded-sm bg-tier-2" />
      <div
        className="absolute h-1 rounded-sm bg-amber"
        style={{ width: `${pct * 100}%` }}
      />
      <div
        aria-hidden
        className="absolute h-3 w-3 rounded-full bg-amber border border-amber"
        style={{ left: `calc(${pct * 100}% - 6px)` }}
      />
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="absolute inset-0 opacity-0 cursor-pointer"
        aria-label={ariaLabel}
        aria-valuemin={min}
        aria-valuemax={max}
        aria-valuenow={value}
      />
    </div>
  );
}

/**
 * Tiny BE drift preview — two faint magenta lines showing how the live
 * breakevens widen as time passes. We don't re-call the analytics
 * endpoint per sample; we interpolate between breakevens_today (now)
 * and breakevens_expiration (worst-case drift) along a linear time axis.
 * That's a close enough illustration of the qualitative behavior for a
 * 90px-tall mini-chart — the on-chart BE lines remain the source of
 * truth for live values.
 */
function BeDriftPreview({
  analytics,
  totalSpan,
  mode,
}: {
  analytics: TradeAnalytics;
  totalSpan: number;
  mode: "hours" | "days";
}) {
  const today = analytics.breakevens_today;
  const expiration = analytics.breakevens_expiration;
  if (!today.length || !expiration.length || totalSpan <= 0) return null;

  // Pick lower/upper BE pairs (straddles have 2; single legs have 1).
  const sortedToday = [...today].sort((a, b) => a - b);
  const sortedExp = [...expiration].sort((a, b) => a - b);
  const lowerToday = sortedToday[0];
  const upperToday = sortedToday[sortedToday.length - 1];
  const lowerExp = sortedExp[0];
  const upperExp = sortedExp[sortedExp.length - 1];

  const minPrice = Math.min(lowerToday, lowerExp);
  const maxPrice = Math.max(upperToday, upperExp);
  const range = Math.max(0.01, maxPrice - minPrice);

  // 30 sample steps from now → expiry; linear interpolation between
  // today and expiration breakevens.
  const steps = 30;
  const lowerPath: string[] = [];
  const upperPath: string[] = [];
  for (let i = 0; i <= steps; i++) {
    const f = i / steps;
    const lowerY = lowerToday * (1 - f) + lowerExp * f;
    const upperY = upperToday * (1 - f) + upperExp * f;
    const x = (i / steps) * 100;
    const yL = 100 - ((lowerY - minPrice) / range) * 100;
    const yU = 100 - ((upperY - minPrice) / range) * 100;
    lowerPath.push(`${i === 0 ? "M" : "L"}${x.toFixed(1)},${yL.toFixed(1)}`);
    upperPath.push(`${i === 0 ? "M" : "L"}${x.toFixed(1)},${yU.toFixed(1)}`);
  }
  return (
    <div className="border border-hairline" style={{ height: 60 }}>
      <svg
        viewBox="0 0 100 100"
        preserveAspectRatio="none"
        className="w-full h-full"
        aria-label={`BE drift preview (${mode})`}
      >
        <path
          d={lowerPath.join(" ")}
          stroke="#C264D8"
          strokeWidth="0.8"
          strokeOpacity="0.55"
          fill="none"
          vectorEffect="non-scaling-stroke"
        />
        <path
          d={upperPath.join(" ")}
          stroke="#C264D8"
          strokeWidth="0.8"
          strokeOpacity="0.55"
          fill="none"
          vectorEffect="non-scaling-stroke"
        />
      </svg>
    </div>
  );
}

// -- COL 3: KEY LEVELS --------------------------------------------------------

function KeyLevelsCol({ symbol }: { symbol: string | null }) {
  // Annotations come from /chart (max_pain, EM, walls, gamma_flip); IV
  // comes from /metrics (iv_rank + iv_rank_status + iv numbers).
  const annotations = useTickerAnnotations(symbol, "1D");
  const metrics = useTickerMetrics(symbol);
  const a = annotations.data?.annotations;
  const m = metrics.data;
  const showOnChart = useChartPrefs((s) => s.showMarketAnnotations);
  const toggle = useChartPrefs((s) => s.toggleMarketAnnotations);

  const allEmpty =
    a?.expected_move_upper == null &&
    a?.expected_move_lower == null &&
    !a?.call_wall &&
    !a?.put_wall &&
    a?.max_pain == null &&
    a?.gamma_flip == null;

  return (
    <>
      <ColHeader left="Key levels" right={symbol ?? ""} />
      <div className="px-3 py-1.5 flex flex-col gap-0.5 flex-1 min-h-0 tabular-nums">
        <LevelRow
          label="EM↑"
          value={fmtPrice(a?.expected_move_upper)}
          tooltip={LEVEL_TOOLTIP["EM↑"]}
        />
        <LevelRow
          label="EM↓"
          value={fmtPrice(a?.expected_move_lower)}
          tooltip={LEVEL_TOOLTIP["EM↓"]}
        />
        <LevelRow
          label="CW"
          value={a?.call_wall ? `$${a.call_wall.strike.toFixed(2)}` : "—"}
          tooltip={LEVEL_TOOLTIP.CW}
        />
        <LevelRow
          label="PW"
          value={a?.put_wall ? `$${a.put_wall.strike.toFixed(2)}` : "—"}
          tooltip={LEVEL_TOOLTIP.PW}
        />
        <LevelRow
          label="MP"
          value={fmtPrice(a?.max_pain)}
          tooltip={LEVEL_TOOLTIP.MP}
        />
        <LevelRow
          label="GF"
          value={fmtPrice(a?.gamma_flip)}
          tooltip={LEVEL_TOOLTIP.GF}
        />
        <div className="border-t border-hairline my-1.5" />
        <LevelRow
          label="IV rank"
          value={
            m?.iv_rank == null
              ? "—"
              : `${m.iv_rank.toFixed(0)}${m.iv_rank_status ? ` · ${m.iv_rank_status}` : ""}`
          }
          tooltip={LEVEL_TOOLTIP.IV}
        />
        <LevelRow
          label="P/C"
          value={m?.pc_ratio == null ? "—" : m.pc_ratio.toFixed(2)}
          tooltip={LEVEL_TOOLTIP["P/C"]}
        />
        {allEmpty && (
          <span
            className="text-fg-tertiary-2 mt-1"
            style={{ fontSize: 11, lineHeight: 1.4 }}
          >
            {annotations.isLoading
              ? "Computing levels from today's option chain…"
              : "Levels compute from the day's option chain — they appear once chain data is available."}
          </span>
        )}
        <div className="mt-auto pt-2 flex items-center justify-between">
          <span
            className="uppercase tracking-label-up text-fg-tertiary-2"
            style={{ fontSize: 11 }}
          >
            show on chart
          </span>
          <ToggleSwitch on={showOnChart} onClick={toggle} />
        </div>
      </div>
    </>
  );
}

function LevelRow({
  label,
  value,
  tooltip,
}: {
  label: string;
  value: string;
  tooltip?: string;
}) {
  return (
    <div
      className="flex items-baseline justify-between text-tiny"
      title={tooltip}
    >
      <span
        className="uppercase tracking-label-up text-fg-tertiary-2"
        style={{ fontSize: 11 }}
      >
        {label}
      </span>
      <span className="text-fg-secondary tabular-nums">{value}</span>
    </div>
  );
}

function ToggleSwitch({ on, onClick }: { on: boolean; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={on}
      title={on ? "Hide market-structure overlays on chart" : "Show market-structure overlays on chart"}
      className={[
        "h-4 w-7 border relative",
        on ? "border-amber bg-tier-3" : "border-hairline bg-tier-1",
      ].join(" ")}
      style={{ borderRadius: 0 }}
    >
      <span
        aria-hidden
        className={`absolute top-0.5 h-2.5 w-2.5 transition-all ${on ? "bg-amber" : "bg-fg-tertiary-2"}`}
        style={{ left: on ? 14 : 2, borderRadius: 0 }}
      />
    </button>
  );
}

// -- COL 4: TODAY -------------------------------------------------------------

function TodayCol({
  trades,
  activeTradeId,
}: {
  trades: Trade[];
  activeTradeId: number | null;
}) {
  const todayIso = new Date().toISOString().slice(0, 10);
  const todayTrades = useMemo(
    () =>
      trades.filter((t) => {
        // Include all trades opened today (paper) OR open positions
        // regardless of date — the latter so a held position shows up
        // until close.
        if (t.status === "open") return true;
        if (t.entry_date.startsWith(todayIso)) return true;
        if (t.exit_date && t.exit_date.startsWith(todayIso)) return true;
        return false;
      }),
    [trades, todayIso],
  );
  const netPnl = useMemo(
    () =>
      todayTrades.reduce((sum, t) => {
        if (t.status === "closed" && t.exit_date?.startsWith(todayIso)) {
          return sum + (t.realized_pnl ?? 0);
        }
        return sum;
      }, 0),
    [todayTrades, todayIso],
  );
  const netCls =
    netPnl > 0 ? "text-bullish" : netPnl < 0 ? "text-bearish" : "text-fg-secondary";

  return (
    <>
      <ColHeader
        left="Today"
        right={<span className={`tabular-nums ${netCls}`}>{formatSignedDollar(netPnl)}</span>}
      />
      <div className="flex flex-col flex-1 min-h-0 overflow-y-auto">
        {todayTrades.length === 0 && <Empty>No trades today yet.</Empty>}
        {todayTrades.map((t) => (
          <TodayRow key={t.id} trade={t} isActive={t.id === activeTradeId} />
        ))}
      </div>
      <div className="border-t border-hairline px-3 py-1 shrink-0">
        <Link
          to="/journal"
          className="text-tiny uppercase tracking-label-up text-fg-tertiary-2 hover:text-amber"
        >
          view full journal →
        </Link>
      </div>
    </>
  );
}

function TodayRow({ trade, isActive }: { trade: Trade; isActive: boolean }) {
  const open = trade.status === "open";
  const pnl = trade.realized_pnl ?? 0;
  const pnlCls =
    open
      ? "text-fg-tertiary-2"
      : pnl > 0
        ? "text-bullish"
        : pnl < 0
          ? "text-bearish"
          : "text-fg-secondary";
  const winLabel = open ? "open" : pnl > 0 ? "win" : pnl < 0 ? "loss" : "even";
  const accent = open ? "border-l-2 border-position" : "border-l-2 border-transparent";
  return (
    <div
      className={`flex flex-col gap-0.5 px-3 py-1 border-b border-hairline tabular-nums ${accent} ${
        isActive ? "bg-tier-2" : ""
      }`}
    >
      <div className="flex items-baseline justify-between text-tiny">
        <span className="text-fg-secondary" title="Eastern Time (market clock)">
          {formatClockEt(open ? trade.entry_date : trade.exit_date ?? trade.entry_date)}
        </span>
        <span className="text-fg-tertiary-2">
          {STRATEGY_LABELS[trade.strategy] ?? trade.strategy}
        </span>
      </div>
      <div className="flex items-baseline justify-between" style={{ fontSize: 12 }}>
        <span className="text-fg-tertiary-2">{trade.symbol}</span>
        <span className={pnlCls}>
          {open ? "—" : formatSignedDollar(pnl)} · {winLabel}
        </span>
      </div>
    </div>
  );
}

// -- shared -------------------------------------------------------------------

function ColHeader({
  left,
  right,
}: {
  left: React.ReactNode;
  right: React.ReactNode;
}) {
  return (
    <div className="flex items-baseline justify-between px-3 py-1 border-b border-hairline bg-tier-1 shrink-0">
      <span className="text-tiny uppercase tracking-label-up text-fg-secondary">
        {left}
      </span>
      <span
        className="uppercase tracking-label-up text-fg-tertiary-2"
        style={{ fontSize: 11 }}
      >
        {right}
      </span>
    </div>
  );
}

function Empty({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex-1 flex items-center justify-center text-tiny text-fg-tertiary-2 px-4 text-center">
      {children}
    </div>
  );
}

function fmtPrice(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return "—";
  return `$${v.toFixed(2)}`;
}

function formatSignedDollar(v: number): string {
  if (!Number.isFinite(v)) return "$0.00";
  const sign = v > 0 ? "+" : v < 0 ? "−" : "";
  return `${sign}$${Math.abs(v).toFixed(2)}`;
}

function formatTimestamp(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  try {
    return d.toLocaleTimeString("en-US", {
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
      timeZone: "America/New_York",
    });
  } catch {
    return iso.slice(11, 16);
  }
}

function formatClockEt(iso: string): string {
  return formatTimestamp(iso);
}

function formatHours(h: number): string {
  // A missing/malformed leg expiry yields NaN hours-to-expiry; guard so the
  // theta-scrubber label never renders "NaNhNaNm".
  if (!Number.isFinite(h)) return "—";
  const total = Math.max(0, h);
  const hours = Math.floor(total);
  const minutes = Math.floor((total - hours) * 60);
  return `${hours}h${minutes.toString().padStart(2, "0")}m`;
}

function summarizeLegs(trade: Trade): string {
  const strikes = trade.legs.map((l) => l.strike).join("/");
  return `K ${strikes}`;
}

function totalContracts(trade: Trade): number {
  // Per-leg contracts. Show the max across legs as "the contract count"
  // — straddles balance both sides at the same size, single legs trivially
  // match. This avoids summing 1+1=2 for a 1-contract straddle.
  if (!trade.legs.length) return 1;
  return trade.legs.reduce((m, l) => Math.max(m, l.contracts), 0);
}
