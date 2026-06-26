import { create } from "zustand";
import { persist } from "zustand/middleware";

import { INDICATOR_CATALOG } from "@/types/indicators";

/**
 * Which technical-indicator overlays are currently toggled on.
 *
 * Persisted (like chartPrefs) so the trader's choice survives reloads.
 * The set of *available* indicators lives in INDICATOR_CATALOG; this
 * store only tracks which keys are enabled. The enabled keys are joined
 * into the `set` query param the indicators endpoint consumes.
 *
 * Defaults to empty (clean chart) — the trader opts indicators in, the
 * same way market-structure annotations default off.
 */
interface IndicatorsState {
  enabled: string[]; // ordered subset of INDICATOR_CATALOG keys
  toggle: (key: string) => void;
  isEnabled: (key: string) => boolean;
  clear: () => void;
}

const VALID_KEYS = new Set(INDICATOR_CATALOG.map((d) => d.key));

// Migrate a legacy persisted key (the old period-baked form, e.g. "sma20",
// "rsi14", "atr14") to its family token ("sma", "rsi", "atr"). VWAP was
// already bare. Returns null if it maps to nothing in the current catalog.
function migrateEnabledKey(key: string): string | null {
  if (VALID_KEYS.has(key)) return key;
  const family = key.replace(/\d+$/, "");
  return VALID_KEYS.has(family) ? family : null;
}

export const useIndicators = create<IndicatorsState>()(
  persist(
    (set, get) => ({
      enabled: [],
      toggle: (key) =>
        set((s) => {
          if (!VALID_KEYS.has(key)) return s;
          return s.enabled.includes(key)
            ? { enabled: s.enabled.filter((k) => k !== key) }
            : { enabled: [...s.enabled, key] };
        }),
      isEnabled: (key) => get().enabled.includes(key),
      clear: () => set({ enabled: [] }),
    }),
    {
      name: "td:indicators",
      // Migrate legacy period-baked keys (sma20 → sma) and drop any that no
      // longer map to a catalog family, de-duplicating, so a catalog change
      // or this period-refactor can't leave a stale token in the query set.
      merge: (persisted, current) => {
        const p = persisted as Partial<IndicatorsState> | undefined;
        const seen = new Set<string>();
        const enabled: string[] = [];
        for (const k of p?.enabled ?? []) {
          const fam = migrateEnabledKey(k);
          if (fam && !seen.has(fam)) {
            seen.add(fam);
            enabled.push(fam);
          }
        }
        return { ...current, enabled };
      },
    },
  ),
);

/**
 * Stable, catalog-ordered query token for the enabled set (or "").
 *
 * Each enabled family is emitted as a `family:period` token using the
 * caller-supplied `periodFor` resolver (the indicatorPeriods store); a
 * windowless family (VWAP, or any with no period) is emitted bare. The
 * catalog order keeps the token stable regardless of toggle order, so the
 * react-query / backend cache keys don't churn — they change ONLY when the
 * enabled set or a period actually changes.
 */
export function enabledSetParam(
  enabled: string[],
  periodFor?: (key: string) => number | null,
): string {
  return INDICATOR_CATALOG.filter((d) => enabled.includes(d.key))
    .map((d) => {
      const period = periodFor ? periodFor(d.key) : d.defaultPeriod;
      return period == null ? d.key : `${d.key}:${period}`;
    })
    .join(",");
}
