import { NavLink } from "react-router-dom";

import {
  AnalyticsIcon,
  ChartIcon,
  JournalIcon,
  SettingsIcon,
  WatchlistIcon,
} from "./RailIcons";

interface RailItem {
  to: string;
  label: string;
  icon: React.ComponentType<React.SVGProps<SVGSVGElement>>;
}

const TOP_ITEMS: RailItem[] = [
  { to: "/positions", label: "Chart", icon: ChartIcon },
  { to: "/journal", label: "Journal", icon: JournalIcon },
  { to: "/analytics", label: "Analytics", icon: AnalyticsIcon },
  { to: "/watchlist", label: "Watch", icon: WatchlistIcon },
];

const BOTTOM_ITEMS: RailItem[] = [
  { to: "/settings", label: "Settings", icon: SettingsIcon },
];

/**
 * Persistent left navigation rail — Topstep / TradingView pattern.
 *
 * 56px wide, full-height, bg-tier-1 with a hairline right border.
 * Each destination is an icon + 9px uppercase label. Active state:
 * amber left accent bar (2px), amber icon + label, bg-tier-2.
 * Inactive: fg-secondary icon, no accent. Hover: bg-tier-2 with the
 * 100ms opacity transition the rest of the app uses (reduced-motion
 * stripped at the global CSS level).
 *
 * The rail is app-level chrome — rendered by RailShell, not per-route.
 */
export function LeftRail() {
  return (
    <nav
      aria-label="Primary"
      className="flex flex-col items-stretch border-r border-hairline bg-tier-1 shrink-0"
      style={{ width: 56 }}
    >
      <ul className="flex flex-col">
        {TOP_ITEMS.map((item) => (
          <RailEntry key={item.to} item={item} />
        ))}
      </ul>
      <div className="mt-auto">
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
                style={{ width: 2 }}
              />
            )}
            <Icon />
            <span
              className="text-tiny uppercase tracking-label-up"
              style={{ fontSize: 9, letterSpacing: "0.04em" }}
            >
              {item.label}
            </span>
          </>
        )}
      </NavLink>
    </li>
  );
}
