import { create } from "zustand";
import { persist } from "zustand/middleware";

/**
 * First-run coachmark dismissal state.
 *
 * Two hints in Phase 1: one on the theta scrubber, one on the on-chart
 * magenta band. Each is shown once per user; dismissing it sets the
 * matching flag and the hint never returns. Stored in localStorage so
 * it survives reloads but a fresh browser / new device shows it again.
 */
type CoachmarkKey = "scrubber" | "magentaBE";

interface CoachmarksState {
  seen: Record<CoachmarkKey, boolean>;
  dismiss: (key: CoachmarkKey) => void;
  hasSeen: (key: CoachmarkKey) => boolean;
}

export const useCoachmarks = create<CoachmarksState>()(
  persist(
    (set, get) => ({
      seen: { scrubber: false, magentaBE: false },
      dismiss: (key) =>
        set((s) => ({ seen: { ...s.seen, [key]: true } })),
      hasSeen: (key) => get().seen[key] === true,
    }),
    { name: "td:coachmarks" },
  ),
);
