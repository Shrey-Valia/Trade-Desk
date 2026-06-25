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
      // Drop any persisted keys that are no longer in the catalog so a
      // ladder change can't leave a stale token in the query set.
      merge: (persisted, current) => {
        const p = persisted as Partial<IndicatorsState> | undefined;
        const enabled = (p?.enabled ?? []).filter((k) => VALID_KEYS.has(k));
        return { ...current, enabled };
      },
    },
  ),
);

/** Stable, catalog-ordered query token for the enabled set (or ""). */
export function enabledSetParam(enabled: string[]): string {
  return INDICATOR_CATALOG.filter((d) => enabled.includes(d.key))
    .map((d) => d.key)
    .join(",");
}
