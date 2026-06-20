import type { ReactNode } from "react";

/**
 * A composed empty state — an invitation to act, not a lonely line of text
 * floating in a void. Centered heading + one supporting line + an optional
 * action, with comfortable padding so a screen with no data still reads as
 * deliberate. Used across Dashboard / Payouts / Analytics / Journal so empty
 * surfaces are consistent.
 */
export function EmptyState({
  title,
  body,
  action,
  icon,
  compact = false,
  className = "",
}: {
  title: string;
  body?: string;
  action?: ReactNode;
  icon?: ReactNode;
  /** Tighter padding for in-panel empties (vs. full-page). */
  compact?: boolean;
  className?: string;
}) {
  return (
    <div
      className={[
        "flex flex-col items-center text-center",
        compact ? "px-6 py-10 gap-2" : "px-6 py-16 gap-2.5",
        className,
      ].join(" ")}
    >
      {icon && (
        <div
          className="mb-1 flex items-center justify-center text-fg-tertiary-2"
          aria-hidden
        >
          {icon}
        </div>
      )}
      <h3 className="text-medium font-medium text-fg-primary">{title}</h3>
      {body && (
        <p
          className="text-xs2 text-fg-tertiary-2 leading-relaxed"
          style={{ maxWidth: 400 }}
        >
          {body}
        </p>
      )}
      {action && <div className="mt-3 flex flex-wrap items-center justify-center gap-2">{action}</div>}
    </div>
  );
}
