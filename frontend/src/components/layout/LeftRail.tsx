import { NavLink } from "react-router-dom";

import { TradeDeskMark } from "@/components/branding/TradeDeskMark";
import { useOnboarding } from "@/stores/onboarding";

import {
  AccountsIcon,
  AnalyticsIcon,
  ChartIcon,
  DashboardIcon,
  JournalIcon,
  PayoutsIcon,
  SettingsIcon,
} from "./RailIcons";

export interface RailItem {
  to: string;
  label: string;
  icon: React.ComponentType<React.SVGProps<SVGSVGElement>>;
}

// Visual rework: WATCH dropped from the rail, and the /watchlist route
// itself was retired (unknown URLs funnel to "/" in App.tsx) — the rail
// is the complete route map until the watchlist concept comes back.
// Exported so the mobile bottom nav renders the same destinations.
export const TOP_ITEMS: RailItem[] = [
  { to: "/dashboard", label: "Home", icon: DashboardIcon },
  { to: "/accounts", label: "Accounts", icon: AccountsIcon },
  { to: "/payouts", label: "Payouts", icon: PayoutsIcon },
  { to: "/positions", label: "Chart", icon: ChartIcon },
  { to: "/journal", label: "Journal", icon: JournalIcon },
  { to: "/analytics", label: "Analytics", icon: AnalyticsIcon },
];

export const BOTTOM_ITEMS: RailItem[] = [
  { to: "/settings", label: "Settings", icon: SettingsIcon },
];

/**
 * Persistent left navigation rail.
 *
 * 48px wide, full-height, bg-tier-1, hairline right border. New
 * Trade Desk mark sits at the top (centered, ~16px below the top
 * edge) with a hairline divider beneath it; nav icons follow.
 *
 * Active state: amber 3px left rule + amber icon + amber label.
 * Inactive: fg-secondary icon, fg-tertiary-2 label.
 * Hover: bg-tier-2 on the whole entry.
 *
 * Rail is app-level chrome — rendered by RailShell, not per-route.
 */
export function LeftRail() {
  return (
    <nav
      aria-label="Primary"
      className="hidden md:flex flex-col items-stretch border-r border-hairline bg-tier-1 shrink-0"
      style={{ width: 72 }}
    >
      <div className="flex justify-center pt-3 pb-3">
        <TradeDeskMark size={36} />
      </div>
      <div className="mx-auto w-6 border-t border-hairline" />
      <ul className="flex flex-col pt-3">
        {TOP_ITEMS.map((item) => (
          <RailEntry key={item.to} item={item} />
        ))}
      </ul>
      <div className="mt-auto pb-2">
        <ul className="flex flex-col">
          <li>
            <HelpEntry />
          </li>
          {BOTTOM_ITEMS.map((item) => (
            <RailEntry key={item.to} item={item} />
          ))}
        </ul>
      </div>
    </nav>
  );
}

/** Help is an ACTION (opens the glossary overlay), not a route — so it's a
 *  button styled to match the rail entries rather than a NavLink. */
function HelpEntry() {
  const setHelpOpen = useOnboarding((s) => s.setHelpOpen);
  return (
    <button
      type="button"
      onClick={() => setHelpOpen(true)}
      title="Help & glossary (?)"
      aria-label="Open help and glossary"
      className="w-full flex flex-col items-center justify-center gap-1 py-2.5 px-1 text-fg-secondary hover:bg-tier-2 hover:text-fg-primary transition-opacity duration-100"
    >
      <svg
        width={20}
        height={20}
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth={1.8}
        strokeLinecap="round"
        strokeLinejoin="round"
        aria-hidden
      >
        <circle cx="12" cy="12" r="9" />
        <path d="M9.2 9.3a2.8 2.8 0 0 1 5.4 1c0 1.9-2.8 2.5-2.8 2.5" />
        <line x1="12" y1="17" x2="12" y2="17" />
      </svg>
      <span
        className="uppercase text-fg-tertiary-2"
        style={{ fontSize: 11, letterSpacing: "0.02em" }}
      >
        Help
      </span>
    </button>
  );
}

function RailEntry({ item }: { item: RailItem }) {
  const Icon = item.icon;
  return (
    <li>
      <NavLink
        to={item.to}
        end={item.to === "/"}
        className={({ isActive }) =>
          [
            "relative flex flex-col items-center justify-center gap-1 py-2.5 px-1",
            "transition-opacity duration-100",
            isActive
              ? "bg-tier-2 text-amber"
              : "text-fg-secondary hover:bg-tier-2 hover:text-fg-primary",
          ].join(" ")
        }
        title={item.label}
      >
        {({ isActive }) => (
          <>
            {isActive && (
              <span
                aria-hidden
                className="absolute left-0 top-0 bottom-0 bg-amber"
                style={{ width: 3 }}
              />
            )}
            <Icon />
            <span
              className={[
                "uppercase",
                isActive ? "text-amber" : "text-fg-tertiary-2",
              ].join(" ")}
              style={{ fontSize: 11, letterSpacing: "0.02em" }}
            >
              {item.label}
            </span>
          </>
        )}
      </NavLink>
    </li>
  );
}
