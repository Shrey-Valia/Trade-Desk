import { Outlet } from "react-router-dom";

import { CommandPalette } from "@/components/command/CommandPalette";
import { HelpOverlay } from "@/components/help/HelpOverlay";
import { OnboardingTour } from "@/components/help/OnboardingTour";
import { useGlobalHotkeys } from "@/hooks/useGlobalHotkeys";

import { LeftRail } from "./LeftRail";
import { MobileBottomNav } from "./MobileBottomNav";

/**
 * Shared shell for every rail route. Desktop: left rail + content (flex row).
 * Mobile (< md): the rail is hidden and a bottom nav takes over (flex column,
 * content above, nav below) — both in-flow so nothing overlaps.
 *
 * Pages already use flex-1 / min-w-0, so they shrink cleanly into whichever
 * column the breakpoint gives them.
 *
 * WS6 mounts the onboarding + power-UX chrome here (inside the authed shell,
 * never on the signin/landing pages): the global hotkeys, the command palette,
 * the help/glossary overlay, and the first-run tour. A skip-to-content link is
 * the first focusable element for keyboard and screen-reader users.
 */
export function RailShell() {
  useGlobalHotkeys();
  return (
    <div className="flex flex-col md:flex-row h-full min-h-0">
      <a
        href="#main-content"
        className="sr-only focus:not-sr-only focus:absolute focus:z-[70] focus:top-2 focus:left-2 focus:bg-tier-2 focus:border focus:border-amber focus:rounded-btn focus:px-3 focus:py-1.5 focus:text-sm focus:text-fg-primary"
      >
        Skip to content
      </a>
      <LeftRail />
      {/* Skip-link target. A plain <div>, not <main>: most rail pages render
          their own <main> landmark, so the wrapper stays a generic container
          to avoid two main landmarks per route. */}
      <div id="main-content" className="flex-1 min-w-0 min-h-0 flex flex-col">
        <Outlet />
      </div>
      <MobileBottomNav />
      <CommandPalette />
      <HelpOverlay />
      <OnboardingTour />
    </div>
  );
}
