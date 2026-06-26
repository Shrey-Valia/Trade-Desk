import { create } from "zustand";
import { persist } from "zustand/middleware";

import {
  INDICATOR_CATALOG,
  MAX_INDICATOR_PERIOD,
  MIN_INDICATOR_PERIOD,
  indicatorDef,
} from "@/types/indicators";

/**
 * Per-indicator lookback periods (e.g. SMA 20, EMA 50, RSI 9).
 *
 * Persisted alongside the enabled-indicators store so a trader's tuned
 * windows survive reloads. Keyed by indicator FAMILY (sma/ema/rsi/atr);
 * VWAP is windowless and never appears here. A family with no stored
 * override falls back to its catalog `defaultPeriod` — so this store only
 * holds the deltas, and clearing an override returns the chip to default.
 *
 * `useTickerIndicators` joins these with the enabled set into the
 * `family:period` query tokens the /indicators endpoint consumes; the
 * period is part of the cache key on both sides, so changing a window
 * refetches just that series.
 */
interface IndicatorPeriodsState {
  periods: Record<string, number>; // family -> period (override only)
  setPeriod: (key: string, period: number) => void;
  resetPeriod: (key: string) => void;
  /** Effective period for a family — stored override or catalog default. */
  periodFor: (key: string) => number | null;
}

// Only parameterizable families may carry a period override.
const PARAMETERIZABLE = new Set(
  INDICATOR_CATALOG.filter((d) => d.parameterizable).map((d) => d.key),
);

/** Clamp a requested period into the supported window and coerce to int.
 *  Mirrors the backend's [2, 400] bound so we never send a value the
 *  server will silently clamp (which would desync the cache key). */
export function clampPeriod(n: number): number {
  if (!Number.isFinite(n)) return MIN_INDICATOR_PERIOD;
  const i = Math.round(n);
  return Math.max(MIN_INDICATOR_PERIOD, Math.min(MAX_INDICATOR_PERIOD, i));
}

export const useIndicatorPeriods = create<IndicatorPeriodsState>()(
  persist(
    (set, get) => ({
      periods: {},
      setPeriod: (key, period) =>
        set((s) => {
          if (!PARAMETERIZABLE.has(key)) return s;
          const clamped = clampPeriod(period);
          // Storing the default is a no-op override — drop the key instead
          // so the persisted state stays minimal and "reset" is implicit.
          const def = indicatorDef(key)?.defaultPeriod ?? null;
          const next = { ...s.periods };
          if (clamped === def) {
            delete next[key];
          } else {
            next[key] = clamped;
          }
          return { periods: next };
        }),
      resetPeriod: (key) =>
        set((s) => {
          if (!(key in s.periods)) return s;
          const next = { ...s.periods };
          delete next[key];
          return { periods: next };
        }),
      periodFor: (key) => {
        const def = indicatorDef(key);
        if (!def) return null;
        if (!def.parameterizable) return null;
        return get().periods[key] ?? def.defaultPeriod;
      },
    }),
    {
      name: "td:indicator-periods",
      // Drop overrides for families that are no longer parameterizable / in
      // the catalog, and re-clamp anything out of range, so a catalog change
      // can't leave a stale or invalid window in the query tokens.
      merge: (persisted, current) => {
        const p = persisted as Partial<IndicatorPeriodsState> | undefined;
        const cleaned: Record<string, number> = {};
        for (const [k, v] of Object.entries(p?.periods ?? {})) {
          if (PARAMETERIZABLE.has(k) && typeof v === "number") {
            cleaned[k] = clampPeriod(v);
          }
        }
        return { ...current, periods: cleaned };
      },
    },
  ),
);
