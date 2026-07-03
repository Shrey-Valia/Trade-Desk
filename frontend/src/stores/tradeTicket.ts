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
/** Entry order type — market fills now; limit/stop/stop_limit place a
 *  working order. stop_limit arms at stopPrice, then rests as a limit. */
export type TicketOrderType = "market" | "limit" | "stop" | "stop_limit";

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
  /** Entry order type. limit/stop/stop_limit reveal price inputs. */
  orderType: TicketOrderType;
  /** Option-premium trigger for a limit/stop order; the resting limit for
   *  a stop_limit (per-share). */
  limitPrice: number | null;
  /** Option-premium ARM level for a stop_limit order (per-share). */
  stopPrice: number | null;
  /** Optional trailing-stop EXIT distance ($/share off the favorable mark);
   *  null = no trailing stop attached at open. */
  trailAmount: number | null;
  /** Time-in-force for a working order: 'gtc' rests, 'day' expires next session. */
  timeInForce: "day" | "gtc";
  setSelection: (sel: TicketSelection | null) => void;
  /** Live-price refresh from the chain refetch — updates the SELECTED
   *  contract's indicative price in place. Keeps selection identity and does
   *  NOT re-seed limit/stop (the user may have edited those). */
  refreshSelectionPrice: (price: number) => void;
  setContracts: (n: number) => void;
  setOrderType: (t: TicketOrderType) => void;
  setLimitPrice: (p: number | null) => void;
  setStopPrice: (p: number | null) => void;
  setTrailAmount: (a: number | null) => void;
  setTimeInForce: (t: "day" | "gtc") => void;
  clear: () => void;
}

export const useTradeTicket = create<TradeTicketState>((set) => ({
  selection: null,
  contracts: 1,
  orderType: "market",
  limitPrice: null,
  stopPrice: null,
  trailAmount: null,
  // DAY is the honest default on a strictly-0DTE product — a resting order
  // that outlives the session is the exception, so GTC is opt-in.
  timeInForce: "day",
  // Selecting a contract seeds limitPrice + stopPrice to its indicative price
  // so a limit/stop/stop_limit order starts at a sensible default to nudge.
  // The trailing stop stays off (null) unless the user opts in.
  setSelection: (selection) =>
    set({
      selection,
      limitPrice: selection ? selection.price : null,
      stopPrice: selection ? selection.price : null,
      trailAmount: null,
    }),
  refreshSelectionPrice: (price) =>
    set((s) =>
      s.selection && s.selection.price !== price
        ? { selection: { ...s.selection, price } }
        : {},
    ),
  setContracts: (n) =>
    set({ contracts: Math.max(1, Math.min(100, Math.floor(n))) }),
  setOrderType: (orderType) => set({ orderType }),
  setLimitPrice: (limitPrice) => set({ limitPrice }),
  setStopPrice: (stopPrice) => set({ stopPrice }),
  setTrailAmount: (trailAmount) => set({ trailAmount }),
  setTimeInForce: (timeInForce) => set({ timeInForce }),
  clear: () =>
    set({
      selection: null,
      orderType: "market",
      limitPrice: null,
      stopPrice: null,
      trailAmount: null,
      timeInForce: "day",
    }),
}));
