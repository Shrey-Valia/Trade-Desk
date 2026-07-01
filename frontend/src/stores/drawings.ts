import { create } from "zustand";
import { persist } from "zustand/middleware";
import type { DrawingStyle, SerializedDrawing } from "lightweight-charts-drawing";
import type { Time } from "lightweight-charts";

/**
 * User-drawn chart annotations, keyed by symbol.
 *
 * Phase 2 (drawing-tools v2): the chart now uses the `lightweight-charts-drawing`
 * engine, which renders every tool (trendlines, fibs, shapes, text, …) via
 * lightweight-charts primitives and serializes them to a clean, JSON-safe shape
 * (`SerializedDrawing`: id + type + time/price anchors + style + options). We
 * persist that engine-native blob verbatim per symbol — hand-mapping 68 tool
 * types to our own union would be error-prone, and the engine guarantees an
 * export/import round-trip.
 *
 * Anchors are stored in time+price coordinates (never pixels), so a drawing
 * re-projects correctly across pan, zoom, timeframe change, and reload.
 *
 * Persisted to localStorage so a trader's markup survives a reload. The store
 * holds pure data; the render layer (ChartDrawingLayer) drives a DrawingManager
 * that imports from / exports to it.
 *
 * The store is deliberately independent of the chart instance and of the
 * engine's runtime classes — it only depends on the serialized type — so a
 * future migration off the package would only need to re-map persisted blobs.
 */
export type StoredDrawing = SerializedDrawing;

interface DrawingsState {
  /** Symbol → its serialized drawings. SPY's markup differs from QQQ's. */
  drawings: Record<string, StoredDrawing[]>;
  /** Replace the entire per-symbol set (called on every manager change event). */
  setSymbolDrawings: (symbol: string, items: StoredDrawing[]) => void;
  clearSymbol: (symbol: string) => void;
}

export const useDrawings = create<DrawingsState>()(
  persist(
    (set) => ({
      drawings: {},
      setSymbolDrawings: (symbol, items) =>
        set((s) => ({ drawings: { ...s.drawings, [symbol]: items } })),
      clearSymbol: (symbol) =>
        set((s) => {
          const next = { ...s.drawings };
          delete next[symbol];
          return { drawings: next };
        }),
    }),
    {
      name: "td:drawings",
      version: 1,
      // v0 → v1: the Phase-1 store held horizontal lines only, as
      // `{ id, kind: "hline", price }`. Convert each into the engine's
      // serialized "horizontal-line" shape. A horizontal line renders across
      // the full pane width regardless of its time anchor, so the anchor time
      // is a neutral placeholder — only the price matters.
      migrate: (persisted, fromVersion) => {
        const state = persisted as { drawings?: Record<string, unknown[]> } | undefined;
        if (!state) return { drawings: {} };
        if (fromVersion < 1) {
          const old = state.drawings ?? {};
          const migrated: Record<string, StoredDrawing[]> = {};
          for (const [symbol, list] of Object.entries(old)) {
            migrated[symbol] = (list ?? [])
              .filter(
                (d): d is { id: string; kind: "hline"; price: number } =>
                  !!d &&
                  typeof d === "object" &&
                  (d as { kind?: unknown }).kind === "hline" &&
                  typeof (d as { price?: unknown }).price === "number",
              )
              .map((d) => migrateHline(d.id, d.price));
          }
          return { drawings: migrated };
        }
        return state as DrawingsState;
      },
    },
  ),
);

const HLINE_ANCHOR_TIME = 0 as unknown as Time;

// Minimal complete style for migrated horizontal lines (cyan, matching the
// Phase-1 default). The engine merges this over its own defaults on import, so
// only the required fields are needed — and keeping this a plain literal (with
// the package imported type-only above) leaves the store free of the drawing
// package at runtime, so the package code-splits cleanly into the chart chunk.
const MIGRATED_HLINE_STYLE: DrawingStyle = {
  lineColor: "#808690",
  lineWidth: 1,
};

function migrateHline(id: string, price: number): SerializedDrawing {
  return {
    id,
    type: "horizontal-line",
    anchors: [{ time: HLINE_ANCHOR_TIME, price }],
    style: { ...MIGRATED_HLINE_STYLE },
    options: {},
  };
}
