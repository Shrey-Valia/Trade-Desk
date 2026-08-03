import { create } from "zustand";
import { persist } from "zustand/middleware";

/**
 * Terminal density mode — the progressive-disclosure switch for the
 * positions terminal (P1-8, UI simplicity audit).
 *
 * "simple" (the default) shows only the essentials a new trader needs:
 * the chart + timeframes, the option chain, the trade ticket, and the
 * active-position readouts. "advanced" additionally reveals the
 * expert chrome — chart indicators (SMA/EMA/RSI/…), the vol-regime
 * strip (IVR/skew/VRP/term), the macro econ-calendar tape, and the
 * KEY LEVELS market-structure panel (EM/CW/PW/MP/GF).
 *
 * Persisted so the choice survives reloads. Defaults to "simple" because
 * the whole-terminal firehose was the audit's biggest "confusing" driver;
 * power users flip to "advanced" once and it sticks.
 */
export type TerminalMode = "simple" | "advanced";

interface TerminalModeState {
  mode: TerminalMode;
  setMode: (mode: TerminalMode) => void;
  toggle: () => void;
}

export const useTerminalMode = create<TerminalModeState>()(
  persist(
    (set) => ({
      mode: "simple",
      setMode: (mode) => set({ mode }),
      toggle: () => set((s) => ({ mode: s.mode === "simple" ? "advanced" : "simple" })),
    }),
    { name: "td:terminal-mode" },
  ),
);
