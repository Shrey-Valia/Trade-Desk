import type { HTMLAttributes, ReactNode } from "react";

export type MetricTone = "default" | "bullish" | "bearish" | "warning" | "amber";

export interface MetricPillProps extends HTMLAttributes<HTMLDivElement> {
  /** Uppercase micro-label, e.g. "UP&L". */
  label: ReactNode;
  /** The value (string or number), rendered tabular. */
  value: ReactNode;
  /** Explicit value color. */
  tone?: MetricTone;
  /** When set, colors the value by sign (+ bullish / − bearish / 0 primary). */
  signed?: number;
  /** Optional muted suffix after the value. */
  sub?: ReactNode;
  /** Min width in px. Default 110. */
  width?: number;
  className?: string;
  /** Inline extras after the value — e.g. a <Badge>BREACH</Badge>. */
  children?: ReactNode;
}

/**
 * MetricPill — the terminal's core "card". A labeled value box:
 * tier-2 fill + 1px tier-3 border + 4px radius, ~110×44, 10px uppercase
 * label over a 15px medium value. This is the entire card vocabulary of
 * the product — BAL / MLL / DLL / RP&L / UP&L / MKT.
 *
 * `tone` colors the value; `signed` maps +/− to bullish/bearish. Numbers
 * are tabular. Matches the inline pill currently in TradeDeskHeader so a
 * later call-site swap is pixel-identical.
 *
 * Distinct from `ui/MetricCell`, which is a CHROME-LESS dense-row cell
 * (no border/radius, 17px value); this is the bordered header pill.
 */
export function MetricPill({
  label,
  value,
  tone = "default",
  signed,
  sub,
  width = 110,
  className = "",
  children,
  style,
  ...rest
}: MetricPillProps) {
  const valueColor =
    tone === "bullish"
      ? "text-bullish"
      : tone === "bearish"
        ? "text-bearish"
        : tone === "warning"
          ? "text-warning"
          : tone === "amber"
            ? "text-amber"
            : signed !== undefined
              ? signed > 0
                ? "text-bullish"
                : signed < 0
                  ? "text-bearish"
                  : "text-fg-primary"
              : "text-fg-primary";

  return (
    <div
      className={[
        "flex flex-col leading-tight",
        "bg-tier-2 border border-tier-3 rounded-btn px-2.5 py-1",
        className,
      ].join(" ")}
      style={{ height: 44, minWidth: width, ...style }}
      {...rest}
    >
      <span
        className="uppercase tracking-label-up text-fg-tertiary-2"
        style={{ fontSize: 12, letterSpacing: "0.08em" }}
      >
        {label}
      </span>
      <span
        className={`tabular-nums font-medium flex items-baseline gap-1 ${valueColor}`}
        style={{ fontSize: 15, marginTop: 2 }}
      >
        {value}
        {children}
        {sub && (
          <span className="text-fg-tertiary-2" style={{ fontSize: 12 }}>
            {sub}
          </span>
        )}
      </span>
    </div>
  );
}
