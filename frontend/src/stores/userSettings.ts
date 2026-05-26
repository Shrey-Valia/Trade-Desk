import { create } from "zustand";
import { persist } from "zustand/middleware";

import type { ChartTimeframe } from "@/types/chart";

/**
 * User-tunable defaults exposed in the Settings page.
 *
 * Kept deliberately small: only preferences that genuinely change how
 * the app opens or behaves. The on/off toggle for market-structure
 * annotations lives in `chartPrefs.showMarketAnnotations` and is
 * surfaced in the same Settings page — same source of truth, no copy.
 *
 *   defaultTicker     — the ticker the chart cold-opens to. Restricted
 *                       to the 0DTE-eligible allowlist when shown in
 *                       the Settings UI; we don't enforce here so a
 *                       future allowlist edit can't strand the value.
 *   defaultContracts  — fill quantity for new paper opens (chain click
 *                       or "+ BUY/SELL STRADDLE"). 1 is a sane starting
 *                       size for a 0DTE play.
 *   defaultTimeframe  — chart timeframe at first render. "5D" matches
 *                       the previous hardcoded default; tradable users
 *                       on 0DTE often prefer "1D".
 */
interface UserSettingsState {
  defaultTicker: string;
  defaultContracts: number;
  defaultTimeframe: ChartTimeframe;
  setDefaultTicker: (s: string) => void;
  setDefaultContracts: (n: number) => void;
  setDefaultTimeframe: (tf: ChartTimeframe) => void;
}

export const useUserSettings = create<UserSettingsState>()(
  persist(
    (set) => ({
      defaultTicker: "SPY",
      defaultContracts: 1,
      defaultTimeframe: "5D",
      setDefaultTicker: (s) => set({ defaultTicker: s.toUpperCase().trim() }),
      setDefaultContracts: (n) =>
        set({ defaultContracts: Math.max(1, Math.min(100, Math.floor(n))) }),
      setDefaultTimeframe: (tf) => set({ defaultTimeframe: tf }),
    }),
    { name: "td:user-settings" },
  ),
);
