import { useEffect, useRef, useState } from "react";
import type { IChartApi, ISeriesApi } from "lightweight-charts";

import { colors } from "@/lib/design";
import { isDrawingInteracting, useDrawingTool } from "@/stores/drawingTool";

export interface BracketOverlay {
  tradeId: number;
  /** Committed bracket levels (underlying price). null = not set. */
  stopLoss: number | null;
  takeProfit: number | null;
  /** Underlying at entry — used to seed sensible default offsets. */
  entryUnderlying: number;
  /** Live underlying spot. */
  spot: number;
  /** Active position's payoff curve (today), for the projected-P&L label. */
  prices: number[];
  payoffToday: number[];
  /** Persist a new pair (drag-release / add / clear). */
  onChange: (b: { stop_loss: number | null; take_profit: number | null }) => void;
}

interface Props {
  chartRef: React.MutableRefObject<IChartApi | null>;
  seriesRef: React.MutableRefObject<ISeriesApi<"Candlestick"> | null>;
  brackets: BracketOverlay;
}

type Kind = "sl" | "tp";

/**
 * Draggable stop-loss / take-profit lines (TopstepX-style brackets) for the
 * active position, on the underlying price axis. SL is red, TP is green;
 * each line shows its price + the projected P&L of the position at that
 * underlying level. Drag a line to move it (persists on release), the +SL /
 * +TP buttons add one, the × clears it. The order monitor closes the
 * position when the underlying crosses a set level (OCO).
 *
 * Line Y is positioned IMPERATIVELY each frame (priceToCoordinate) so panning
 * never re-renders React; React only re-renders on add/clear/drag (when the
 * price — and thus the label — actually changes).
 */
export function PositionBracketsLayer({ chartRef, seriesRef, brackets }: Props) {
  const rootRef = useRef<HTMLDivElement>(null);
  const slRowRef = useRef<HTMLDivElement>(null);
  const tpRowRef = useRef<HTMLDivElement>(null);

  // Transient drag: { kind, price }. While set, that line follows the cursor
  // and the committed prop is ignored until release.
  const [drag, setDrag] = useState<{ kind: Kind; price: number } | null>(null);

  const displayed = (kind: Kind): number | null => {
    if (drag && drag.kind === kind) return drag.price;
    return kind === "sl" ? brackets.stopLoss : brackets.takeProfit;
  };

  // Live mirror for the rAF loop (avoids re-subscribing the loop on changes).
  const dispRef = useRef<{ sl: number | null; tp: number | null }>({ sl: null, tp: null });
  dispRef.current = { sl: displayed("sl"), tp: displayed("tp") };

  // Position each line's Y from the current series projection, every frame.
  useEffect(() => {
    let raf = 0;
    const frame = () => {
      raf = requestAnimationFrame(frame);
      const series = seriesRef.current;
      const chart = chartRef.current;
      const root = rootRef.current;
      if (!series || !chart || !root) return;
      const paneBottom = root.clientHeight - chart.timeScale().height();
      const place = (el: HTMLDivElement | null, price: number | null) => {
        if (!el) return;
        if (price == null) {
          el.style.display = "none";
          return;
        }
        const y = series.priceToCoordinate(price);
        if (y == null || y < 0 || y > paneBottom) {
          el.style.display = "none";
          return;
        }
        el.style.display = "";
        el.style.top = `${y}px`;
      };
      place(slRowRef.current, dispRef.current.sl);
      place(tpRowRef.current, dispRef.current.tp);
    };
    raf = requestAnimationFrame(frame);
    return () => cancelAnimationFrame(raf);
    // refs are stable; loop reads .current live.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Right-click at a price → context menu to SET the SL/TP there (audit
  // wave 6 chart-trading v1). Listens on the chart host (this overlay is
  // pointer-transparent), maps clientY → price through the same series
  // projection the drag path uses, and skips the time-scale strip. The
  // browser menu is suppressed only when the click maps to a price.
  const [ctxMenu, setCtxMenu] = useState<{ x: number; y: number; price: number } | null>(
    null,
  );
  useEffect(() => {
    const root = rootRef.current;
    const host = root?.parentElement;
    if (!host) return;
    const onCtx = (e: MouseEvent) => {
      const series = seriesRef.current;
      const chart = chartRef.current;
      if (!series || !chart || !root) return;
      const rect = root.getBoundingClientRect();
      const yIn = e.clientY - rect.top;
      const paneBottom = root.clientHeight - chart.timeScale().height();
      if (yIn < 0 || yIn > paneBottom) return;
      const price = series.coordinateToPrice(yIn);
      if (price == null || Number(price) <= 0) return;
      e.preventDefault();
      setCtxMenu({
        x: Math.min(e.clientX - rect.left, rect.width - 130),
        y: yIn,
        price: round2(Number(price)),
      });
    };
    host.addEventListener("contextmenu", onCtx);
    return () => host.removeEventListener("contextmenu", onCtx);
    // refs are stable; handler reads .current live.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  useEffect(() => {
    if (!ctxMenu) return;
    const close = () => setCtxMenu(null);
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") close();
    };
    window.addEventListener("pointerdown", close);
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("pointerdown", close);
      window.removeEventListener("keydown", onKey);
    };
  }, [ctxMenu]);

  const setAt = (kind: Kind, price: number) => {
    brackets.onChange({
      stop_loss: kind === "sl" ? price : brackets.stopLoss,
      take_profit: kind === "tp" ? price : brackets.takeProfit,
    });
    setCtxMenu(null);
  };

  // Drag — window-level move/up so the cursor can leave the line.
  useEffect(() => {
    if (!drag) return;
    const onMove = (e: PointerEvent) => {
      const series = seriesRef.current;
      const root = rootRef.current;
      if (!series || !root) return;
      const rect = root.getBoundingClientRect();
      const price = series.coordinateToPrice(e.clientY - rect.top);
      if (price == null) return;
      setDrag({ kind: drag.kind, price: Math.max(0.01, Number(price)) });
    };
    const onUp = () => {
      brackets.onChange({
        stop_loss: drag.kind === "sl" ? round2(drag.price) : brackets.stopLoss,
        take_profit: drag.kind === "tp" ? round2(drag.price) : brackets.takeProfit,
      });
      setDrag(null);
    };
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp, { once: true });
    return () => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
    };
    // seriesRef/rootRef are stable ref objects (read .current live).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [drag, brackets]);

  const startDrag = (kind: Kind) => (e: React.PointerEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setDrag({ kind, price: displayed(kind) ?? brackets.spot });
  };

  const clear = (kind: Kind) => () =>
    brackets.onChange({
      stop_loss: kind === "sl" ? null : brackets.stopLoss,
      take_profit: kind === "tp" ? null : brackets.takeProfit,
    });

  const add = (kind: Kind) => () => {
    const s = brackets.spot || brackets.entryUnderlying || 0;
    const level = round2(kind === "sl" ? s * 0.99 : s * 1.01);
    brackets.onChange({
      stop_loss: kind === "sl" ? level : brackets.stopLoss,
      take_profit: kind === "tp" ? level : brackets.takeProfit,
    });
  };

  const pnlAt = (x: number) => interpolate(brackets.prices, brackets.payoffToday, x);

  // While a drawing tool is armed (or a drawing is selected), the grab strips
  // yield so a draw gesture starting on the SL/TP band reaches the chart's
  // drawing engine instead of starting a bracket drag.
  const drawingActive = useDrawingTool(isDrawingInteracting);

  return (
    <div ref={rootRef} className="absolute inset-0" style={{ pointerEvents: "none", zIndex: 8 }}>
      {displayed("sl") != null && (
        <BracketRow
          rowRef={slRowRef}
          label="SL"
          color={colors.bearish}
          price={displayed("sl") as number}
          pnl={pnlAt(displayed("sl") as number)}
          onPointerDown={startDrag("sl")}
          onClear={clear("sl")}
          grabDisabled={drawingActive}
        />
      )}
      {displayed("tp") != null && (
        <BracketRow
          rowRef={tpRowRef}
          label="TP"
          color={colors.bullish}
          price={displayed("tp") as number}
          pnl={pnlAt(displayed("tp") as number)}
          onPointerDown={startDrag("tp")}
          onClear={clear("tp")}
          grabDisabled={drawingActive}
        />
      )}
      <div className="absolute right-2 top-2 flex gap-1" style={{ pointerEvents: "auto", zIndex: 20 }}>
        {brackets.stopLoss == null && (
          <AddButton color={colors.bearish} label="+ SL" onClick={add("sl")} />
        )}
        {brackets.takeProfit == null && (
          <AddButton color={colors.bullish} label="+ TP" onClick={add("tp")} />
        )}
      </div>
      {ctxMenu && (
        <div
          className="absolute flex flex-col"
          style={{
            left: ctxMenu.x,
            top: Math.max(4, ctxMenu.y - 4),
            pointerEvents: "auto",
            zIndex: 30,
            background: colors.bgTier0,
            border: `1px solid ${colors.borderHairline}`,
            minWidth: 122,
          }}
          onPointerDown={(e) => e.stopPropagation()}
          role="menu"
          aria-label={`Set bracket at ${ctxMenu.price.toFixed(2)}`}
        >
          <button
            type="button"
            role="menuitem"
            onClick={() => setAt("sl", ctxMenu.price)}
            className="px-2 py-1 text-left uppercase tracking-label-up hover:bg-tier-2"
            style={{ fontSize: 11, color: colors.bearish }}
            title="Auto-close when the underlying crosses this level"
          >
            SL @ {ctxMenu.price.toFixed(2)}
          </button>
          <button
            type="button"
            role="menuitem"
            onClick={() => setAt("tp", ctxMenu.price)}
            className="px-2 py-1 text-left uppercase tracking-label-up hover:bg-tier-2"
            style={{ fontSize: 11, color: colors.bullish }}
            title="Auto-close when the underlying crosses this level"
          >
            TP @ {ctxMenu.price.toFixed(2)}
          </button>
        </div>
      )}
    </div>
  );
}

function BracketRow({
  rowRef,
  label,
  color,
  price,
  pnl,
  onPointerDown,
  onClear,
  grabDisabled,
}: {
  rowRef: React.Ref<HTMLDivElement>;
  label: string;
  color: string;
  price: number;
  pnl: number | null;
  onPointerDown: (e: React.PointerEvent) => void;
  onClear: () => void;
  grabDisabled: boolean;
}) {
  const pnlText = pnl == null ? "" : `${pnl >= 0 ? "+" : "−"}$${Math.abs(pnl).toFixed(0)}`;
  return (
    <div
      ref={rowRef}
      className="absolute left-0 right-0"
      style={{ transform: "translateY(-50%)", pointerEvents: "none" }}
    >
      {/* Grab strip — the only pointer-interactive band, so chart pan works
          everywhere else along the chart. */}
      <div
        onPointerDown={onPointerDown}
        className="absolute left-0 right-0"
        style={{
          top: -6,
          height: 12,
          cursor: "ns-resize",
          pointerEvents: grabDisabled ? "none" : "auto",
        }}
        role="slider"
        aria-label={`${label} bracket at ${price.toFixed(2)}`}
        aria-valuenow={price}
      />
      <div
        className="absolute left-0 right-0"
        style={{ top: 0, height: 0, borderTop: `1px dashed ${color}` }}
      />
      <div
        className="absolute flex items-center gap-1 tabular-nums"
        style={{ right: 0, top: -8, pointerEvents: "auto" }}
      >
        <span
          className="uppercase tracking-label-up px-1"
          style={{ fontSize: 11, color, background: colors.bgTier0, border: `1px solid ${color}` }}
          title="Drag to move · auto-closes when the underlying crosses"
        >
          {label} {price.toFixed(2)}
          {pnlText && <span className="ml-1 text-fg-secondary">{pnlText}</span>}
        </span>
        <button
          type="button"
          onClick={onClear}
          aria-label={`Clear ${label}`}
          className="text-fg-tertiary hover:text-fg-primary leading-none"
          style={{ fontSize: 12, background: colors.bgTier0, paddingInline: 2 }}
        >
          ×
        </button>
      </div>
    </div>
  );
}

function AddButton({ color, label, onClick }: { color: string; label: string; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="uppercase tracking-label-up px-1.5 py-0.5 hover:bg-tier-2"
      style={{ fontSize: 11, color, border: `1px solid ${color}`, background: `${colors.bgTier0}cc` }}
    >
      {label}
    </button>
  );
}

function round2(v: number): number {
  return Math.round(v * 100) / 100;
}

function interpolate(xs: number[], ys: number[], x: number): number | null {
  if (!xs.length || xs.length !== ys.length) return null;
  if (x <= xs[0]) return ys[0];
  if (x >= xs[xs.length - 1]) return ys[ys.length - 1];
  for (let i = 1; i < xs.length; i++) {
    if (x <= xs[i]) {
      const t = (x - xs[i - 1]) / (xs[i] - xs[i - 1] || 1);
      return ys[i - 1] + t * (ys[i] - ys[i - 1]);
    }
  }
  return ys[ys.length - 1];
}
