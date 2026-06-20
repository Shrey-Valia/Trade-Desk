import { NavLink } from "react-router-dom";

import { BOTTOM_ITEMS, TOP_ITEMS } from "./LeftRail";

const ITEMS = [...TOP_ITEMS, ...BOTTOM_ITEMS];

/**
 * Mobile bottom navigation — replaces the left rail below the `md` breakpoint
 * (a 72px side rail eats too much of a phone screen). In-flow at the bottom of
 * the shell so it never overlaps content; icon-led with labels, active tinted
 * amber. Hidden on desktop, where the rail takes over.
 */
export function MobileBottomNav() {
  return (
    <nav
      aria-label="Primary"
      className="md:hidden flex items-stretch justify-around border-t border-hairline bg-tier-1 shrink-0"
      style={{ paddingBottom: "env(safe-area-inset-bottom)" }}
    >
      {ITEMS.map(({ to, label, icon: Icon }) => (
        <NavLink
          key={to}
          to={to}
          end={to === "/"}
          aria-label={label}
          title={label}
          className={({ isActive }) =>
            [
              "flex flex-col items-center justify-center gap-0.5 flex-1 py-2 min-w-0",
              "transition-colors duration-100",
              isActive ? "text-amber" : "text-fg-tertiary-2 hover:text-fg-primary",
            ].join(" ")
          }
        >
          <Icon />
          <span
            className="uppercase tracking-label-up truncate w-full text-center"
            style={{ fontSize: 11, letterSpacing: "0.02em" }}
          >
            {label}
          </span>
        </NavLink>
      ))}
    </nav>
  );
}
