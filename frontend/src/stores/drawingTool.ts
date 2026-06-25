import { create } from "zustand";

/**
 * Session-only coordination slice for the drawing-tools layer.
 *
 * Deliberately NOT persisted — it holds transient UI state (which tool is
 * armed, which drawing is selected) shared between two sibling overlays:
 *
 *  - ChartDrawingLayer owns the toolbar and writes this state.
 *  - PositionBracketsLayer reads it so its draggable SL/TP grab strips can
 *    yield (pointer-events: none) while a drawing tool is armed or a drawing
 *    is selected — otherwise a draw gesture that starts on the SL/TP band
 *    would be swallowed by the bracket strip instead of reaching the chart.
 *
 * The drawing engine itself (DrawingManager) is the source of truth for the
 * armed tool / selection; this slice mirrors it via the manager's
 * `tool:changed` / `drawing:selected` events so the UI and the bracket gate
 * stay in sync regardless of how the engine arms/disarms internally.
 */
interface DrawingToolState {
  /** Active tool type string (e.g. "trend-line"), or null for cursor/select. */
  activeTool: string | null;
  /** Currently-selected drawing id, or null. */
  selectedId: string | null;
  setActiveTool: (tool: string | null) => void;
  setSelectedId: (id: string | null) => void;
}

export const useDrawingTool = create<DrawingToolState>((set) => ({
  activeTool: null,
  selectedId: null,
  setActiveTool: (tool) => set({ activeTool: tool }),
  setSelectedId: (id) => set({ selectedId: id }),
}));

/** True when a drawing interaction is in progress (tool armed or selection). */
export const isDrawingInteracting = (s: DrawingToolState): boolean =>
  s.activeTool !== null || s.selectedId !== null;
