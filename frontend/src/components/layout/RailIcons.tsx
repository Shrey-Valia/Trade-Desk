/**
 * Monoline icon set for the LeftRail.
 *
 * Inline SVGs (no icon library — keeps the bundle lean and the look
 * consistent with the terminal aesthetic). Each icon is 20×20, stroke
 * 1.5, no fills except where needed. They inherit `currentColor` so
 * the rail's active-state amber + inactive-state fg-secondary just
 * work via className.
 */

import type { SVGProps } from "react";

type IconProps = SVGProps<SVGSVGElement>;

const BASE_PROPS: IconProps = {
  width: 20,
  height: 20,
  viewBox: "0 0 20 20",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 1.5,
  strokeLinecap: "round",
  strokeLinejoin: "round",
};

export function DashboardIcon(props: IconProps) {
  // Four tiles, one filled — the management-overview cue.
  return (
    <svg {...BASE_PROPS} {...props}>
      <rect x="3" y="3" width="6" height="6" fill="currentColor" />
      <rect x="11" y="3" width="6" height="6" />
      <rect x="3" y="11" width="6" height="6" />
      <rect x="11" y="11" width="6" height="6" />
    </svg>
  );
}

export function AccountsIcon(props: IconProps) {
  // Two stacked cards — the multi-account ("all your accounts") cue; the
  // front card is filled to read as the active one.
  return (
    <svg {...BASE_PROPS} {...props}>
      <rect x="6" y="3" width="11" height="7" rx="1" />
      <rect x="3" y="10" width="11" height="7" rx="1" fill="currentColor" />
    </svg>
  );
}

export function PayoutsIcon(props: IconProps) {
  // A coin with a dollar stroke — the payouts cue.
  return (
    <svg {...BASE_PROPS} {...props}>
      <circle cx="10" cy="10" r="7" />
      <path d="M10 6v8M12 8c0-0.9-0.9-1.4-2-1.4S8 7.1 8 8s.9 1.3 2 1.5 2 .6 2 1.5-.9 1.4-2 1.4-2-.5-2-1.4" />
    </svg>
  );
}

export function ChartIcon(props: IconProps) {
  // Two candlesticks with wicks — the price-chart product cue.
  return (
    <svg {...BASE_PROPS} {...props}>
      <line x1="6" y1="3" x2="6" y2="17" />
      <rect x="4" y="6" width="4" height="7" fill="currentColor" />
      <line x1="14" y1="3" x2="14" y2="17" />
      <rect x="12" y="8" width="4" height="5" />
    </svg>
  );
}

export function JournalIcon(props: IconProps) {
  // A ruled notebook — open book read as journal/log.
  return (
    <svg {...BASE_PROPS} {...props}>
      <path d="M4 4h9a2 2 0 0 1 2 2v11H6a2 2 0 0 1-2-2V4z" />
      <line x1="7" y1="8" x2="12" y2="8" />
      <line x1="7" y1="11" x2="12" y2="11" />
      <line x1="7" y1="14" x2="10" y2="14" />
    </svg>
  );
}

export function AnalyticsIcon(props: IconProps) {
  // Three ascending bars — stats / aggregations.
  return (
    <svg {...BASE_PROPS} {...props}>
      <line x1="3" y1="17" x2="17" y2="17" />
      <rect x="4" y="11" width="3" height="6" />
      <rect x="9" y="7" width="3" height="10" />
      <rect x="14" y="4" width="3" height="13" />
    </svg>
  );
}

export function WatchlistIcon(props: IconProps) {
  // List rows with a small lead dot — a scan list.
  return (
    <svg {...BASE_PROPS} {...props}>
      <circle cx="4.5" cy="5.5" r="1" fill="currentColor" stroke="none" />
      <line x1="8" y1="5.5" x2="17" y2="5.5" />
      <circle cx="4.5" cy="10" r="1" fill="currentColor" stroke="none" />
      <line x1="8" y1="10" x2="17" y2="10" />
      <circle cx="4.5" cy="14.5" r="1" fill="currentColor" stroke="none" />
      <line x1="8" y1="14.5" x2="17" y2="14.5" />
    </svg>
  );
}

export function ZeroDteIcon(props: IconProps) {
  // Hourglass — decay/clock cue for the 0DTE prototype destination.
  return (
    <svg {...BASE_PROPS} {...props}>
      <line x1="4" y1="3" x2="16" y2="3" />
      <line x1="4" y1="17" x2="16" y2="17" />
      <path d="M5 3v3l5 4-5 4v3M15 3v3l-5 4 5 4v3" />
    </svg>
  );
}

export function SupportIcon(props: IconProps) {
  // Life buoy — ring with four spokes; the universal "help desk" cue,
  // distinct from the rail's question-mark Help (glossary) action.
  return (
    <svg {...BASE_PROPS} {...props}>
      <circle cx="10" cy="10" r="7" />
      <circle cx="10" cy="10" r="3" />
      <path d="M7.9 7.9 5.1 5.1M12.1 7.9l2.8-2.8M12.1 12.1l2.8 2.8M7.9 12.1l-2.8 2.8" />
    </svg>
  );
}

export function AdminIcon(props: IconProps) {
  // Shield with a key dot — the operator/back-office cue (admin-only rail
  // entry; workstream D1).
  return (
    <svg {...BASE_PROPS} {...props}>
      <path d="M10 2.5 16 5v5c0 4-2.7 6.4-6 7.5-3.3-1.1-6-3.5-6-7.5V5l6-2.5z" />
      <circle cx="10" cy="8.5" r="1.6" />
      <path d="M10 10.1v3" />
    </svg>
  );
}

export function SettingsIcon(props: IconProps) {
  // Gear — simplified six-tooth ring around a center circle.
  return (
    <svg {...BASE_PROPS} {...props}>
      <circle cx="10" cy="10" r="2.5" />
      <path d="M10 2.5v2M10 15.5v2M2.5 10h2M15.5 10h2M4.7 4.7l1.4 1.4M13.9 13.9l1.4 1.4M4.7 15.3l1.4-1.4M13.9 6.1l1.4-1.4" />
    </svg>
  );
}
