import { Outlet } from "react-router-dom";

import { LeftRail } from "./LeftRail";
import { MobileBottomNav } from "./MobileBottomNav";

/**
 * Shared shell for every rail route. Desktop: left rail + content (flex row).
 * Mobile (< md): the rail is hidden and a bottom nav takes over (flex column,
 * content above, nav below) — both in-flow so nothing overlaps.
 *
 * Pages already use flex-1 / min-w-0, so they shrink cleanly into whichever
 * column the breakpoint gives them.
 */
export function RailShell() {
  return (
    <div className="flex flex-col md:flex-row h-full min-h-0">
      <LeftRail />
      <div className="flex-1 min-w-0 min-h-0 flex flex-col">
        <Outlet />
      </div>
      <MobileBottomNav />
    </div>
  );
}
