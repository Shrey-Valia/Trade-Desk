import { NavLink } from "react-router-dom";

import { ModeToggle } from "@/components/positions/ModeToggle";

const NAV_LINKS: { to: string; label: string }[] = [
  { to: "/", label: "Dashboard" },
  { to: "/market", label: "Market" },
  { to: "/news", label: "News" },
  { to: "/signal", label: "Signal" },
];

/**
 * 24px function-key style nav bar — sits between the 28px status strip
 * and the calendar strip / route content. Bloomberg metaphor: this is
 * the F1-F12 bar, not a web-app primary nav. Active tab gets a 2px
 * amber bottom rule (selection focus) and FG PRIMARY text; inactive
 * tabs are FG SECONDARY 11px uppercase tracked.
 */
export function TopNavBar() {
  return (
    <nav
      aria-label="Primary"
      className="flex items-stretch justify-between border-b border-hairline bg-tier-1 px-4"
      style={{ height: 24 }}
    >
      <div className="flex items-stretch gap-6">
        {NAV_LINKS.map((link) => (
          <NavLink
            key={link.to}
            to={link.to}
            end={link.to === "/"}
            className={({ isActive }) =>
              [
                "flex items-center text-xs2 uppercase tracking-label-up border-b-2",
                isActive
                  ? "text-fg-primary border-amber"
                  : "text-fg-secondary border-transparent hover:text-fg-primary",
              ].join(" ")
            }
          >
            {link.label}
          </NavLink>
        ))}
      </div>
      {/* Mode toggle sits to the right of the route tabs. In Analysis
          mode "Analysis" is the active segment; clicking "Positions"
          navigates to the Trade Desk shell. */}
      <div className="flex items-stretch">
        <ModeToggle />
      </div>
    </nav>
  );
}
