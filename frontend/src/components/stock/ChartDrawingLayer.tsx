import { useEffect, useRef, useState } from "react";
import type {
  IChartApi,
  ISeriesApi,
  MouseEventParams,
  Time,
} from "lightweight-charts";

import { colors } from "@/lib/design";
import { useDrawings, type Drawing } from "@/stores/drawings";

interface Props {
  /** Live refs from the host chart. Read at draw time so the layer always
   *  projects against the CURRENT series — which lightweight-charts
   *  recreates on every timeframe / bars rebuild. */
  chartRef: React.MutableRefObject<IChartApi | null>;
  seriesRef: React.MutableRefObject<ISeriesApi<"Candlestick"> | null>;
  symbol: string;
}

// Click-to-select tolerance, in CSS pixels.
const HIT_PX = 6;

const EMPTY: Drawing[] = [];

/**
 * Drawing-tools overlay (Phase 1: horizontal lines).
 *
 * A transparent <canvas> sits over the chart, `pointer-events: none`, so
 * it never steals pan/zoom from lightweight-charts. Placement and
 * selection go through chart.subscribeClick (clicks, not drags), so the
 * chart stays fully interactive. Lines are stored in PRICE coordinates
 * (Zustand, persisted) and re-projected to pixels via
 * series.priceToCoordinate() on a requestAnimationFrame dirty-check loop
 * — so they track pan, zoom, timeframe change, and price-scale drag with
 * no missed events, and stay pinned to their price level.
 *
 * This layer is fully additive: it adds no series and no price lines, and
 * never touches the position / breakeven overlay.
 */
export function ChartDrawingLayer({ chartRef, seriesRef, symbol }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  const drawingsMap = useDrawings((s) => s.drawings);
  const addDrawing = useDrawings((s) => s.addDrawing);
  const removeDrawing = useDrawings((s) => s.removeDrawing);
  const lines = drawingsMap[symbol] ?? EMPTY;

  const [tool, setTool] = useState<"none" | "hline">("none");
  const [selectedId, setSelectedId] = useState<string | null>(null);

  // Live mirrors for the click handler + rAF loop (both set up once).
  const linesRef = useRef(lines);
  linesRef.current = lines;
  const toolRef = useRef(tool);
  toolRef.current = tool;
  const selectedRef = useRef(selectedId);
  selectedRef.current = selectedId;
  const symbolRef = useRef(symbol);
  symbolRef.current = symbol;

  // Switching symbol clears the ephemeral UI state (selection + tool);
  // the drawings themselves are per-symbol in the store.
  useEffect(() => {
    setSelectedId(null);
    setTool("none");
  }, [symbol]);

  // Stable click handler — created once, reads refs. Placement when the
  // tool is active; otherwise hit-test for selection.
  const handlerRef = useRef<((p: MouseEventParams<Time>) => void) | null>(null);
  if (!handlerRef.current) {
    handlerRef.current = (param: MouseEventParams<Time>) => {
      const series = seriesRef.current;
      if (!series || !param.point) return;
      const y = param.point.y;

      if (toolRef.current === "hline") {
        const price = series.coordinateToPrice(y);
        if (price == null) return;
        addDrawing(symbolRef.current, {
          id: newId(),
          kind: "hline",
          price: Number(price),
        });
        return;
      }

      // Selection: nearest line within tolerance, else deselect.
      let hit: string | null = null;
      let best = HIT_PX;
      for (const ln of linesRef.current) {
        const ly = series.priceToCoordinate(ln.price);
        if (ly == null) continue;
        const d = Math.abs(ly - y);
        if (d <= best) {
          best = d;
          hit = ln.id;
        }
      }
      setSelectedId(hit);
    };
  }

  // Render + lifecycle loop. Subscribes to chart clicks once the chart
  // exists (child effects run before the parent creates the chart, so we
  // can't subscribe in a plain mount effect), and repaints only when a
  // projected coordinate or the canvas size actually changes.
  useEffect(() => {
    let raf = 0;
    let subscribed = false;
    let lastSig = "";

    const frame = () => {
      raf = requestAnimationFrame(frame);
      const chart = chartRef.current;
      const series = seriesRef.current;
      const canvas = canvasRef.current;
      if (!chart || !series || !canvas) return;

      if (!subscribed && handlerRef.current) {
        chart.subscribeClick(handlerRef.current);
        subscribed = true;
      }

      const wrapper = canvas.parentElement;
      if (!wrapper) return;
      const cw = wrapper.clientWidth;
      const ch = wrapper.clientHeight;
      if (cw === 0 || ch === 0) return;
      const paneW = chart.timeScale().width() || cw;
      // Bottom of the price pane (above the time axis) — lines whose
      // price falls outside the visible range are hidden rather than
      // drawn over the axis, matching native price-line behavior.
      const paneBottom = ch - chart.timeScale().height();

      const items = linesRef.current.map((ln) => ({
        id: ln.id,
        price: ln.price,
        y: series.priceToCoordinate(ln.price),
      }));

      const sig =
        `${cw}x${ch}|${paneW}|${selectedRef.current ?? ""}|` +
        items.map((i) => `${i.id}:${i.y == null ? "-" : i.y.toFixed(1)}`).join(",");
      if (sig === lastSig) return;
      lastSig = sig;

      const dpr = window.devicePixelRatio || 1;
      if (canvas.width !== Math.round(cw * dpr) || canvas.height !== Math.round(ch * dpr)) {
        canvas.width = Math.round(cw * dpr);
        canvas.height = Math.round(ch * dpr);
        canvas.style.width = `${cw}px`;
        canvas.style.height = `${ch}px`;
      }

      const ctx = canvas.getContext("2d");
      if (!ctx) return;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, cw, ch);
      ctx.font = '9px "IBM Plex Mono", ui-monospace, monospace';
      ctx.textBaseline = "alphabetic";

      for (const it of items) {
        if (it.y == null || it.y < 0 || it.y > paneBottom) continue;
        const selected = it.id === selectedRef.current;
        const color = selected ? colors.accentAmber : colors.accentCyan;
        ctx.strokeStyle = color;
        ctx.lineWidth = selected ? 1.5 : 1;
        ctx.beginPath();
        ctx.moveTo(0, it.y);
        ctx.lineTo(paneW, it.y);
        ctx.stroke();
        ctx.fillStyle = color;
        ctx.fillText(it.price.toFixed(2), 4, it.y - 3);
      }
    };

    raf = requestAnimationFrame(frame);
    return () => {
      cancelAnimationFrame(raf);
      if (subscribed && chartRef.current && handlerRef.current) {
        try {
          chartRef.current.unsubscribeClick(handlerRef.current);
        } catch {
          /* chart already disposed */
        }
      }
    };
    // chartRef / seriesRef are stable ref objects; loop reads .current live.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Delete the selected line via keyboard. Ignored while typing in a
  // field so it can't hijack form input elsewhere on the page.
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
      removeDrawing(symbol, selectedId);
      setSelectedId(null);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [selectedId, symbol, removeDrawing]);

  const deleteSelected = () => {
    if (!selectedId) return;
    removeDrawing(symbol, selectedId);
    setSelectedId(null);
  };

  return (
    <>
      <canvas
        ref={canvasRef}
        className="absolute inset-0"
        style={{ pointerEvents: "none", zIndex: 5 }}
      />
      {/* Vertical tool strip on the left edge — the conventional spot for
          chart drawing tools, clear of the top-left legend. Only the
          buttons are pointer-interactive; the rest passes through. */}
      <div
        className="absolute left-1.5 top-1/2 -translate-y-1/2 flex flex-col gap-1"
        style={{ zIndex: 20 }}
      >
        <button
          type="button"
          onClick={() => setTool((t) => (t === "hline" ? "none" : "hline"))}
          title="Horizontal line — click the chart to place a line at a price"
          aria-label="Horizontal line tool"
          aria-pressed={tool === "hline"}
          className={[
            "h-7 w-7 flex items-center justify-center text-medium border",
            tool === "hline"
              ? "border-amber text-amber bg-tier-2"
              : "border-hairline text-fg-tertiary bg-tier-0/80 hover:bg-tier-2 hover:text-fg-secondary",
          ].join(" ")}
          style={{ borderRadius: 0, lineHeight: 1 }}
        >
          ―
        </button>
        {selectedId && (
          <button
            type="button"
            onClick={deleteSelected}
            title="Delete selected line (Del)"
            aria-label="Delete selected line"
            className="h-7 w-7 flex items-center justify-center text-tiny border border-bearish text-bearish bg-tier-0/80 hover:bg-tier-2"
            style={{ borderRadius: 0 }}
          >
            ✕
          </button>
        )}
      </div>
    </>
  );
}

function newId(): string {
  try {
    if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
      return crypto.randomUUID();
    }
  } catch {
    /* fall through */
  }
  return `d_${Date.now().toString(36)}_${Math.floor(Math.random() * 1e6).toString(36)}`;
}
