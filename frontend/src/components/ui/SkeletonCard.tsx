/**
 * Hairline-cell skeleton matching the MetricCell shape. No card chrome
 * (no border, no radius); cell borders are owned by the parent row.
 * Static blocks per DESIGN.md skeleton rules.
 */
interface Props {
  label?: string;
}

export function SkeletonCard({ label }: Props) {
  return (
    <div className="flex flex-col gap-0.5 py-1.5 px-3 min-w-0">
      {label ? (
        <span className="text-tiny uppercase tracking-label-up text-fg-secondary truncate">
          {label}
        </span>
      ) : (
        <div className="h-2 w-1/2 bg-tier-2" />
      )}
      <div className="h-3 w-1/2 bg-tier-2" />
      <div className="h-2 w-3/4 bg-tier-2" />
    </div>
  );
}
