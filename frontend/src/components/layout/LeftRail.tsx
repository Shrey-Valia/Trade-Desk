import { NavLink } from "react-router-dom";

import { TradeDeskMark } from "@/components/branding/TradeDeskMark";

import {
  AccountsIcon,
  AnalyticsIcon,
  ChartIcon,
  DashboardIcon,
  JournalIcon,
  PayoutsIcon,
  SettingsIcon,
} from "./RailIcons";

interface RailItem {
  to: string;
  label: string;
  icon: React.ComponentType<React.SVGProps<SVGSVGElement>>;
}

// Visual rework: WATCH dropped from the rail. The /watchlist route is
// still reachable directly; we just don't surface it as a destination
// in the primary nav until the watchlist concept comes back online.
const TOP_ITEMS: RailItem[] = [
  { to: "/dashboard", label: "Home", icon: DashboardIcon },
  { to: "/accounts", label: "Accounts", icon: AccountsIcon },
  { to: "/payouts", label: "Payouts", icon: PayoutsIcon },
  { to: "/positions", label: "Chart", icon: ChartIcon },
  { to: "/journal", label: "Journal", icon: JournalIcon },
  { to: "/analytics", label: "Analytics", icon: AnalyticsIcon },
];

const BOTTOM_ITEMS: RailItem[] = [
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
      className="flex flex-col items-stretch border-r border-hairline bg-tier-1 shrink-0"
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
          {BOTTOM_ITEMS.map((item) => (
            <RailEntry key={item.to} item={item} />
          ))}
        </ul>
      </div>
    </nav>
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
