import { create } from "zustand";
import { persist } from "zustand/middleware";

import {
  DEFAULT_CHART_TIMEFRAME,
  isChartTimeframe,
  type ChartTimeframe,
} from "@/types/chart";

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
  /** Restore the four chart-appearance knobs to factory values. */
  resetAppearance: () => void;
}

/** Factory values for the chart-appearance knobs — single source for
 * the store initializer, the reset action, and the Settings UI's
 * "differs from default" check. */
export const APPEARANCE_DEFAULTS = {
  bullishColor: "#22E584", // bright mint-green candles (was muted #4DD17C)
  bearishColor: "#FF5A6A", // bright red candles (was muted #E85C5C)
  bgGradient: true,
  gridOpacity: 30,
} as const;

export const useUserSettings = create<UserSettingsState>()(
  persist(
    (set) => ({
      defaultTicker: "SPY",
      defaultContracts: 1,
      defaultTimeframe: DEFAULT_CHART_TIMEFRAME,
      ...APPEARANCE_DEFAULTS,
      setDefaultTicker: (s) => set({ defaultTicker: s.toUpperCase().trim() }),
      setDefaultContracts: (n) =>
        set({ defaultContracts: Math.max(1, Math.min(100, Math.floor(n))) }),
      setDefaultTimeframe: (tf) =>
        set({
          defaultTimeframe: isChartTimeframe(tf) ? tf : DEFAULT_CHART_TIMEFRAME,
        }),
      setBullishColor: (hex) => set({ bullishColor: hex }),
      setBearishColor: (hex) => set({ bearishColor: hex }),
      setBgGradient: (on) => set({ bgGradient: on }),
      setGridOpacity: (pct) =>
        set({ gridOpacity: Math.max(0, Math.min(100, Math.round(pct))) }),
      resetAppearance: () => set({ ...APPEARANCE_DEFAULTS }),
    }),
    {
      name: "td:user-settings",
      // Schema bump 2 — the chart timeframe ladder swapped from
      // lookback-range buttons ("1D"/"5D"/"1M"/"3M") to candle-
      // interval buttons ("1m"/"5m"/"15m"/"1h"/"4h"/"1D"). Anyone
      // with a persisted defaultTimeframe outside the new ladder
      // gets normalized to DEFAULT_CHART_TIMEFRAME on next load.
      version: 2,
      migrate: (persisted, fromVersion) => {
        const draft = (persisted ?? {}) as Partial<UserSettingsState>;
        if (fromVersion < 2 && !isChartTimeframe(draft.defaultTimeframe)) {
          draft.defaultTimeframe = DEFAULT_CHART_TIMEFRAME;
        }
        return draft;
      },
    },
  ),
);
