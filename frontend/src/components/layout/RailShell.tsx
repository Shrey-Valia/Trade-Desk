import { Outlet } from "react-router-dom";

import { HelpOverlay } from "@/components/help/HelpOverlay";
import { OnboardingTour } from "@/components/help/OnboardingTour";

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
 * WS6 mounts the onboarding chrome here (inside the authed shell, never on
 * the signin/landing pages): the help/glossary overlay and the first-run
 * tour. A skip-to-content link is the first focusable element for keyboard
 * and screen-reader users. (The command palette + global hotkeys mount here
 * too — added in the power-UX pass.)
 */
export function RailShell() {
  return (
    <div className="flex flex-col md:flex-row h-full min-h-0">
      <a
        href="#main-content"
        className="sr-only focus:not-sr-only focus:absolute focus:z-[70] focus:top-2 focus:left-2 focus:bg-tier-2 focus:border focus:border-amber focus:rounded-btn focus:px-3 focus:py-1.5 focus:text-sm focus:text-fg-primary"
      >
        Skip to content
      </a>
      <LeftRail />
      <main id="main-content" className="flex-1 min-w-0 min-h-0 flex flex-col">
        <Outlet />
      </main>
      <MobileBottomNav />
      <HelpOverlay />
      <OnboardingTour />
    </div>
  );
}
