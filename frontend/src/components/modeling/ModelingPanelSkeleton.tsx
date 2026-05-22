import { colors } from "@/lib/design";

const VB_W = 510;
const VB_H = 190;

interface Props {
  title: string;
}

/**
 * Empty SVG panel — hairline frame on BG TIER 1 with axis baseline.
 * Static (no animation) per DESIGN.md skeleton rules.
 */
export function ModelingPanelSkeleton({ title }: Props) {
  return (
    <div className="px-4 py-3">
      <div className="text-xs2 uppercase tracking-label-up text-fg-secondary mb-2">
        {title}
      </div>
      <svg
        viewBox={`0 0 ${VB_W} ${VB_H}`}
        style={{ width: "100%", height: "auto" }}
        preserveAspectRatio="none"
      >
        <rect
          x={6}
          y={6}
          width={VB_W - 12}
          height={VB_H - 12}
          fill={colors.bgTier1}
          stroke={colors.borderHairline}
          strokeWidth={0.5}
        />
        <line x1={6} x2={VB_W - 6} y1={VB_H - 6} y2={VB_H - 6} stroke={colors.borderHairline} strokeWidth={0.5} />
        <text
          x={VB_W / 2}
          y={VB_H / 2}
          textAnchor="middle"
          fontSize={10}
          fill={colors.fgTertiary}
        >
          Computing…
        </text>
      </svg>
    </div>
  );
}
