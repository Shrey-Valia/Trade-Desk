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

export function SettingsIcon(props: IconProps) {
  // Gear — simplified six-tooth ring around a center circle.
  return (
    <svg {...BASE_PROPS} {...props}>
      <circle cx="10" cy="10" r="2.5" />
      <path d="M10 2.5v2M10 15.5v2M2.5 10h2M15.5 10h2M4.7 4.7l1.4 1.4M13.9 13.9l1.4 1.4M4.7 15.3l1.4-1.4M13.9 6.1l1.4-1.4" />
    </svg>
  );
}
