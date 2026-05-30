import type { ButtonHTMLAttributes, ReactNode } from "react";

type Variant = "default" | "ghost" | "filled";
type Size = "sm" | "md" | "lg";

export interface UIButtonProps
  extends Omit<ButtonHTMLAttributes<HTMLButtonElement>, "className"> {
  active?: boolean;
  variant?: Variant;
  size?: Size;
  className?: string;
  children?: ReactNode;
}

/**
 * Topstep-influenced filled button primitive.
 *
 * default — bg-tier-2 fill, 1px bg-tier-3 border, fg-primary text,
 *           bg-tier-3 on hover. The neutral chrome button used for
 *           timeframes, chart-type stubs, drawing tools, indicators,
 *           QTY chips, dropdowns, etc.
 *
 * ghost   — transparent fill, fg-secondary text, hover bg-tier-2.
 *           For low-volume affordances (LEGEND toggle, etc.).
 *
 * filled  — currently the same as default; reserved for the action
 *           BUY/SELL surface so a future variant flip is one prop
 *           away. (Phase D ships its own action buttons distinct
 *           from this primitive.)
 *
 * active=true overrides both: amber border, bg-tier-3, amber text.
 *
 * Sizes:
 *   sm — 26px tall, 11px text, 8px horizontal padding
 *   md — 32px tall, 13px text, 12px horizontal padding   (default)
 *   lg — 38px tall, 14px text, 16px horizontal padding
 *
 * All variants share: 4px border-radius, IBM Plex Mono, medium (500)
 * font weight on the label, tabular-nums.
 */
export function UIButton({
  active = false,
  variant = "default",
  size = "md",
  className,
  children,
  disabled,
  ...rest
}: UIButtonProps) {
  const sizing = SIZE_CLS[size];

  // Disabled wins over everything — sinks into the background, no
  // hover, no cursor pointer.
  const visual = disabled
    ? "bg-tier-1 border border-tier-2 text-fg-disabled cursor-not-allowed"
    : active
      ? "bg-tier-3 border border-amber text-amber"
      : variant === "ghost"
        ? "bg-transparent border border-transparent text-fg-secondary hover:bg-tier-2 hover:text-fg-primary"
        : "bg-tier-2 border border-tier-3 text-fg-primary hover:bg-tier-3";

  return (
    <button
      type="button"
      disabled={disabled}
      className={[
        "inline-flex items-center justify-center gap-1 tabular-nums",
        "transition-colors duration-100",
        "font-medium select-none",
        "rounded-btn",
        sizing,
        visual,
        className ?? "",
      ].join(" ")}
      {...rest}
    >
      {children}
    </button>
  );
}

const SIZE_CLS: Record<Size, string> = {
  sm: "h-[26px] px-2 text-[11px]",
  md: "h-8 px-3 text-[13px]",
  lg: "h-[38px] px-4 text-[14px]",
};
