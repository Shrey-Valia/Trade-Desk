import { NavLink } from "react-router-dom";

const NAV_LINKS: { to: string; label: string }[] = [
  { to: "/", label: "Dashboard" },
  { to: "/market", label: "Market" },
  { to: "/news", label: "News" },
  { to: "/signal", label: "Signal" },
];

/**
 * 24px function-key style nav bar — the retired ANALYSIS-mode header.
 *
 * Analysis mode is no longer reachable from the navigation revamp's
 * left rail (step 1), but its routes are still defined and this nav
 * still works when those URLs are hit directly. The old "ANALYSIS /
 * POSITIONS / ANALYTICS" toggle was removed from the right side; if
 * you're sitting on an Analysis route and want to leave, change the
 * URL — there's no cross-link from here back into the rail shell.
 */
export function TopNavBar() {
  return (
    <nav
      aria-label="Primary"
      className="flex items-stretch border-b border-hairline bg-tier-1 px-4"
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
    </nav>
  );
}
