import { useEffect, useState } from "react";
import { create } from "zustand";
import { persist } from "zustand/middleware";

interface SelectedTickerState {
  symbol: string | null;
  setSymbol: (symbol: string | null) => void;
}

export const useSelectedTicker = create<SelectedTickerState>()(
  persist(
    (set) => ({
      symbol: null,
      setSymbol: (symbol) => set({ symbol }),
    }),
    { name: "selected-ticker" },
  ),
);

// Hydration gate. Zustand's persist middleware reads localStorage in an
// effect after the first render — without this, components render once
// with `symbol: null` even when there's a saved value, producing a flash
// of "Select a name from the watchlist". Subscribe to the hydration
// finish event so React re-renders the moment storage is restored.
export function useSelectedTickerHasHydrated(): boolean {
  const [hydrated, setHydrated] = useState(() =>
    useSelectedTicker.persist.hasHydrated(),
  );
  useEffect(() => {
    const unsub = useSelectedTicker.persist.onFinishHydration(() => setHydrated(true));
    setHydrated(useSelectedTicker.persist.hasHydrated());
    return () => unsub();
  }, []);
  return hydrated;
}
