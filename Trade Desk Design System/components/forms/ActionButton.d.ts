import React from "react";

export type ActionIntent = "buy" | "sell";

/**
 * ActionButton — large BUY / SELL ticket button with sub-label.
 *
 * @startingPoint section="Forms" subtitle="BUY / SELL action buttons" viewport="700x120"
 */
export interface ActionButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  /** "buy" (green fill) or "sell" (red fill). Default "buy". */
  intent?: ActionIntent;
  /** Main label, e.g. "BUY +1". */
  label: React.ReactNode;
  /** Sub-line, e.g. "long call · $8.00 debit". */
  sub?: React.ReactNode;
  disabled?: boolean;
}

export function ActionButton(props: ActionButtonProps): JSX.Element;
