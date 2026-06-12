import { create } from "zustand";
import { persist } from "zustand/middleware";

import type { TierKey } from "@/types/account";
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
  /**
   * Per-tier DLL override. `undefined` means use the backend default
   * (Topstep-aligned $1.5K / $3K / $4.5K). Range 1-10% of starting
   * balance is enforced at the setter.
   */
  dllOverrides: Partial<Record<TierKey, number>>;
  setDefaultTicker: (s: string) => void;
  setDefaultContracts: (n: number) => void;
  setDefaultTimeframe: (tf: ChartTimeframe) => void;
  setBullishColor: (hex: string) => void;
  setBearishColor: (hex: string) => void;
  setBgGradient: (on: boolean) => void;
  setGridOpacity: (pct: number) => void;
  setDllOverride: (tier: TierKey, amount: number | null) => void;
  /** Restore the four chart-appearance knobs to factory values. */
  resetAppearance: () => void;
}

/** Factory values for the chart-appearance knobs — single source for
 * the store initializer, the reset action, and the Settings UI's
 * "differs from default" check. */
export const APPEARANCE_DEFAULTS = {
  bullishColor: "#4DD17C",
  bearishColor: "#E85C5C",
  bgGradient: true,
  gridOpacity: 30,
} as const;

const TIER_STARTING_BALANCE: Record<TierKey, number> = {
  "50K": 50_000,
  "100K": 100_000,
  "150K": 150_000,
};

export const useUserSettings = create<UserSettingsState>()(
  persist(
    (set) => ({
      defaultTicker: "SPY",
      defaultContracts: 1,
      defaultTimeframe: DEFAULT_CHART_TIMEFRAME,
      ...APPEARANCE_DEFAULTS,
      dllOverrides: {},
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
      setDllOverride: (tier, amount) =>
        set((state) => {
          const next = { ...state.dllOverrides };
          if (amount == null || !Number.isFinite(amount)) {
            delete next[tier];
          } else {
            const start = TIER_STARTING_BALANCE[tier];
            const min = Math.round(start * 0.01);
            const max = Math.round(start * 0.10);
            const clamped = Math.max(min, Math.min(max, Math.round(amount)));
            next[tier] = clamped;
          }
          return { dllOverrides: next };
        }),
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
