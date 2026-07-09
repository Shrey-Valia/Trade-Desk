import React from "react";

export type BadgeTone = "bearish" | "warning" | "amber" | "bullish" | "cyan" | "muted";

/**
 * Badge — small outlined status chip (BREACH, 0DTE, ER, MACRO).
 */
export interface BadgeProps extends React.HTMLAttributes<HTMLSpanElement> {
  /** Outline + text color. Default "muted". */
  tone?: BadgeTone;
}

export function Badge(props: BadgeProps): JSX.Element;
