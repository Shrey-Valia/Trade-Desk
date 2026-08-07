import { create } from "zustand";
import { persist } from "zustand/middleware";

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
 * Selection is NOT persisted: a fresh session starts with no selection.
 * The user's default contracts comes from useUserSettings. ONLY the
 * premium-exit config persists (partialize below) — the last-used
 * TP/SL preset survives reloads, matching "set it once" ergonomics.
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

/**
 * Premium-exit presets ("close at 2× / 50% max profit") — TP/SL as
 * multiples of the ENTRY premium, resolved per direction at fire time:
 *   - long (net-debit):  longTpMult 2 = sell when the premium doubles;
 *     longSlMult 0.5 = cut when it halves.
 *   - short (net-credit): shortTpMult 0.5 = buy back at 50% of the credit
 *     (keep 50% of max profit, Tastytrade-style); shortSlMult 2 = stop
 *     out when the mark reaches 2× the credit received.
 * null = that exit not attached. `enabled` is the master switch — OFF by
 * default; the mults are remembered (persisted) as the last-used config.
 */
export interface PremiumExitConfig {
  enabled: boolean;
  longTpMult: number | null;
  longSlMult: number | null;
  shortTpMult: number | null;
  shortSlMult: number | null;
}

export const PREMIUM_EXIT_DEFAULTS: PremiumExitConfig = {
  enabled: false,
  longTpMult: 2,
  longSlMult: 0.5,
  shortTpMult: 0.5,
  shortSlMult: 2,
};

/**
 * Resolve the premium-exit mults for the direction actually fired
 * (BUY = net-debit/long; SELL = net-credit/short — the multi-leg builder
 * derives it from the priced legs instead). Disabled config → both null,
 * so the open payload attaches nothing.
 */
export function premiumExitForDirection(
  config: PremiumExitConfig | null | undefined,
  isLong: boolean,
): { tp: number | null; sl: number | null } {
  if (!config?.enabled) return { tp: null, sl: null };
  return isLong
    ? { tp: config.longTpMult, sl: config.longSlMult }
    : { tp: config.shortTpMult, sl: config.shortSlMult };
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
   *  null = no trailing stop attached at open. Mutually exclusive with
   *  trailPct (the backend uses trail_amount when both are set). */
  trailAmount: number | null;
  /** Optional trailing-stop EXIT distance as a FRACTION of the entry premium
   *  (0.10 = 10%); null = not a percentage trail. */
  trailPct: number | null;
  /** Optional underlying-price SL/TP brackets pre-attached at entry; null =
   *  not set. Absolute underlying price levels (the same the draggable chart
   *  brackets set post-open). */
  stopLoss: number | null;
  takeProfit: number | null;
  /** Time-in-force for a working order: 'gtc' rests, 'day' expires next session. */
  timeInForce: "day" | "gtc";
  /** Premium-exit presets — persisted last-used config, off by default. */
  premiumExit: PremiumExitConfig;
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
  setTrailPct: (p: number | null) => void;
  setStopLoss: (p: number | null) => void;
  setTakeProfit: (p: number | null) => void;
  setTimeInForce: (t: "day" | "gtc") => void;
  /** Patch the premium-exit config (merges; e.g. `{ enabled: true }`). */
  setPremiumExit: (patch: Partial<PremiumExitConfig>) => void;
  clear: () => void;
}

export const useTradeTicket = create<TradeTicketState>()(
  persist(
    (set) => ({
      selection: null,
      contracts: 1,
      orderType: "market",
      limitPrice: null,
      stopPrice: null,
      trailAmount: null,
      trailPct: null,
      stopLoss: null,
      takeProfit: null,
      // DAY is the honest default on a strictly-0DTE product — a resting order
      // that outlives the session is the exception, so GTC is opt-in.
      timeInForce: "day",
      premiumExit: PREMIUM_EXIT_DEFAULTS,
      // Selecting a contract seeds limitPrice + stopPrice to its indicative price
      // so a limit/stop/stop_limit order starts at a sensible default to nudge.
      // The trailing stop stays off (null) unless the user opts in.
      setSelection: (selection) =>
        set({
          selection,
          limitPrice: selection ? selection.price : null,
          stopPrice: selection ? selection.price : null,
          trailAmount: null,
          trailPct: null,
          stopLoss: null,
          takeProfit: null,
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
      setTrailPct: (trailPct) => set({ trailPct }),
      setStopLoss: (stopLoss) => set({ stopLoss }),
      setTakeProfit: (takeProfit) => set({ takeProfit }),
      setTimeInForce: (timeInForce) => set({ timeInForce }),
      setPremiumExit: (patch) =>
        set((s) => ({ premiumExit: { ...s.premiumExit, ...patch } })),
      // clear() intentionally leaves `premiumExit` (and contracts) alone —
      // the last-used exit config carries to the next ticket.
      clear: () =>
        set({
          selection: null,
          orderType: "market",
          limitPrice: null,
          stopPrice: null,
          trailAmount: null,
          trailPct: null,
          stopLoss: null,
          takeProfit: null,
          timeInForce: "day",
        }),
    }),
    {
      name: "trade-ticket",
      // ONLY the premium-exit config persists — selection/prices are
      // deliberately session-scoped (see the doc comment above).
      partialize: (s) => ({ premiumExit: s.premiumExit }),
    },
  ),
);
