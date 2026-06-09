import { useMemo } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { NewsPanel } from "@/components/positions/NewsPanel";
import { useTickerAnnotations } from "@/hooks/useTickerChart";
import { useTickerMetrics } from "@/hooks/useTickerMetrics";
import { useTradeAnalytics } from "@/hooks/useTradeAnalytics";
import { useTrades } from "@/hooks/useTrades";
import { updateTrade } from "@/lib/api";
import { useActivePosition } from "@/stores/activePosition";
import { useChartPrefs } from "@/stores/chartPrefs";
import { useSelectedTicker } from "@/stores/selectedTicker";
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
  const trades = tradesData?.trades ?? [];
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

  // No active position → collapsed single-row strip: just KEY LEVELS
  // inline + a TODAY summary row. Hides OPEN POSITION and THETA
  // SCRUBBER entirely (they're empty placeholders when no trade is
  // active) and gives the freed vertical space back to the chart.
  if (!activeTrade) {
    return (
      <div
        className="border-t border-hairline bg-tier-0 shrink-0 flex flex-col"
        style={{ height: 80 }}
      >
        <KeyLevelsInline symbol={symbol} />
        <TodayInline trades={trades} />
      </div>
    );
  }

  return (
    <div
      className="grid border-t border-hairline bg-tier-0 shrink-0"
      style={{
        height: 280,
        // 5 equal columns — the original four shrink proportionally to
        // make room for the NEWS panel; row height is unchanged.
        gridTemplateColumns: "1fr 1fr 1fr 1fr 1fr",
      }}
    >
      <Column>
        <OpenPositionCol trade={activeTrade} analytics={analytics} />
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
        <NewsPanel symbol={symbol} />
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
    items.push({ label: "EM↑", value: fmtPrice(a.expected_move_upper) });
  if (a?.expected_move_lower != null)
    items.push({ label: "EM↓", value: fmtPrice(a.expected_move_lower) });
  if (a?.call_wall)
    items.push({
      label: "CW",
      value: `$${a.call_wall.strike.toFixed(2)}`,
      tooltip: INLINE_VOL_TOOLTIP.CW,
    });
  if (a?.put_wall)
    items.push({
      label: "PW",
      value: `$${a.put_wall.strike.toFixed(2)}`,
      tooltip: INLINE_VOL_TOOLTIP.PW,
    });
  if (a?.max_pain != null)
    items.push({
      label: "MP",
      value: fmtPrice(a.max_pain),
      tooltip: INLINE_VOL_TOOLTIP.MP,
    });
  if (a?.gamma_flip != null)
    items.push({
      label: "GF",
      value: fmtPrice(a.gamma_flip),
      tooltip: INLINE_VOL_TOOLTIP.GF,
    });
  if (m?.iv_rank != null)
    items.push({ label: "IV", value: `${m.iv_rank.toFixed(0)}` });

  return (
    <div
      className="flex items-center px-3 border-b border-hairline bg-tier-1 tabular-nums"
      style={{ height: 44, gap: 16 }}
    >
      <span
        className="uppercase tracking-label-up text-fg-tertiary shrink-0"
        style={{ fontSize: 10, letterSpacing: "0.08em" }}
      >
        Key levels
      </span>
      <span className="text-fg-tertiary-2 shrink-0" style={{ fontSize: 11 }}>
        {symbol ?? ""}
      </span>
      {items.length === 0 ? (
        <span className="text-fg-tertiary-2" style={{ fontSize: 11 }}>
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
          style={{ fontSize: 10, letterSpacing: "0.08em" }}
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
        style={{ fontSize: 10, letterSpacing: "0.06em" }}
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

// Same disclosure copy as the full-column tooltip; pinned here so the
// inline strip can reach it without importing from the lower section.
const INLINE_VOL_TOOLTIP = {
  CW: "Call wall — computed from today's volume as OI proxy (free tier limitation)",
  PW: "Put wall — computed from today's volume as OI proxy (free tier limitation)",
  MP: "Max pain — computed from today's volume as OI proxy (free tier limitation)",
  GF: "Gamma flip — computed from today's volume as OI proxy (free tier limitation)",
};

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
        background: on ? "#F0A030" : "#2A3142",
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
          background: "#FFFFFF",
          transition: "left 100ms ease-out",
        }}
      />
    </button>
  );
}

function TodayInline({ trades }: { trades: Trade[] }) {
  const todayIso = new Date().toISOString().slice(0, 10);
  const { net, count } = useMemo(() => {
    let n = 0;
    let c = 0;
    for (const t of trades) {
      if (t.status === "closed" && t.exit_date?.startsWith(todayIso)) {
        n += t.realized_pnl ?? 0;
        c += 1;
      } else if (t.status === "open" && t.entry_date.startsWith(todayIso)) {
        c += 1;
      }
    }
    return { net: n, count: c };
  }, [trades, todayIso]);
  const netCls =
    net > 0 ? "text-bullish" : net < 0 ? "text-bearish" : "text-fg-secondary";
  return (
    <div
      className="flex items-center gap-3 px-3 tabular-nums"
      style={{ height: 36 }}
    >
      <span className="text-tiny uppercase tracking-label-up text-fg-secondary shrink-0">
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
  return (
    <div className="border-r border-hairline last:border-r-0 flex flex-col min-h-0 overflow-hidden">
      {children}
    </div>
  );
}

// -- COL 1: OPEN POSITION -----------------------------------------------------

function OpenPositionCol({
  trade,
  analytics,
}: {
  trade: Trade | null;
  analytics: TradeAnalytics | null;
}) {
  const queryClient = useQueryClient();
  const setActiveTradeId = useActivePosition((s) => s.setTradeId);
  const close = useMutation({
    mutationFn: async () => {
      if (!trade || !analytics) return null;
      return updateTrade(trade.id, {
        status: "closed",
        exit_date: new Date().toISOString(),
        exit_underlying_price: analytics.spot,
        realized_pnl: analytics.unrealized_pnl,
      });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["journal", "trades"] });
      // Account state polls every 5s; invalidate so the header
      // BAL/MLL/RP&L update immediately after the close books P&L.
      queryClient.invalidateQueries({ queryKey: ["account", "state"] });
      setActiveTradeId(null);
    },
  });

  return (
    <>
      <ColHeader
        left="Open position"
        right={trade ? `DTE ${analytics?.current_dte_days ?? "—"}` : ""}
      />
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
          <div className="text-fg-tertiary-2 mt-0.5" style={{ fontSize: 10 }}>
            {summarizeLegs(trade)} · entry{" "}
            {formatTimestamp(trade.entry_date)} ·{" "}
            {totalContracts(trade)} contract{totalContracts(trade) === 1 ? "" : "s"}
          </div>
          <div className="border-t border-hairline my-1.5" />
          <div className="flex items-baseline justify-between">
            <span
              className="uppercase tracking-label-up text-fg-tertiary-2"
              style={{ fontSize: 9 }}
            >
              UPL
            </span>
            <span
              className={`text-large font-medium ${
                (analytics?.unrealized_pnl ?? 0) > 0
                  ? "text-bullish"
                  : (analytics?.unrealized_pnl ?? 0) < 0
                    ? "text-bearish"
                    : "text-fg-secondary"
              }`}
            >
              {formatSignedDollar(analytics?.unrealized_pnl ?? 0)}
            </span>
          </div>
          {analytics && (
            <>
              <GreeksGrid g={analytics} />
              <BeRange be={analytics.breakevens_today} />
              <RiskRow analytics={analytics} />
            </>
          )}
          <div className="mt-auto pt-2">
            <CloseButton
              disabled={!analytics || close.isPending}
              upl={analytics?.unrealized_pnl ?? 0}
              onClick={() => close.mutate()}
            />
          </div>
        </div>
      )}
    </>
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
        borderBottom: "6px solid #D946EF",
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
      <span className="text-fg-tertiary-2" style={{ fontSize: 10 }}>
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
        style={{ fontSize: 9 }}
      >
        {label}
      </span>
      <span className={`text-tiny tabular-nums ${cls}`}>{value}</span>
    </div>
  );
}

function CloseButton({
  disabled,
  upl,
  onClick,
}: {
  disabled: boolean;
  upl: number;
  onClick: () => void;
}) {
  // Filled bearish-red treatment to match the SELL action button —
  // smaller (h-8) since CLOSE doesn't need to compete with BUY/SELL
  // for visual weight, just sit beside them with the same chrome.
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className={[
        "w-full h-8 rounded-btn font-semibold tabular-nums uppercase",
        "transition-colors duration-100",
        disabled
          ? "bg-tier-1 text-fg-disabled cursor-not-allowed"
          : "bg-action-sell hover:bg-action-sell-hover active:bg-action-sell-active text-white",
      ].join(" ")}
      style={{ fontSize: 12, letterSpacing: "0.04em" }}
    >
      CLOSE · realize <span className="ml-1">
        {formatSignedDollar(upl)}
      </span>
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
          style={{ fontSize: 9 }}
        >
          today's session
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
          <span>NOW · {formatHours(value)}</span>
          <span>{formatHours(totalHours)} EXP</span>
        </div>
        <BeDriftPreview analytics={analytics} totalSpan={totalHours} mode="hours" />
        <div className="mt-auto flex items-center justify-between">
          <span
            className="text-tiny text-fg-tertiary-2"
            style={{ fontSize: 9 }}
          >
            BEs widen toward expiry as theta burns
          </span>
          <button
            type="button"
            onClick={() => onChange(null)}
            className="text-tiny uppercase tracking-label-up text-fg-tertiary-2 hover:text-amber"
            disabled={scrubberHours === null}
          >
            reset
          </button>
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
          style={{ fontSize: 9 }}
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
            style={{ fontSize: 9 }}
          >
            BEs widen toward expiry as theta burns
          </span>
          <button
            type="button"
            onClick={() => onChange(null)}
            className="text-tiny uppercase tracking-label-up text-fg-tertiary-2 hover:text-amber"
            disabled={scrubberDte === currentDte}
          >
            reset
          </button>
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
          stroke="#D946EF"
          strokeWidth="0.8"
          strokeOpacity="0.55"
          fill="none"
          vectorEffect="non-scaling-stroke"
        />
        <path
          d={upperPath.join(" ")}
          stroke="#D946EF"
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

  return (
    <>
      <ColHeader left="Key levels" right={symbol ?? ""} />
      <div className="px-3 py-1.5 flex flex-col gap-0.5 flex-1 min-h-0 tabular-nums">
        <LevelRow label="EM↑" value={fmtPrice(a?.expected_move_upper)} />
        <LevelRow label="EM↓" value={fmtPrice(a?.expected_move_lower)} />
        <LevelRow
          label="CW"
          value={a?.call_wall ? `$${a.call_wall.strike.toFixed(2)}` : "—"}
          tooltip={VOL_PROXY_TOOLTIP.CW}
        />
        <LevelRow
          label="PW"
          value={a?.put_wall ? `$${a.put_wall.strike.toFixed(2)}` : "—"}
          tooltip={VOL_PROXY_TOOLTIP.PW}
        />
        <LevelRow
          label="MP"
          value={fmtPrice(a?.max_pain)}
          tooltip={VOL_PROXY_TOOLTIP.MP}
        />
        <LevelRow
          label="GF"
          value={fmtPrice(a?.gamma_flip)}
          tooltip={VOL_PROXY_TOOLTIP.GF}
        />
        <div className="border-t border-hairline my-1.5" />
        <LevelRow
          label="IV rank"
          value={
            m?.iv_rank == null
              ? "—"
              : `${m.iv_rank.toFixed(0)}${m.iv_rank_status ? ` · ${m.iv_rank_status}` : ""}`
          }
        />
        <div className="mt-auto pt-2 flex items-center justify-between">
          <span
            className="uppercase tracking-label-up text-fg-tertiary-2"
            style={{ fontSize: 9 }}
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
        style={{ fontSize: 9 }}
      >
        {label}
      </span>
      <span className="text-fg-secondary tabular-nums">{value}</span>
    </div>
  );
}

// Disclosure for the four volume-derived KEY LEVELS values. The free
// Alpaca tier doesn't expose open_interest, so call wall / put wall /
// max pain / gamma flip are computed against today's per-contract
// VOLUME as an OI proxy. EM±/IV are NOT volume-derived and don't
// carry this disclosure.
const VOL_PROXY_TOOLTIP = {
  CW: "Call wall — computed from today's volume as OI proxy (free tier limitation)",
  PW: "Put wall — computed from today's volume as OI proxy (free tier limitation)",
  MP: "Max pain — computed from today's volume as OI proxy (free tier limitation)",
  GF: "Gamma flip — computed from today's volume as OI proxy (free tier limitation)",
};

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
        <span className="text-fg-secondary">
          {formatClockEt(open ? trade.entry_date : trade.exit_date ?? trade.entry_date)}
        </span>
        <span className="text-fg-tertiary-2">
          {STRATEGY_LABELS[trade.strategy] ?? trade.strategy}
        </span>
      </div>
      <div className="flex items-baseline justify-between" style={{ fontSize: 10 }}>
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
        style={{ fontSize: 9 }}
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
