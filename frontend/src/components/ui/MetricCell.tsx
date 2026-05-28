import type { ReactNode } from "react";

interface Props {
  label: string;
  value: string | ReactNode;
  valueColor?: "primary" | "bullish" | "bearish";
  subContext?: string;
  tooltip?: string;
  /** Bottom border becomes 1px dashed warning color (model signals row). */
  failingBaseline?: boolean;
  className?: string;
}

/**
 * Bloomberg-archetype metric cell — no card chrome. Cell borders are owned
 * by the parent row (via per-cell `border-r`); this primitive only draws
 * content and the optional failing-baseline bottom rule.
 */
export function MetricCell({
  label,
  value,
  valueColor = "primary",
  subContext,
  tooltip,
  failingBaseline = false,
  className = "",
}: Props) {
  const valueColorClass =
    valueColor === "bullish"
      ? "text-bullish"
      : valueColor === "bearish"
      ? "text-bearish"
      : "text-fg-primary";

  const baseClasses = [
    "flex flex-col gap-0.5 py-1.5 px-3 min-w-0",
    failingBaseline ? "border-b border-dashed border-warning" : "",
    className,
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <div className={baseClasses} title={tooltip}>
      <span className="text-tiny uppercase tracking-label-up text-fg-secondary truncate">
        {label}
      </span>
      <span className={`text-large font-medium tabular-nums truncate ${valueColorClass}`}>
        {value}
      </span>
      {subContext && (
        <span className="text-xs2 text-fg-tertiary truncate lowercase">{subContext}</span>
      )}
    </div>
  );
}
