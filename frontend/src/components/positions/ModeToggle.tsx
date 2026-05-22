import { NavLink, useLocation } from "react-router-dom";

const SEGMENTS: { label: string; to: string; match: (path: string) => boolean }[] = [
  {
    label: "Analysis",
    to: "/",
    match: (p) => p !== "/positions" && p !== "/analytics",
  },
  {
    label: "Positions",
    to: "/positions",
    match: (p) => p === "/positions",
  },
  {
    label: "Analytics",
    to: "/analytics",
    match: (p) => p === "/analytics",
  },
];

/**
 * Top-level mode switcher. Two segments, 11px uppercase tracked. Active
 * segment uses FG PRIMARY + 2px amber bottom rule (matches the existing
 * TopNavBar tab treatment), inactive is FG SECONDARY.
 *
 * Used in both shells: rendered on the right side of the Analysis-mode
 * TopNavBar AND inside the Positions-mode TradeDeskToolbar. The mode it
 * shows as active is derived from the URL path, not internal state, so
 * back/forward navigation stays consistent.
 */
export function ModeToggle() {
  const { pathname } = useLocation();
  return (
    <div className="flex items-stretch gap-4" role="group" aria-label="Mode">
      {SEGMENTS.map((seg) => {
        const active = seg.match(pathname);
        return (
          <NavLink
            key={seg.to}
            to={seg.to}
            className={[
              "flex items-center text-xs2 uppercase tracking-label-up border-b-2",
              active
                ? "text-fg-primary border-amber"
                : "text-fg-secondary border-transparent hover:text-fg-primary",
            ].join(" ")}
          >
            {seg.label}
          </NavLink>
        );
      })}
    </div>
  );
}
