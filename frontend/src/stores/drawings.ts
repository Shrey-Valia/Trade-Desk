import { create } from "zustand";
import { persist } from "zustand/middleware";

/**
 * User-drawn chart annotations, keyed by symbol.
 *
 * Phase 1 of the drawing-tools layer: horizontal lines only. Each
 * drawing is stored in PRICE coordinates (never pixels) so it can be
 * re-projected onto the lightweight-charts canvas on every redraw —
 * pan, zoom, and timeframe change — and stay pinned to its price level.
 *
 * Persisted to localStorage so a trader's levels survive a reload. The
 * store is deliberately independent of the chart instance: it holds
 * pure data, and the render layer (ChartDrawingLayer) projects it.
 *
 * Phase 2+ extends `Drawing` with new `kind`s (trendline, rect, text)
 * that also carry time coordinates — the same store, same persistence.
 */
export type DrawingKind = "hline";

export interface Drawing {
  id: string;
  kind: DrawingKind;
  /** Price level for a horizontal line. */
  price: number;
}

interface DrawingsState {
  /** Symbol → its drawings. SPY's levels differ from QQQ's. */
  drawings: Record<string, Drawing[]>;
  addDrawing: (symbol: string, drawing: Drawing) => void;
  removeDrawing: (symbol: string, id: string) => void;
  clearSymbol: (symbol: string) => void;
}

export const useDrawings = create<DrawingsState>()(
  persist(
    (set) => ({
      drawings: {},
      addDrawing: (symbol, drawing) =>
        set((s) => ({
          drawings: {
            ...s.drawings,
            [symbol]: [...(s.drawings[symbol] ?? []), drawing],
          },
        })),
      removeDrawing: (symbol, id) =>
        set((s) => ({
          drawings: {
            ...s.drawings,
            [symbol]: (s.drawings[symbol] ?? []).filter((d) => d.id !== id),
          },
        })),
      clearSymbol: (symbol) =>
        set((s) => {
          const next = { ...s.drawings };
          delete next[symbol];
          return { drawings: next };
        }),
    }),
    { name: "td:drawings" },
  ),
);
