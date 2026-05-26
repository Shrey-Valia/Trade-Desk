import { create } from "zustand";

/**
 * Trade Desk — active position.
 *
 * Clicking a trade row in TradeList sets this; clicking the same row
 * again clears it. The active position drives:
 *   - the entry marker + breakeven price-lines on AnnotatedChart
 *   - the payoff curve + theta scrubber in JournalPanel
 *
 * Two scrubber states live here so the chart and the payoff panel read
 * from the same source:
 *   - `scrubberDte`     — integer days remaining (multi-day positions)
 *   - `elapsedHours`    — fractional hours since entry (0DTE positions)
 *
 * Only one is meaningful at a time; PositionsPage picks the right one
 * based on the active trade's nearest-leg expiry.
 *
 * NOT persisted: selection is session-scoped. A reload should return
 * the user to the chart, not strand them on a previously-clicked row.
 */
interface ActivePositionState {
  tradeId: number | null;
  /** Days remaining (multi-day). null = use today (no scrub). */
  scrubberDte: number | null;
  /** Hours elapsed since entry (0DTE only). null = use live wall clock. */
  elapsedHours: number | null;
  setTradeId: (id: number | null) => void;
  setScrubberDte: (dte: number | null) => void;
  setElapsedHours: (hours: number | null) => void;
  clear: () => void;
  toggle: (id: number) => void;
}

export const useActivePosition = create<ActivePositionState>((set, get) => ({
  tradeId: null,
  scrubberDte: null,
  elapsedHours: null,
  setTradeId: (id) => set({ tradeId: id, scrubberDte: null, elapsedHours: null }),
  setScrubberDte: (dte) => set({ scrubberDte: dte }),
  setElapsedHours: (hours) => set({ elapsedHours: hours }),
  clear: () => set({ tradeId: null, scrubberDte: null, elapsedHours: null }),
  toggle: (id) => {
    if (get().tradeId === id) {
      set({ tradeId: null, scrubberDte: null, elapsedHours: null });
    } else {
      set({ tradeId: id, scrubberDte: null, elapsedHours: null });
    }
  },
}));
