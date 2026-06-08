import React from "react";

export type ButtonVariant = "primary" | "secondary" | "ghost" | "danger";
export type ButtonSize = "sm" | "md" | "lg";

/**
 * Trade Desk button — monospace, 4px radius, amber-on-raised when active.
 *
 * @startingPoint section="Core" subtitle="Button — primary / secondary / ghost / danger" viewport="700x120"
 */
export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  /** Visual treatment. Default "secondary". */
  variant?: ButtonVariant;
  /** Height/padding scale. Default "md". */
  size?: ButtonSize;
  /** Selected state — turns text amber (secondary/ghost only). */
  active?: boolean;
  disabled?: boolean;
}

export function Button(props: ButtonProps): JSX.Element;
