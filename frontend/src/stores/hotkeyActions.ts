import { create } from "zustand";

/**
 * Hotkey action bus (WS6 power-UX).
 *
 * A keystroke can't safely reach into a deeply-nested component and fire a
 * mutation, so the global hotkey hook publishes an INTENT here and the owning
 * component (TradeTicket, the active-position panel) reacts. Intents are
 * one-shot: a monotonically-increasing `nonce` lets a listener tell a fresh
 * press apart from a re-render, and `consume()` clears it once handled.
 *
 *   - armBuy / armSell : "pre-arm" the BUY/SELL direction on the ticket. We
 *     deliberately do NOT auto-fire an order from a keystroke — arming focuses
 *     the matching action button so the user confirms with Enter. Safety first.
 *   - closeActive      : request a close of the active position (the panel that
 *     owns the close mutation performs it).
 */
export type HotkeyIntent = "armBuy" | "armSell" | "closeActive" | null;

interface HotkeyActionState {
  intent: HotkeyIntent;
  /** Bumped on every request so listeners can dedupe. */
  nonce: number;
  request: (intent: Exclude<HotkeyIntent, null>) => void;
  /** Clear the pending intent once a listener has handled it. */
  consume: () => void;
}

export const useHotkeyActions = create<HotkeyActionState>((set) => ({
  intent: null,
  nonce: 0,
  request: (intent) => set((s) => ({ intent, nonce: s.nonce + 1 })),
  consume: () => set({ intent: null }),
}));
