import { Outlet } from "react-router-dom";

import { LeftRail } from "./LeftRail";

/**
 * Shared shell for every chart-first route — the left rail on the
 * outer left, the route's own chrome (TradeDeskToolbar / etc.) and
 * content inside. Outlet renders whatever child route matched.
 *
 * The rail is on the outer flex row, so each child page lays out
 * inside a column that's ~56px narrower than the viewport. Existing
 * pages already use flex-1 / min-w-0 — they shrink cleanly.
 */
export function RailShell() {
  return (
    <div className="flex h-full min-h-0">
      <LeftRail />
      <div className="flex-1 min-w-0 min-h-0 flex flex-col">
        <Outlet />
      </div>
    </div>
  );
}
