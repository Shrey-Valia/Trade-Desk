import React from "react";

export type MetricTone = "default" | "bullish" | "bearish" | "warning" | "amber";

/**
 * MetricPill — labeled value box, the terminal's core card primitive.
 *
 * @startingPoint section="Core" subtitle="Metric pill — BAL / UP&L / MKT" viewport="700x120"
 */
export interface MetricPillProps extends React.HTMLAttributes<HTMLDivElement> {
  /** Uppercase micro-label, e.g. "UP&L". */
  label: React.ReactNode;
  /** The value (string or number), rendered tabular. */
  value: React.ReactNode;
  /** Explicit value color. */
  tone?: MetricTone;
  /** When set, colors the value by sign (+ bullish / − bearish). */
  signed?: number;
  /** Optional muted suffix after the value. */
  sub?: React.ReactNode;
  /** Min width in px. Default 110. */
  width?: number;
}

export function MetricPill(props: MetricPillProps): JSX.Element;
