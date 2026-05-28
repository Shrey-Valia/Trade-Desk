import { create } from "zustand";

/**
 * Trade ticket selection — drives the BUY/SELL surface below the
 * option chain.
 *
 * Clicking a chain cell SELECTS the strike + side here; the ticket
 * shows the choice and lets the user fire BUY or SELL with a separate
 * quantity. There is no "buy/sell mode toggle" anywhere — direction
 * is which of the two buttons you click.
 *
 * `kind` is "leg" for a single call or put, "straddle" for both.
 * `strike` and `expiry` come from the chain row.
 *
 * NOT persisted: a fresh session starts with no selection. The user's
 * default contracts comes from useUserSettings.
 */
export type TicketKind = "leg" | "straddle";
export type TicketSide = "call" | "put";

export interface TicketSelection {
  kind: TicketKind;
  symbol: string;
  strike: number;
  /** Required only when kind = "leg". */
  side?: TicketSide;
  /** Indicative price (debit per contract for buy, credit for sell). */
  price: number;
  /** Same-day expiry (YYYY-MM-DD). */
  expiry: string;
}

interface TradeTicketState {
  selection: TicketSelection | null;
  contracts: number;
  setSelection: (sel: TicketSelection | null) => void;
  setContracts: (n: number) => void;
  clear: () => void;
}

export const useTradeTicket = create<TradeTicketState>((set) => ({
  selection: null,
  contracts: 1,
  setSelection: (selection) => set({ selection }),
  setContracts: (n) =>
    set({ contracts: Math.max(1, Math.min(100, Math.floor(n))) }),
  clear: () => set({ selection: null }),
}));
