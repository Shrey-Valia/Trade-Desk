import type { HTMLAttributes, ReactNode } from "react";

export type BadgeTone =
  | "bearish"
  | "warning"
  | "amber"
  | "bullish"
  | "cyan"
  | "muted";

export interface BadgeProps extends HTMLAttributes<HTMLSpanElement> {
  /** Color tone. Default "muted". */
  tone?: BadgeTone;
  className?: string;
  children?: ReactNode;
}

/**
 * Badge — small outlined status chip, never solid-filled. 16px tall,
 * 2px radius (`rounded-hair`), 9px uppercase with 0.08em tracking.
 * Use for inline status: BREACH, DLL HIT, 0DTE, ER, news tags.
 *
 * Tones: bearish (error/breach) · warning (advisory) · amber (active) ·
 * bullish · cyan (neutral/event) · muted.
 */
export function Badge({
  tone = "muted",
  className = "",
  children,
  ...rest
}: BadgeProps) {
  const toneCls =
    tone === "bearish"
      ? "text-bearish border-bearish"
      : tone === "warning"
        ? "text-warning border-warning"
        : tone === "amber"
          ? "text-amber border-amber"
          : tone === "bullish"
            ? "text-bullish border-bullish"
            : tone === "cyan"
              ? "text-cyan border-cyan"
              : "text-fg-tertiary-2 border-hairline-strong";

  return (
    <span
      className={[
        "inline-flex items-center whitespace-nowrap leading-none",
        "border bg-transparent rounded-hair font-medium uppercase tracking-label-up",
        toneCls,
        className,
      ].join(" ")}
      style={{ height: 16, padding: "0 5px", fontSize: 11 }}
      {...rest}
    >
      {children}
    </span>
  );
}
