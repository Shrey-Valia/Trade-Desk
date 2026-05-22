import { create } from "zustand";
import { persist } from "zustand/middleware";

/**
 * User-toggleable chart display preferences.
 *
 * Phase 1 of the overnight polish adds these toggles so the trader can
 * choose what they see on the price chart. Persisted so the choice
 * survives reloads.
 *
 *   showMarketAnnotations: render EM±, CW, PW, MP, GF price lines. The
 *   magenta POSITION lines are NEVER hidden by this toggle — those are
 *   "your trade" and always present when a trade is active. Off-state
 *   gives the user a clean chart focused on their position alone.
 *
 *   showLegend: render the on-chart legend overlay that explains the
 *   color language. Most useful for first-time viewers; dismissible
 *   for users who already know the language.
 */
interface ChartPrefsState {
  showMarketAnnotations: boolean;
  showLegend: boolean;
  toggleMarketAnnotations: () => void;
  toggleLegend: () => void;
  setShowLegend: (v: boolean) => void;
}

export const useChartPrefs = create<ChartPrefsState>()(
  persist(
    (set) => ({
      showMarketAnnotations: true,
      showLegend: true,
      toggleMarketAnnotations: () =>
        set((s) => ({ showMarketAnnotations: !s.showMarketAnnotations })),
      toggleLegend: () => set((s) => ({ showLegend: !s.showLegend })),
      setShowLegend: (v) => set({ showLegend: v }),
    }),
    { name: "td:chart-prefs" },
  ),
);
