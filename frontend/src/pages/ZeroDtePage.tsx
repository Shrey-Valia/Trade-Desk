/**
 * Zero-DTE paper-trade prototype.
 *
 * INTENTIONALLY MINIMAL. The brief said even ugly is fine — the point
 * is to validate the felt interaction: open an ATM SPY straddle, watch
 * the breakeven lines slide toward spot as the session decays. Don't
 * polish this. Doesn't touch the existing chart/journal/analytics code;
 * it's a sibling route that uses the existing intraday SPY bars + a
 * bespoke /api/zerodte backend for ATM-chain lookup and live BS-mark
 * repricing at fractional T.
 *
 * Position state lives in localStorage so a reload survives. Single
 * open position at a time. Closed positions roll cumulative realized
 * P&L into the session header (`rpl`) and the paper balance.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  CandlestickSeries,
  ColorType,
  CrosshairMode,
  HistogramSeries,
  LineStyle,
  createChart,
  createSeriesMarkers,
  type IChartApi,
  type IPriceLine,
  type ISeriesApi,
  type ISeriesMarkersPluginApi,
  type SeriesMarker,
  type Time,
  type UTCTimestamp,
} from "lightweight-charts";

import { PageHeader } from "@/components/layout/PageHeader";
import { useTickerChart } from "@/hooks/useTickerChart";
import { colors } from "@/lib/design";
import { fetchZeroDteChain, fetchZeroDteMark } from "@/lib/api";
import {
  STARTING_BALANCE,
  type ZeroDteAccount,
  type ZeroDteChain,
  type ZeroDteMark,
  type ZeroDtePosition,
} from "@/types/zerodte";

const POSITION_COLOR = "#D4537E";   // magenta — same "my position" semantic
const POS_LS_KEY = "td:zerodte:position";
const ACCT_LS_KEY = "td:zerodte:account";
const MARK_POLL_MS = 5_000;          // 5s live mark refresh when scrubber is off

function loadPosition(): ZeroDtePosition | null {
  try {
    const raw = localStorage.getItem(POS_LS_KEY);
    return raw ? (JSON.parse(raw) as ZeroDtePosition) : null;
  } catch {
    return null;
  }
}

function loadAccount(): ZeroDteAccount {
  try {
    const raw = localStorage.getItem(ACCT_LS_KEY);
    if (raw) return JSON.parse(raw) as ZeroDteAccount;
  } catch {
    /* fallthrough */
  }
  return { balance: STARTING_BALANCE, rpl: 0 };
}

export function ZeroDtePage() {
  const [position, setPositionState] = useState<ZeroDtePosition | null>(loadPosition);
  const [account, setAccountState] = useState<ZeroDteAccount>(loadAccount);
  const [chain, setChain] = useState<ZeroDteChain | null>(null);
  const [mark, setMark] = useState<ZeroDteMark | null>(null);
  const [scrubberHours, setScrubberHours] = useState<number | null>(null);  // null = real time
  const [opening, setOpening] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const setPosition = useCallback((p: ZeroDtePosition | null) => {
    setPositionState(p);
    if (p) localStorage.setItem(POS_LS_KEY, JSON.stringify(p));
    else localStorage.removeItem(POS_LS_KEY);
  }, []);

  const setAccount = useCallback((a: ZeroDteAccount) => {
    setAccountState(a);
    localStorage.setItem(ACCT_LS_KEY, JSON.stringify(a));
  }, []);

  // Initial chain fetch — also refreshed when the user opens.
  const refreshChain = useCallback(async () => {
    setError(null);
    try {
      const c = await fetchZeroDteChain();
      setChain(c);
    } catch (e) {
      setError((e as Error).message);
    }
  }, []);

  useEffect(() => {
    void refreshChain();
  }, [refreshChain]);

  // Mark refresh. Re-fires every 5s when no scrubber, immediately on
  // scrubber change.
  useEffect(() => {
    if (!position) {
      setMark(null);
      return;
    }
    let cancelled = false;
    const tick = async () => {
      try {
        const m = await fetchZeroDteMark(position, scrubberHours);
        if (!cancelled) setMark(m);
      } catch (e) {
        if (!cancelled) setError((e as Error).message);
      }
    };
    void tick();
    if (scrubberHours !== null) return; // stop polling when scrubbing
    const id = window.setInterval(() => void tick(), MARK_POLL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, [position, scrubberHours]);

  const onOpenStraddle = async () => {
    if (!chain) {
      setError("Chain not loaded yet — wait a moment.");
      return;
    }
    setOpening(true);
    try {
      // Prefer ask (we're buying premium); fall back to last → mid → 0.
      const pickPrice = (q: typeof chain.call) => {
        if (q.ask && q.ask > 0) return q.ask;
        if (q.last && q.last > 0) return q.last;
        if (q.bid && q.ask && q.bid > 0 && q.ask > 0) return (q.bid + q.ask) / 2;
        return 0;
      };
      const callPrice = pickPrice(chain.call);
      const putPrice = pickPrice(chain.put);
      if (callPrice === 0 || putPrice === 0) {
        setError("Indicative quotes unavailable — try again in a moment.");
        return;
      }
      const pos: ZeroDtePosition = {
        strike: chain.strike,
        entry_spot: chain.spot,
        entry_call_price: callPrice,
        entry_put_price: putPrice,
        entry_time_iso: new Date().toISOString(),
        expiry_iso: chain.expiry,
        contracts: 1,
      };
      setScrubberHours(null);
      setPosition(pos);
    } finally {
      setOpening(false);
    }
  };

  const onClose = () => {
    if (!position || !mark) return;
    // Settle UPL into RPL + balance.
    const next: ZeroDteAccount = {
      rpl: account.rpl + mark.upl_dollar,
      balance: account.balance + mark.upl_dollar,
    };
    setAccount(next);
    setPosition(null);
    setScrubberHours(null);
  };

  const headerNumbers = useMemo(() => {
    const upl = position && mark ? mark.upl_dollar : 0;
    return {
      upl,
      rpl: account.rpl,
      balance: account.balance + upl,
    };
  }, [position, mark, account]);

  // Max scrubber range — hours from entry to expiry. Until a position
  // is open we render a disabled scrubber for layout consistency.
  const maxScrubberHours = useMemo(() => {
    if (!position) return 0;
    const entry = new Date(position.entry_time_iso).getTime();
    const close = new Date(`${position.expiry_iso}T16:00:00-04:00`).getTime();
    return Math.max(0, (close - entry) / 3_600_000);
  }, [position]);

  const effectiveElapsed =
    scrubberHours !== null ? scrubberHours : mark?.elapsed_hours ?? 0;

  return (
    <div className="flex flex-col h-full min-h-0 bg-tier-0">
      <PageHeader title="0DTE" subtitle="prototype · SPY only" />
      <PaperHeader numbers={headerNumbers} />
      <Toolbar
        hasPosition={!!position}
        chain={chain}
        opening={opening}
        onOpen={onOpenStraddle}
        onClose={onClose}
        onRefreshChain={() => void refreshChain()}
      />
      {error && (
        <div className="px-4 py-1.5 text-tiny text-bearish border-b border-hairline bg-tier-1">
          {error}
        </div>
      )}
      <PositionStrip position={position} chain={chain} mark={mark} />
      <main className="flex-1 min-h-0 relative">
        <ZeroDteChartView position={position} mark={mark} />
      </main>
      <Scrubber
        enabled={!!position}
        elapsed={effectiveElapsed}
        max={maxScrubberHours}
        decayPct={mark?.decay_pct ?? 0}
        onChange={setScrubberHours}
      />
      <Disclosure />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Header — UPL / RPL / BALANCE
// ---------------------------------------------------------------------------

function PaperHeader({
  numbers,
}: {
  numbers: { upl: number; rpl: number; balance: number };
}) {
  return (
    <div className="flex items-stretch border-b border-hairline bg-tier-1 shrink-0">
      <HeaderCell label="UPL" value={numbers.upl} signed />
      <HeaderCell label="RPL" value={numbers.rpl} signed />
      <HeaderCell label="Balance" value={numbers.balance} />
      <div className="flex-1" />
    </div>
  );
}

function HeaderCell({
  label,
  value,
  signed,
}: {
  label: string;
  value: number;
  signed?: boolean;
}) {
  const cls = signed
    ? value > 0
      ? "text-bullish"
      : value < 0
      ? "text-bearish"
      : "text-fg-secondary"
    : "text-fg-primary";
  const sign = signed && value > 0 ? "+" : value < 0 ? "−" : "";
  const formatted = `${sign}$${Math.abs(value).toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
  return (
    <div className="flex flex-col px-4 py-2 border-r border-hairline" style={{ minWidth: 140 }}>
      <span
        className="text-tiny uppercase tracking-label-up text-fg-tertiary"
        style={{ fontSize: 9 }}
      >
        {label}
      </span>
      <span className={`text-medium font-medium tabular-nums ${cls}`}>{formatted}</span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Toolbar — OPEN / CLOSE / refresh chain
// ---------------------------------------------------------------------------

function Toolbar({
  hasPosition,
  chain,
  opening,
  onOpen,
  onClose,
  onRefreshChain,
}: {
  hasPosition: boolean;
  chain: ZeroDteChain | null;
  opening: boolean;
  onOpen: () => void;
  onClose: () => void;
  onRefreshChain: () => void;
}) {
  return (
    <div className="flex items-center gap-3 px-4 py-2 border-b border-hairline bg-tier-0 shrink-0">
      {!hasPosition ? (
        <button
          type="button"
          onClick={onOpen}
          disabled={!chain || opening}
          className="h-7 px-3 text-tiny uppercase tracking-label-up border border-amber text-amber bg-tier-1 hover:bg-tier-2 disabled:opacity-50"
          style={{ borderRadius: 0 }}
        >
          {opening ? "Opening…" : `+ Open straddle @ ${chain ? chain.strike : "—"}`}
        </button>
      ) : (
        <button
          type="button"
          onClick={onClose}
          className="h-7 px-3 text-tiny uppercase tracking-label-up border border-bearish text-bearish bg-tier-1 hover:bg-tier-2"
          style={{ borderRadius: 0 }}
        >
          Close position
        </button>
      )}
      <button
        type="button"
        onClick={onRefreshChain}
        className="h-7 px-2 text-tiny uppercase tracking-label-up border border-hairline text-fg-tertiary hover:bg-tier-2"
        style={{ borderRadius: 0 }}
      >
        Refresh chain
      </button>
      {chain && (
        <span className="text-tiny text-fg-tertiary tabular-nums">
          SPY ${chain.spot.toFixed(2)} · ATM ${chain.strike} · {chain.expiry}
        </span>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Position strip — entry vs mark, breakevens-today, decay %
// ---------------------------------------------------------------------------

function PositionStrip({
  position,
  chain,
  mark,
}: {
  position: ZeroDtePosition | null;
  chain: ZeroDteChain | null;
  mark: ZeroDteMark | null;
}) {
  if (!position) return null;
  const bes = mark?.breakevens_today ?? [];
  const expBes = mark?.breakevens_expiration ?? [];
  return (
    <div className="flex items-center gap-4 px-4 py-1.5 border-b border-hairline bg-tier-0 shrink-0 text-tiny tabular-nums">
      <span className="text-fg-tertiary uppercase tracking-label-up" style={{ fontSize: 9 }}>
        Position
      </span>
      <span className="text-fg-primary">
        Long straddle ${position.strike} · {position.contracts}c
      </span>
      <span className="text-fg-tertiary">
        entry call ${position.entry_call_price.toFixed(2)} +
        put ${position.entry_put_price.toFixed(2)} =
        ${(position.entry_call_price + position.entry_put_price).toFixed(2)}
      </span>
      {mark && (
        <span className="text-fg-tertiary">
          mark ${mark.mark_total.toFixed(2)}
        </span>
      )}
      {bes.length === 2 && (
        <span className="text-fg-primary" style={{ color: POSITION_COLOR }}>
          BE today {bes[0].toFixed(2)} / {bes[1].toFixed(2)}
        </span>
      )}
      {expBes.length === 2 && (
        <span className="text-fg-tertiary">
          BE expiry {expBes[0].toFixed(2)} / {expBes[1].toFixed(2)}
        </span>
      )}
      {chain && mark && (
        <span className="text-fg-tertiary">spot ${mark.spot.toFixed(2)}</span>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Scrubber — fast-forward time to expiry
// ---------------------------------------------------------------------------

function Scrubber({
  enabled,
  elapsed,
  max,
  decayPct,
  onChange,
}: {
  enabled: boolean;
  elapsed: number;
  max: number;
  decayPct: number;
  onChange: (hours: number | null) => void;
}) {
  if (!enabled) {
    return null;
  }
  return (
    <div className="flex items-center gap-3 px-4 py-2 border-t border-hairline bg-tier-1 shrink-0">
      <span className="text-tiny uppercase tracking-label-up text-fg-secondary shrink-0"
            style={{ fontSize: 9 }}>
        Time
      </span>
      <span className="text-tiny text-fg-tertiary tabular-nums w-16 text-right">
        +{elapsed.toFixed(1)}h
      </span>
      <input
        type="range"
        min={0}
        max={Math.max(0.01, max)}
        step={0.05}
        value={elapsed}
        onChange={(e) => onChange(Number(e.target.value))}
        className="theta-scrubber flex-1 min-w-0"
      />
      <span className="text-tiny text-fg-tertiary tabular-nums w-16">
        close
      </span>
      <DecayBar pct={decayPct} />
      <button
        type="button"
        onClick={() => onChange(null)}
        className="text-tiny uppercase tracking-label-up text-fg-tertiary hover:text-amber"
      >
        live
      </button>
    </div>
  );
}

function DecayBar({ pct }: { pct: number }) {
  const fill = Math.max(0, Math.min(1, pct));
  return (
    <div className="flex items-center gap-1">
      <span
        className="text-tiny uppercase tracking-label-up text-fg-tertiary"
        style={{ fontSize: 9 }}
      >
        Decay
      </span>
      <div
        className="h-1.5 bg-tier-2 border border-hairline"
        style={{ width: 80 }}
        aria-label={`Session decay ${(fill * 100).toFixed(0)}%`}
      >
        <div
          className="h-full"
          style={{ width: `${fill * 100}%`, background: "#D4537E" }}
        />
      </div>
      <span className="text-tiny text-fg-tertiary tabular-nums" style={{ fontSize: 9 }}>
        {(fill * 100).toFixed(0)}%
      </span>
    </div>
  );
}

function Disclosure() {
  return (
    <div className="px-4 py-1 border-t border-hairline bg-tier-1 text-tiny text-fg-tertiary"
         style={{ fontSize: 9 }}>
      Paper · indicative pricing (approximate). BS math is real; price inputs from the free Alpaca feed.
    </div>
  );
}

// ---------------------------------------------------------------------------
// Chart — SPY intraday + entry marker + horizontal BE lines (today + expiry)
// ---------------------------------------------------------------------------

function ZeroDteChartView({
  position,
  mark,
}: {
  position: ZeroDtePosition | null;
  mark: ZeroDteMark | null;
}) {
  // Reuse the existing intraday SPY pipeline. 1D = minute bars, RTH only.
  const { data, isLoading, isError, error } = useTickerChart("SPY", "1D");
  const bars = data?.bars ?? [];
  if (isError) {
    return (
      <div className="p-4 text-tiny text-bearish">
        {(error as Error)?.message ?? "Chart load failed"}
      </div>
    );
  }
  if (isLoading || bars.length === 0) {
    return (
      <div className="absolute inset-0 flex items-center justify-center text-tiny text-fg-tertiary">
        Loading SPY intraday…
      </div>
    );
  }
  return <ZeroDteChartCanvas bars={bars} position={position} mark={mark} />;
}

interface CanvasProps {
  bars: { t: string; o: number; h: number; l: number; c: number; v: number }[];
  position: ZeroDtePosition | null;
  mark: ZeroDteMark | null;
}

function ZeroDteChartCanvas({ bars, position, mark }: CanvasProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const volumeRef = useRef<ISeriesApi<"Histogram"> | null>(null);
  const beLinesRef = useRef<IPriceLine[]>([]);
  const markersRef = useRef<ISeriesMarkersPluginApi<Time> | null>(null);

  // Build chart once.
  useEffect(() => {
    const host = containerRef.current;
    if (!host) return;
    const chart = createChart(host, {
      width: host.clientWidth,
      height: host.clientHeight,
      layout: {
        background: { type: ColorType.Solid, color: colors.bgTier0 },
        textColor: colors.fgSecondary,
        fontFamily:
          '"IBM Plex Mono", ui-monospace, SFMono-Regular, Menlo, Consolas, monospace',
        fontSize: 11,
        attributionLogo: false,
      },
      grid: { vertLines: { visible: false }, horzLines: { visible: false } },
      crosshair: {
        mode: CrosshairMode.Normal,
        vertLine: { color: colors.fgTertiary, labelBackgroundColor: colors.bgTier1 },
        horzLine: { color: colors.fgTertiary, labelBackgroundColor: colors.bgTier1 },
      },
      timeScale: {
        borderColor: colors.borderHairline,
        timeVisible: true,
        secondsVisible: false,
      },
      rightPriceScale: {
        borderColor: colors.borderHairline,
        scaleMargins: { top: 0.08, bottom: 0.25 },
      },
      handleScroll: true,
      handleScale: true,
    });
    chartRef.current = chart;

    const candles = chart.addSeries(CandlestickSeries, {
      upColor: colors.bullish,
      downColor: colors.bearish,
      wickUpColor: colors.bullish,
      wickDownColor: colors.bearish,
      borderVisible: false,
      priceLineVisible: false,
      lastValueVisible: true,
    });
    candleRef.current = candles;

    const volume = chart.addSeries(HistogramSeries, {
      priceFormat: { type: "volume" },
      priceScaleId: "",
      color: colors.fgTertiary,
    });
    volume.priceScale().applyOptions({ scaleMargins: { top: 0.85, bottom: 0 } });
    volumeRef.current = volume;

    const ro = new ResizeObserver(() => {
      if (containerRef.current && chartRef.current) {
        chartRef.current.applyOptions({
          width: containerRef.current.clientWidth,
          height: containerRef.current.clientHeight,
        });
      }
    });
    ro.observe(host);

    return () => {
      ro.disconnect();
      chart.remove();
      chartRef.current = null;
      candleRef.current = null;
      volumeRef.current = null;
      beLinesRef.current = [];
      markersRef.current = null;
    };
  }, []);

  // Data refresh.
  useEffect(() => {
    const candles = candleRef.current;
    const volume = volumeRef.current;
    if (!candles || !volume) return;
    candles.setData(
      bars.map((b) => ({
        time: toTime(b.t),
        open: b.o,
        high: b.h,
        low: b.l,
        close: b.c,
      })),
    );
    volume.setData(
      bars.map((b) => ({
        time: toTime(b.t),
        value: b.v,
        color: b.c >= b.o ? `${colors.bullish}80` : `${colors.bearish}80`,
      })),
    );
    chartRef.current?.timeScale().fitContent();
  }, [bars]);

  // Position overlay — entry marker + horizontal BE lines.
  useEffect(() => {
    const candles = candleRef.current;
    if (!candles) return;
    for (const l of beLinesRef.current) {
      try {
        candles.removePriceLine(l);
      } catch {
        /* already removed */
      }
    }
    beLinesRef.current = [];
    if (markersRef.current) markersRef.current.setMarkers([]);

    if (!position) return;

    // Entry marker.
    const entryT = toTime(position.entry_time_iso);
    const firstT = bars.length ? toTime(bars[0].t) : entryT;
    const lastT = bars.length ? toTime(bars[bars.length - 1].t) : entryT;
    const clampedT = Math.min(
      Math.max(entryT as unknown as number, firstT as unknown as number),
      lastT as unknown as number,
    ) as unknown as UTCTimestamp;
    const markers: SeriesMarker<Time>[] = [
      {
        time: clampedT,
        position: "belowBar",
        color: POSITION_COLOR,
        shape: "arrowUp",
        text: `ENTRY ${position.strike}`,
        size: 1,
      },
    ];
    if (markersRef.current == null) {
      markersRef.current = createSeriesMarkers(candles, markers);
    } else {
      markersRef.current.setMarkers(markers);
    }

    // Today-BE lines (the thing we're testing). Solid magenta, thick.
    if (mark) {
      for (const be of mark.breakevens_today) {
        beLinesRef.current.push(
          candles.createPriceLine({
            price: be,
            color: POSITION_COLOR,
            lineStyle: LineStyle.Solid,
            lineWidth: 2,
            axisLabelVisible: true,
            title: "BE",
          }),
        );
      }
      // Expiration-BE ghosts.
      for (const be of mark.breakevens_expiration) {
        beLinesRef.current.push(
          candles.createPriceLine({
            price: be,
            color: POSITION_COLOR,
            lineStyle: LineStyle.Dotted,
            lineWidth: 1,
            axisLabelVisible: true,
            title: "BE✕",
          }),
        );
      }
    }
  }, [position, mark, bars]);

  return <div ref={containerRef} className="absolute inset-0" />;
}

function toTime(iso: string): UTCTimestamp {
  return Math.floor(new Date(iso).getTime() / 1000) as UTCTimestamp;
}
