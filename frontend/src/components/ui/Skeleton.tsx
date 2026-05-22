/**
 * Static hairline rectangle for skeleton loading states.
 *
 * Bloomberg never animates loading — DESIGN.md mandates static blocks,
 * no shimmer. Background uses BG TIER 2 (`bg-tier-2`) for one notch of
 * elevation above the page background.
 */
interface Props {
  width?: number | string;
  height?: number | string;
  className?: string;
}

export function Skeleton({ width = "100%", height = 12, className = "" }: Props) {
  return (
    <div
      className={`bg-tier-2 ${className}`}
      style={{ width, height }}
    />
  );
}
