import { create } from "zustand";
import { persist } from "zustand/middleware";

/**
 * First-run onboarding + help overlay state (WS6).
 *
 * Two independent concerns share this store:
 *   - `tourSeen`  : whether the first-run terminal walkthrough has been
 *                   completed/skipped. Gated so the tour shows exactly once
 *                   per browser; "Replay tour" in Help re-opens it without
 *                   clearing the flag.
 *   - `helpOpen`  : whether the glossary/help overlay is visible. Opened by
 *                   the "?" hotkey, the rail Help button, or the command
 *                   palette. Not persisted — it's transient UI state.
 *   - `tourOpen`  : whether the walkthrough modal is visible right now.
 *
 * Persisted under `td:onboarding` (localStorage) so it survives reloads but
 * a fresh browser / new device replays the tour, mirroring the existing
 * `td:coachmarks` convention.
 */
interface OnboardingState {
  /** First-run tour completed or skipped — persisted. */
  tourSeen: boolean;
  /** Walkthrough modal currently visible — transient. */
  tourOpen: boolean;
  /** Glossary/help overlay currently visible — transient. */
  helpOpen: boolean;
  /** Mark the tour seen (does NOT close the modal — caller does). */
  markTourSeen: () => void;
  openTour: () => void;
  closeTour: () => void;
  setHelpOpen: (open: boolean) => void;
  toggleHelp: () => void;
}

export const useOnboarding = create<OnboardingState>()(
  persist(
    (set) => ({
      tourSeen: false,
      tourOpen: false,
      helpOpen: false,
      markTourSeen: () => set({ tourSeen: true }),
      openTour: () => set({ tourOpen: true }),
      closeTour: () => set({ tourOpen: false }),
      setHelpOpen: (open) => set({ helpOpen: open }),
      toggleHelp: () => set((s) => ({ helpOpen: !s.helpOpen })),
    }),
    {
      name: "td:onboarding",
      // Only the "seen" flag is durable; transient UI flags must never
      // rehydrate as open (a reload should not pop the tour/help back up).
      partialize: (s) => ({ tourSeen: s.tourSeen }),
    },
  ),
);
