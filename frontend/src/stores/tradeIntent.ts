import { create } from "zustand";

/**
 * Direction (long/short) for the next paper-trade open.
 *
 * Shared between the ChainPanel's buy/sell toggle and the toolbar
 * straddle button so a single mode applies wherever you click. Not
 * persisted: each session opens in "buy" mode (the safer default).
 */
export type TradeAction = "buy" | "sell";

interface TradeIntentState {
  action: TradeAction;
  setAction: (a: TradeAction) => void;
  toggle: () => void;
}

export const useTradeIntent = create<TradeIntentState>((set, get) => ({
  action: "buy",
  setAction: (action) => set({ action }),
  toggle: () => set({ action: get().action === "buy" ? "sell" : "buy" }),
}));
