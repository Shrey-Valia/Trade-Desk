import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import type { IChartApi, ISeriesApi, MouseEventParams, Time } from "lightweight-charts";
import {
  DrawingManager,
  getToolRegistry,
  type Anchor,
  type DrawingCategory,
  type DrawingEvent,
  type SerializedDrawing,
} from "lightweight-charts-drawing";

import { colors } from "@/lib/design";
import { useDrawings } from "@/stores/drawings";
import { isDrawingInteracting, useDrawingTool } from "@/stores/drawingTool";

interface Props {
  /** Live refs from the host chart. Read at draw time so the layer always
   *  binds to the CURRENT series — which lightweight-charts recreates on
   *  every timeframe / bars rebuild. */
  chartRef: React.MutableRefObject<IChartApi | null>;
  seriesRef: React.MutableRefObject<ISeriesApi<"Candlestick"> | null>;
  symbol: string;
}

/**
 * Drawing-tools layer — full TradingView-style markup kit.
 *
 * Backed by `lightweight-charts-drawing`'s DrawingManager, which renders every
 * tool (trendlines, fibs, channels, shapes, text, …) through lightweight-charts
 * PRIMITIVES — so drawings paint inside the chart's own canvas and track pan,
 * zoom, and timeframe automatically (no separate projection canvas).
 *
 * Lifecycle is the load-bearing part:
 *  - The manager attaches once the chart + series refs are live (polled in an
 *    rAF loop, because this child mounts before the parent creates the chart).
 *  - lightweight-charts tears down + recreates the candle series on every
 *    bars / timeframe / color change (and on the 60s bars refetch). We detect
 *    that by series identity and `detach()` + re-`attach()` + re-import — the
 *    same re-attach discipline `attachPositionOverlay` uses for breakeven lines.
 *  - The drawings store is the source of truth; manager change events export to
 *    it, and we import from it on attach / symbol change. Persistence is
 *    SUPPRESSED during programmatic import (clearAll + importDrawings emit
 *    events that would otherwise overwrite the store with an empty/partial set).
 *
 * Touch note: the engine binds mousedown (not pointer/touch) for drag-create,
 * so the toolbar is desktop-only (`hidden md:flex`); existing drawings still
 * render on mobile (view-only).
 */
export function ChartDrawingLayer({ chartRef, seriesRef, symbol }: Props) {
  const setSymbolDrawings = useDrawings((s) => s.setSymbolDrawings);
  const hasDrawings = useDrawings((s) => (s.drawings[symbol]?.length ?? 0) > 0);

  const activeTool = useDrawingTool((s) => s.activeTool);
  const selectedId = useDrawingTool((s) => s.selectedId);
  const setActiveTool = useDrawingTool((s) => s.setActiveTool);
  const setSelectedId = useDrawingTool((s) => s.setSelectedId);
  const interacting = useDrawingTool(isDrawingInteracting);

  const managerRef = useRef<DrawingManager | null>(null);
  const attachedSeriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const suppressPersistRef = useRef(false);
  // Lets the symbol-change effect trigger a re-import without re-running the
  // mount effect (the manager + handlers are created there).
  const reimportRef = useRef<(() => void) | null>(null);

  const symbolRef = useRef(symbol);
  symbolRef.current = symbol;

  const [toolsOpen, setToolsOpen] = useState(false);

  // --- Interactive creation glue ---------------------------------------------
  // v0.1.1's DrawingManager.setActiveTool only flips an internal flag — it has
  // NO path that creates a drawing from an armed tool (creation logic lives in
  // an unwired InteractionHandler class). So we drive creation ourselves:
  // collect clicks (chart.subscribeClick yields chart-space coords directly, no
  // pixel math), and once the tool's `requiredAnchors` points are placed, build
  // it via the registry and addDrawing() — which persists via the events above.
  const creationAnchorsRef = useRef<Anchor[]>([]);
  const creationSubscribedRef = useRef(false);
  const activeToolRef = useRef<string | null>(activeTool);
  activeToolRef.current = activeTool;
  const creationClickRef = useRef<((p: MouseEventParams) => void) | null>(null);
  if (!creationClickRef.current) {
    creationClickRef.current = (param: MouseEventParams) => {
      const reset = () => {
        creationAnchorsRef.current = [];
        managerRef.current?.setActiveTool(null);
        setActiveTool(null);
      };
      const type = activeToolRef.current;
      if (!type) return; // cursor mode → let the manager handle selection
      const chart = chartRef.current;
      const series = seriesRef.current;
      if (!chart || !series || !param.point) return;
      const price = series.coordinateToPrice(param.point.y);
      const time = (param.time ?? chart.timeScale().coordinateToTime(param.point.x)) as Time | null;
      if (price == null || time == null) return; // clicked outside the data area

      creationAnchorsRef.current.push({ time, price: Number(price) });
      const need = getToolRegistry().get(type)?.requiredAnchors ?? 2;
      if (creationAnchorsRef.current.length < need) return; // need more points

      const anchors = creationAnchorsRef.current.slice();
      let options: Record<string, unknown> = {};
      if (TEXT_TOOLS.has(type)) {
        const txt = window.prompt("Text", "");
        if (txt == null) {
          reset();
          return;
        }
        options = { text: txt };
      }
      const drawing = getToolRegistry().createDrawing(
        type,
        newId(),
        anchors,
        { lineColor: colors.accentCyan, lineWidth: 2 },
        options,
      );
      if (drawing) managerRef.current?.addDrawing(drawing); // emits drawing:added → persisted
      reset(); // return to cursor (restores pan via the `interacting` effect)
    };
  }

  // Tool catalog, grouped by category — built once from the engine's registry
  // so we never hardcode the 68 tool ids/names.
  const groups = useMemo(() => buildGroups(), []);

  // Attach / re-attach lifecycle (mount once; reads refs live every frame).
  useEffect(() => {
    let raf = 0;
    let subscribedChart: IChartApi | null = null;
    const offs: Array<() => void> = [];

    const factory = (type: string, d: SerializedDrawing) =>
      getToolRegistry().createDrawing(type, d.id, d.anchors, d.style, d.options);

    const exportToStore = () => {
      const m = managerRef.current;
      if (!m || suppressPersistRef.current) return;
      setSymbolDrawings(symbolRef.current, m.exportDrawings());
    };

    const importFromStore = () => {
      const m = managerRef.current;
      if (!m) return;
      suppressPersistRef.current = true;
      try {
        m.clearAll();
        const data = useDrawings.getState().drawings[symbolRef.current] ?? [];
        if (data.length) m.importDrawings(data, factory);
      } finally {
        suppressPersistRef.current = false;
      }
    };
    reimportRef.current = importFromStore;

    const wire = (m: DrawingManager) => {
      offs.push(m.on("drawing:added", exportToStore));
      offs.push(m.on("drawing:removed", exportToStore));
      offs.push(m.on("drawing:updated", exportToStore));
      offs.push(m.on("drawing:cleared", exportToStore));
      offs.push(
        m.on("drawing:selected", (e: DrawingEvent) => setSelectedId(e.drawingId ?? null)),
      );
      offs.push(m.on("drawing:deselected", () => setSelectedId(null)));
      offs.push(m.on("tool:changed", (e: DrawingEvent) => setActiveTool(e.toolType ?? null)));
    };

    const frame = () => {
      raf = requestAnimationFrame(frame);
      const chart = chartRef.current;
      const series = seriesRef.current;
      if (!chart || !series) return;
      const container = chart.chartElement();

      if (!managerRef.current) {
        const m = new DrawingManager();
        m.attach(chart, series, container);
        managerRef.current = m;
        attachedSeriesRef.current = series;
        wire(m);
        importFromStore();
        // Our creation handler lives on the chart (which persists across series
        // rebuilds), so subscribe once.
        if (creationClickRef.current && !creationSubscribedRef.current) {
          chart.subscribeClick(creationClickRef.current);
          subscribedChart = chart;
          creationSubscribedRef.current = true;
        }
      } else if (attachedSeriesRef.current !== series) {
        // The bars effect rebuilt the candle series — re-point the manager at
        // the new series and repaint from the store.
        const m = managerRef.current;
        m.detach();
        m.attach(chart, series, container);
        attachedSeriesRef.current = series;
        importFromStore();
      }
    };

    raf = requestAnimationFrame(frame);
    return () => {
      cancelAnimationFrame(raf);
      offs.forEach((off) => off());
      if (creationSubscribedRef.current && subscribedChart && creationClickRef.current) {
        try {
          subscribedChart.unsubscribeClick(creationClickRef.current);
        } catch {
          /* chart already disposed */
        }
        creationSubscribedRef.current = false;
      }
      if (managerRef.current) {
        managerRef.current.detach();
        managerRef.current = null;
      }
      attachedSeriesRef.current = null;
      reimportRef.current = null;
    };
    // chartRef / seriesRef are stable ref objects; setters are stable.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Symbol change: drawings are per-symbol, so disarm, clear selection, and
  // load the new symbol's set. (The series also rebuilds on a symbol switch,
  // which would re-import anyway, but doing it here makes the swap immediate.)
  useEffect(() => {
    creationAnchorsRef.current = [];
    setActiveTool(null);
    setSelectedId(null);
    setToolsOpen(false);
    managerRef.current?.setActiveTool(null);
    managerRef.current?.deselectAll();
    reimportRef.current?.();
    // setters stable; reimportRef read live.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [symbol]);

  // Delete the selected drawing via keyboard. Ignored while typing in a field
  // so it can't hijack form input elsewhere on the page.
  useEffect(() => {
    if (!selectedId) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Delete" && e.key !== "Backspace") return;
      const el = document.activeElement;
      const tag = el?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || (el as HTMLElement)?.isContentEditable) {
        return;
      }
      e.preventDefault();
      managerRef.current?.removeDrawing(selectedId);
      setSelectedId(null);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedId]);

  // While a tool is armed (or a drawing is selected for editing), disable
  // lightweight-charts pan/zoom so a click-drag draws/edits instead of
  // scrolling the chart. The engine itself never disables panning or calls
  // preventDefault, so without this a drag-created tool (trendline, brush,
  // rectangle…) just pans the chart and no drawing is made. Restored to the
  // chart's defaults in cursor mode. The chart instance is created once and
  // survives series rebuilds, so applyOptions here persists correctly.
  useEffect(() => {
    const chart = chartRef.current;
    if (!chart) return;
    chart.applyOptions({ handleScroll: !interacting, handleScale: !interacting });
    // chartRef is a stable ref object; read .current live.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [interacting]);

  const armTool = (type: string) => {
    creationAnchorsRef.current = [];
    setActiveTool(type); // drive UI state directly — don't depend on the event
    setSelectedId(null);
    managerRef.current?.deselectAll();
    managerRef.current?.setActiveTool(type); // keep the manager's handleClick a no-op
    setToolsOpen(false);
  };

  const useCursor = () => {
    creationAnchorsRef.current = [];
    setActiveTool(null);
    setSelectedId(null);
    managerRef.current?.setActiveTool(null);
    managerRef.current?.deselectAll();
    setToolsOpen(false);
  };

  const deleteSelected = () => {
    if (!selectedId) return;
    managerRef.current?.removeDrawing(selectedId);
    setSelectedId(null);
  };

  const clearAll = () => {
    managerRef.current?.clearAll();
    setSelectedId(null);
    setToolsOpen(false);
  };

  // Icon-rail button styling — flush buttons inside one bordered rail,
  // reading like a TradingView / Topstep tool rail.
  const railBtn = (active: boolean) =>
    [
      "h-8 w-8 flex items-center justify-center transition-colors",
      active ? "text-amber bg-tier-2" : "text-fg-tertiary hover:text-fg-secondary hover:bg-tier-2",
    ].join(" ");
  const directTypes = RAIL.map((r) => r.type);
  const moreActive = activeTool !== null && !directTypes.includes(activeTool);

  return (
    <>
      {/* Outside-click backdrop while the tools menu is open. */}
      {toolsOpen && (
        <div
          className="absolute inset-0"
          style={{ zIndex: 19, pointerEvents: "auto" }}
          onClick={() => setToolsOpen(false)}
        />
      )}

      {/* Vertical tool strip — desktop only (touch drawing is unsupported by
          the engine). Drawings themselves still render on mobile. */}
      <div
        className="absolute left-1.5 top-1/2 -translate-y-1/2 hidden md:flex items-start"
        style={{ zIndex: 20 }}
      >
        <div className="flex flex-col bg-tier-0/90 border border-hairline">
          <button
            type="button"
            onClick={useCursor}
            title="Cursor — select & move drawings"
            aria-label="Cursor / select"
            aria-pressed={activeTool === null}
            className={railBtn(activeTool === null)}
          >
            <Glyph name="cursor" />
          </button>
          <Divider />
          {RAIL.map((t) => (
            <button
              key={t.type}
              type="button"
              onClick={() => armTool(t.type)}
              title={t.label}
              aria-label={t.label}
              aria-pressed={activeTool === t.type}
              className={railBtn(activeTool === t.type)}
            >
              <Glyph name={t.icon} />
            </button>
          ))}
          <Divider />
          <button
            type="button"
            onClick={() => setToolsOpen((o) => !o)}
            title="All drawing tools"
            aria-label="All drawing tools"
            aria-expanded={toolsOpen}
            className={railBtn(moreActive || toolsOpen)}
          >
            <Glyph name="more" />
          </button>
          {(selectedId || hasDrawings) && <Divider />}
          {selectedId && (
            <button
              type="button"
              onClick={deleteSelected}
              title="Delete selected (Del)"
              aria-label="Delete selected drawing"
              className="h-8 w-8 flex items-center justify-center text-fg-tertiary hover:text-bearish hover:bg-tier-2"
            >
              <Glyph name="trash" />
            </button>
          )}
          {hasDrawings && (
            <button
              type="button"
              onClick={clearAll}
              title="Clear all drawings on this symbol"
              aria-label="Clear all drawings"
              className="h-8 w-8 flex items-center justify-center text-fg-tertiary hover:text-fg-secondary hover:bg-tier-2"
            >
              <Glyph name="eraser" />
            </button>
          )}
        </div>

        {/* Flyout: every tool, grouped by category. */}
        {toolsOpen && (
          <div
            className="ml-1 bg-tier-0 border border-hairline overflow-y-auto"
            style={{ zIndex: 21, width: 176, maxHeight: 320 }}
          >
            {groups.map((g) => (
              <div key={g.category}>
                <div className="px-2 pt-1.5 pb-0.5 text-tiny uppercase tracking-label-up text-fg-tertiary sticky top-0 bg-tier-0">
                  {g.label}
                </div>
                {g.tools.map((t) => (
                  <button
                    key={t.type}
                    type="button"
                    onClick={() => armTool(t.type)}
                    className={[
                      "w-full text-left px-2 py-1 text-tiny",
                      activeTool === t.type
                        ? "text-amber bg-tier-2"
                        : "text-fg-secondary hover:bg-tier-2",
                    ].join(" ")}
                  >
                    {t.name}
                  </button>
                ))}
              </div>
            ))}
          </div>
        )}
      </div>
    </>
  );
}

// Category display order + labels for the flyout. Any category present in the
// registry but missing here is appended under its raw key (defensive).
const CATEGORY_ORDER: DrawingCategory[] = [
  "line",
  "channel",
  "pitchfork",
  "fibonacci",
  "gann",
  "forecasting",
  "measurement",
  "shape",
  "annotation",
  "trading",
];

const CATEGORY_LABELS: Record<string, string> = {
  line: "Lines",
  channel: "Channels",
  pitchfork: "Pitchforks",
  fibonacci: "Fibonacci",
  gann: "Gann",
  forecasting: "Forecast",
  measurement: "Measure",
  shape: "Shapes",
  annotation: "Notes",
  trading: "Positions",
};

interface ToolGroup {
  category: string;
  label: string;
  tools: { type: string; name: string }[];
}

function buildGroups(): ToolGroup[] {
  const byCat = new Map<string, { type: string; name: string }[]>();
  for (const t of getToolRegistry().getAll()) {
    const arr = byCat.get(t.category) ?? [];
    arr.push({ type: t.type, name: t.name });
    byCat.set(t.category, arr);
  }
  const ordered = CATEGORY_ORDER.filter((c) => byCat.has(c));
  const extras = [...byCat.keys()].filter((c) => !CATEGORY_ORDER.includes(c as DrawingCategory));
  return [...ordered, ...extras].map((c) => ({
    category: c,
    label: CATEGORY_LABELS[c] ?? c,
    tools: byCat.get(c)!,
  }));
}

// Tools whose drawing needs a text value — we prompt for it on completion.
const TEXT_TOOLS = new Set([
  "text-annotation",
  "anchored-text",
  "callout",
  "comment",
  "note",
  "signpost",
  "price-note",
]);

function newId(): string {
  try {
    if (typeof crypto !== "undefined" && "randomUUID" in crypto) return crypto.randomUUID();
  } catch {
    /* fall through */
  }
  return `d_${Math.random().toString(36).slice(2)}`;
}

// The most-used tools, surfaced as direct icon buttons on the rail (the long
// tail lives behind the "more" flyout). Types match the engine's registry ids.
const RAIL: { type: string; label: string; icon: string }[] = [
  { type: "trend-line", label: "Trend line", icon: "trend" },
  { type: "horizontal-line", label: "Horizontal line", icon: "hline" },
  { type: "horizontal-ray", label: "Horizontal ray", icon: "ray" },
  { type: "parallel-channel", label: "Parallel channel", icon: "channel" },
  { type: "fib-retracement", label: "Fib retracement", icon: "fib" },
  { type: "andrews-pitchfork", label: "Pitchfork", icon: "fork" },
  { type: "rectangle", label: "Rectangle", icon: "rect" },
  { type: "brush", label: "Brush", icon: "brush" },
  { type: "text-annotation", label: "Text", icon: "text" },
  { type: "date-price-range", label: "Measure", icon: "ruler" },
];

function Divider() {
  return <div className="mx-1.5 border-t border-hairline" aria-hidden />;
}

// Minimal line-art glyphs (16px, currentColor) for the tool rail.
function Glyph({ name }: { name: string }) {
  const dot = (cx: number, cy: number, r = 1.6) => (
    <circle cx={cx} cy={cy} r={r} fill="currentColor" stroke="none" />
  );
  let inner: ReactNode = null;
  switch (name) {
    case "cursor":
      inner = (<><path d="M12 4v4M12 16v4M4 12h4M16 12h4" />{dot(12, 12, 1.5)}</>);
      break;
    case "trend":
      inner = (<><path d="M5 18L19 6" />{dot(5, 18)}{dot(19, 6)}</>);
      break;
    case "hline":
      inner = (<><path d="M4 12h16" />{dot(12, 12)}</>);
      break;
    case "ray":
      inner = (<><path d="M5 12h15" />{dot(5, 12, 1.9)}</>);
      break;
    case "channel":
      inner = <path d="M4 17L17 5M7 20L20 8" />;
      break;
    case "fib":
      inner = <path d="M4 6h16M7 10h10M7 14h10M4 18h16" />;
      break;
    case "fork":
      inner = (<><path d="M4 20L14 10M14 10l2.5-6M14 10l6-2.5" />{dot(14, 10, 1.4)}</>);
      break;
    case "rect":
      inner = <rect x="4.5" y="6.5" width="15" height="11" />;
      break;
    case "brush":
      inner = <path d="M4 18c3-7 6-7 8 0s5 7 8 0" />;
      break;
    case "text":
      inner = <path d="M6 6h12M12 6v12" />;
      break;
    case "ruler":
      inner = (<><rect x="3.5" y="9.5" width="17" height="5" /><path d="M8 9.5v2.2M12 9.5v2.2M16 9.5v2.2" /></>);
      break;
    case "more":
      inner = (<>{dot(12, 6, 1.4)}{dot(12, 12, 1.4)}{dot(12, 18, 1.4)}</>);
      break;
    case "trash":
      inner = <path d="M5 7h14M10 7V5h4v2M6.5 7l1 12h9l1-12" />;
      break;
    case "eraser":
      inner = <path d="M6 16L14 8l5 5-4 4H8z M5 20h14" />;
      break;
  }
  return (
    <svg
      width="16"
      height="16"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      {inner}
    </svg>
  );
}
