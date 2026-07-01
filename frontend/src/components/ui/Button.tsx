import type { ButtonHTMLAttributes, ReactNode } from "react";

export type ButtonVariant = "primary" | "secondary" | "ghost" | "danger";
export type ButtonSize = "sm" | "md" | "lg";

export interface ButtonProps
  extends Omit<ButtonHTMLAttributes<HTMLButtonElement>, "className"> {
  /** Visual treatment. Default "secondary". */
  variant?: ButtonVariant;
  /** Height/padding scale: sm 24px / md 32px / lg 40px. Default "md". */
  size?: ButtonSize;
  /** Selected state — turns text amber (secondary / ghost only). */
  active?: boolean;
  className?: string;
  children?: ReactNode;
}

/**
 * Trade Desk button — the design-system canonical button primitive.
 *
 * Monospace, 4px radius (`rounded-btn`), 1px border, 100ms color
 * transition, no shadow. Variants map to the terminal's real chrome:
 *   - primary   : amber border + amber text on the lifted (tier-3) fill
 *                 — the active CTA. (`active` is implicit; not needed.)
 *   - secondary : tier-2 fill, tier-3 border, secondary text; `active`
 *                 flips the text amber. The neutral chrome button.
 *   - ghost     : transparent, tertiary-2 text, lifts to secondary on
 *                 hover; `active` flips the text amber.
 *   - danger    : tier-2 fill, bearish border + text (destructive /
 *                 breach).
 *
 * Reconciliation note: this is intentionally SEPARATE from the existing
 * `ui/UIButton` (variant default|ghost|filled, sizes 26/32/38), which is
 * already consumed by ChartToolbar + SettingsPage — changing its API
 * would ripple into those live screens. Equivalence for a future
 * converge step: primary↔UIButton active · secondary↔default ·
 * ghost↔ghost · danger↔(new here).
 */
export function Button({
  variant = "secondary",
  size = "md",
  active = false,
  disabled = false,
  type = "button",
  className = "",
  children,
  ...rest
}: ButtonProps) {
  const visual = disabled
    ? "bg-tier-1 border-tier-2 text-fg-disabled cursor-not-allowed"
    : variant === "primary"
      ? "bg-amber text-tier-0 border-amber hover:opacity-90"
      : variant === "danger"
        ? "bg-tier-2 border-bearish text-bearish hover:bg-tier-3"
        : variant === "ghost"
          ? active
            ? "bg-transparent border-transparent text-amber"
            : "bg-transparent border-transparent text-fg-tertiary-2 hover:text-fg-secondary"
          : // secondary
            active
            ? "bg-tier-2 border-tier-3 text-amber hover:bg-tier-3"
            : "bg-tier-2 border-tier-3 text-fg-secondary hover:bg-tier-3 hover:text-fg-primary";

  return (
    <button
      type={type}
      disabled={disabled}
      data-variant={variant}
      data-active={active || undefined}
      className={[
        "inline-flex items-center justify-center gap-1.5 whitespace-nowrap",
        "rounded-btn border font-medium tabular-nums select-none",
        "transition-colors duration-100",
        SIZE_CLS[size],
        visual,
        className,
      ].join(" ")}
      {...rest}
    >
      {children}
    </button>
  );
}

const SIZE_CLS: Record<ButtonSize, string> = {
  sm: "h-6 px-2 text-[11px]",
  md: "h-8 px-3 text-[12px]",
  lg: "h-10 px-4 text-[14px]",
};
