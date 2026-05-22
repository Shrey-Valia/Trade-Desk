import { create } from "zustand";

/**
 * Trade Desk Phase 2 — active position.
 *
 * Clicking a trade row in TradeList sets this; clicking the same row
 * again clears it. The active position drives:
 *   - the entry marker + breakeven price-lines on AnnotatedChart
 *   - the payoff curve + theta scrubber in JournalPanel
 *
 * The scrubber DTE lives here too so the chart and the payoff panel
 * read from the same source — when the user drags the slider in the
 * panel, the chart's breakeven line moves in lockstep.
 *
 * NOT persisted: selection is session-scoped. A reload should return
 * the user to the chart, not strand them on a previously-clicked row.
 */
interface ActivePositionState {
  tradeId: number | null;
  /** null = use the analytics endpoint's natural "current DTE" (today). */
  scrubberDte: number | null;
  setTradeId: (id: number | null) => void;
  setScrubberDte: (dte: number | null) => void;
  clear: () => void;
  toggle: (id: number) => void;
}

export const useActivePosition = create<ActivePositionState>((set, get) => ({
  tradeId: null,
  scrubberDte: null,
  setTradeId: (id) => set({ tradeId: id, scrubberDte: null }),
  setScrubberDte: (dte) => set({ scrubberDte: dte }),
  clear: () => set({ tradeId: null, scrubberDte: null }),
  toggle: (id) => {
    if (get().tradeId === id) {
      set({ tradeId: null, scrubberDte: null });
    } else {
      set({ tradeId: id, scrubberDte: null });
    }
  },
}));
