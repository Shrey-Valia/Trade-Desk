import { useEffect } from "react";
import { create } from "zustand";

import { toast } from "@/stores/toast";

/**
 * Hotkey action bus (WS6 power-UX).
 *
 * A keystroke can't safely reach into a deeply-nested component and fire a
 * mutation, so the global hotkey hook publishes an INTENT here and the owning
 * component (TradeTicket, the active-position panel, the bulk-action strip)
 * reacts. Intents are one-shot: a monotonically-increasing `nonce` lets a
 * listener tell a fresh press apart from a re-render, and `consume()` clears
 * it once handled.
 *
 *   - armBuy / armSell    : "pre-arm" the BUY/SELL direction on the ticket. We
 *     deliberately do NOT auto-fire an order from a keystroke — arming focuses
 *     the matching action button so the user confirms with Enter. Safety first.
 *   - closeActive         : request a close of the active position (the panel
 *     that owns the close mutation performs it; C-C arm/confirm).
 *   - flattenAll          : close EVERY open position (F-F arm/confirm).
 *   - cancelAllOrders     : cancel every working order (X-X arm/confirm).
 *
 * Hygiene: intents are TIMESTAMPED and consumers must ignore anything older
 * than INTENT_TTL_MS (a stale intent must never replay a trade action on a
 * later mount). Publishing is also gated on a CONSUMER REGISTRY — when no
 * eligible consumer is mounted (wrong page, nothing selected) the request
 * toasts the reason instead of parking an intent forever.
 */
export type HotkeyIntent =
  | "armBuy"
  | "armSell"
  | "closeActive"
  | "flattenAll"
  | "cancelAllOrders"
  | null;

type ActiveIntent = Exclude<HotkeyIntent, null>;

/** Consumers ignore intents older than this. */
export const INTENT_TTL_MS = 2_000;

/** Why a request went nowhere — surfaced as a toast so the keystroke never
 *  silently vanishes. */
const NO_CONSUMER_REASON: Record<ActiveIntent, string> = {
  armBuy: "No contract selected — open the terminal and pick a strike",
  armSell: "No contract selected — open the terminal and pick a strike",
  closeActive: "No open position selected — open the terminal",
  flattenAll: "Nothing to flatten here — open the terminal",
  cancelAllOrders: "No orders to cancel here — open the terminal",
};

interface HotkeyActionState {
  intent: HotkeyIntent;
  /** Bumped on every request so listeners can dedupe. */
  nonce: number;
  /** Publish time (ms epoch) — consumers reject intents past INTENT_TTL_MS. */
  ts: number;
  /** Mounted-consumer counts per intent (registry for the no-consumer toast). */
  consumers: Partial<Record<ActiveIntent, number>>;
  /** Register a mounted consumer for `intents`; returns the unregister fn. */
  register: (intents: ActiveIntent[]) => () => void;
  /** Publish an intent — or toast the reason when nothing can handle it. */
  request: (intent: ActiveIntent) => void;
  /** Clear the pending intent once a listener has handled it. */
  consume: () => void;
  /** Drop any pending intent (route change — never replay across pages). */
  clear: () => void;
}

export const useHotkeyActions = create<HotkeyActionState>((set, get) => ({
  intent: null,
  nonce: 0,
  ts: 0,
  consumers: {},
  register: (intents) => {
    const bump = (delta: number) =>
      set((s) => {
        const next = { ...s.consumers };
        for (const i of intents) next[i] = Math.max(0, (next[i] ?? 0) + delta);
        return { consumers: next };
      });
    bump(1);
    return () => bump(-1);
  },
  request: (intent) => {
    if ((get().consumers[intent] ?? 0) <= 0) {
      toast.info(NO_CONSUMER_REASON[intent]);
      return;
    }
    set((s) => ({ intent, nonce: s.nonce + 1, ts: Date.now() }));
  },
  consume: () => set({ intent: null }),
  clear: () => set({ intent: null }),
}));

/** True while `ts` is within the intent TTL. */
export function isIntentFresh(ts: number, now: number = Date.now()): boolean {
  return now - ts <= INTENT_TTL_MS;
}

/** Declare this component a mounted consumer of `intents` while `enabled`.
 *  Registration is what routes a request here instead of the reason-toast. */
export function useHotkeyConsumer(intents: ActiveIntent[], enabled = true) {
  const register = useHotkeyActions((s) => s.register);
  const key = intents.join(",");
  useEffect(() => {
    if (!enabled) return;
    return register(key.split(",") as ActiveIntent[]);
  }, [enabled, register, key]);
}
