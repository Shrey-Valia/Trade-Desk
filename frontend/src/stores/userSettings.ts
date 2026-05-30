import { create } from "zustand";
import { persist } from "zustand/middleware";

import type { ChartTimeframe } from "@/types/chart";

/**
 * User-tunable defaults exposed in the Settings page.
 *
 * Kept deliberately small: only preferences that genuinely change how
 * the app opens or behaves.
 *
 *   defaultTicker     — the ticker the chart cold-opens to.
 *   defaultContracts  — fill quantity for new paper opens.
 *   defaultTimeframe  — chart timeframe at first render.
 *
 * Chart appearance (visual rework):
 *   bullishColor      — candle up color
 *   bearishColor      — candle down color
 *   bgGradient        — soft radial gradient on the body background
 *   gridOpacity       — chart grid line opacity (0-100)
 *
 * These persist and the chart re-applies them in real time.
 */
interface UserSettingsState {
  defaultTicker: string;
  defaultContracts: number;
  defaultTimeframe: ChartTimeframe;
  bullishColor: string;
  bearishColor: string;
  bgGradient: boolean;
  gridOpacity: number;
  setDefaultTicker: (s: string) => void;
  setDefaultContracts: (n: number) => void;
  setDefaultTimeframe: (tf: ChartTimeframe) => void;
  setBullishColor: (hex: string) => void;
  setBearishColor: (hex: string) => void;
  setBgGradient: (on: boolean) => void;
  setGridOpacity: (pct: number) => void;
}

export const useUserSettings = create<UserSettingsState>()(
  persist(
    (set) => ({
      defaultTicker: "SPY",
      defaultContracts: 1,
      defaultTimeframe: "5D",
      bullishColor: "#4DD17C",
      bearishColor: "#E85C5C",
      bgGradient: true,
      gridOpacity: 30,
      setDefaultTicker: (s) => set({ defaultTicker: s.toUpperCase().trim() }),
      setDefaultContracts: (n) =>
        set({ defaultContracts: Math.max(1, Math.min(100, Math.floor(n))) }),
      setDefaultTimeframe: (tf) => set({ defaultTimeframe: tf }),
      setBullishColor: (hex) => set({ bullishColor: hex }),
      setBearishColor: (hex) => set({ bearishColor: hex }),
      setBgGradient: (on) => set({ bgGradient: on }),
      setGridOpacity: (pct) =>
        set({ gridOpacity: Math.max(0, Math.min(100, Math.round(pct))) }),
    }),
    { name: "td:user-settings" },
  ),
);
