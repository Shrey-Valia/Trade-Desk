import { useMemo } from "react";
import { useMonteCarlo } from "@/hooks/useMonteCarlo";
import { colors } from "@/lib/design";
import { formatPrice } from "@/lib/formatters";
import { MetricCell } from "@/components/ui/MetricCell";
import { ModelingPanelSkeleton } from "./ModelingPanelSkeleton";
import type { McResponse } from "@/types/mc";

const VB_W = 510;
const VB_H = 190;
const PRICE_TOP = 8;
const PRICE_BOTTOM = 178;
const LEFT_PAD = 6;
const RIGHT_PAD = 70;
const GLYPH_FONT = 9;

interface Props {
  symbol: string;
}

/**
 * Monte Carlo panel — left half of Row E (commit 12). Sample paths render
 * in FG TERTIARY at 0.3 opacity (neutral noise floor), median in FG PRIMARY
 * 1.6px (the read), inner cone faint cyan at 15% / outer cone faint cyan
 * at 8% (anchor + envelope). Probability labels at right edge use the
 * LabelGlyph treatment (text only, no pill). Cyan reads as "neutral but
 * important" — the right semantic for a probability distribution.
 */
export function MonteCarloPanel({ symbol }: Props) {
  const { data, isLoading, isError, error } = useMonteCarlo(symbol);

  if (isLoading) {
    return <ModelingPanelSkeleton title="Monte Carlo" />;
  }
  if (isError || !data) {
    const msg = (error as Error)?.message ?? "Failed to load MC";
    const insufficient = msg.toLowerCase().includes("insufficient");
    return (
      <div className="px-4 py-3 text-tiny text-fg-secondary text-center">
        {insufficient ? "Insufficient options data to model" : msg}
      </div>
    );
  }

  return (
    <div className="px-4 py-2 flex flex-col h-full min-h-0">
      <div className="flex items-baseline justify-between mb-2 shrink-0">
        <span className="text-xs2 uppercase tracking-label-up text-fg-secondary">
          Monte Carlo · {data.horizon_days}d · {data.n_paths.toLocaleString()} paths
        </span>
        <span className="text-tiny text-fg-tertiary">
          σ = {(data.sigma * 100).toFixed(1)}%
        </span>
      </div>
      <div className="flex-1 min-h-0">
        <McFanChart data={data} />
      </div>
      <div className="shrink-0">
        <McStats data={data} />
      </div>
    </div>
  );
}

function McFanChart({ data }: { data: McResponse }) {
  const { sample_paths, bands, probabilities, spot } = data;
  const nSteps = sample_paths[0]?.length ?? 0;

  const { yMin, yMax } = useMemo(() => {
    const all: number[] = [];
    sample_paths.forEach((p) => p.forEach((v) => all.push(v)));
    probabilities.forEach((pr) => all.push(pr.level));
    all.push(spot);
    const min = Math.min(...all);
    const max = Math.max(...all);
    const pad = (max - min) * 0.05 || 1;
    return { yMin: min - pad, yMax: max + pad };
  }, [sample_paths, probabilities, spot]);

  const xScale = (i: number) =>
    LEFT_PAD + (i * (VB_W - LEFT_PAD - RIGHT_PAD)) / Math.max(nSteps - 1, 1);
  const yPrice = (p: number) =>
    PRICE_BOTTOM - ((p - yMin) / (yMax - yMin)) * (PRICE_BOTTOM - PRICE_TOP);

  const cone = (loSeries: number[], hiSeries: number[]) => {
    const top = loSeries.map((v, i) => `${xScale(i)},${yPrice(v)}`).join(" ");
    const bot = hiSeries.map((v, i) => `${xScale(i)},${yPrice(v)}`).reverse().join(" ");
    return `${top} ${bot}`;
  };

  return (
    <svg viewBox={`0 0 ${VB_W} ${VB_H}`} style={{ width: "100%", height: "100%" }} preserveAspectRatio="none">
      {bands["10"] && bands["90"] && (
        <polygon points={cone(bands["10"], bands["90"])} fill={colors.accentCyan} opacity={0.08} />
      )}
      {bands["25"] && bands["75"] && (
        <polygon points={cone(bands["25"], bands["75"])} fill={colors.accentCyan} opacity={0.15} />
      )}

      {sample_paths.map((path, i) => (
        <polyline
          key={i}
          points={path.map((v, j) => `${xScale(j)},${yPrice(v)}`).join(" ")}
          fill="none"
          stroke={colors.fgTertiary}
          strokeWidth={0.4}
          opacity={0.3}
        />
      ))}

      {bands["50"] && (
        <polyline
          points={bands["50"].map((v, i) => `${xScale(i)},${yPrice(v)}`).join(" ")}
          fill="none"
          stroke={colors.fgPrimary}
          strokeWidth={1.6}
        />
      )}

      {probabilities.map((p) => {
        const y = yPrice(p.level);
        return (
          <g key={p.label}>
            <line
              x1={LEFT_PAD}
              x2={VB_W - RIGHT_PAD}
              y1={y}
              y2={y}
              stroke={colors.fgTertiary}
              strokeWidth={0.4}
              strokeDasharray="2 2"
              opacity={0.55}
            />
            <text
              x={VB_W - 4}
              y={y + 3}
              fontSize={GLYPH_FONT}
              fill={colors.fgSecondary}
              textAnchor="end"
              fontWeight={500}
            >
              {p.label} · {(p.prob_touch * 100).toFixed(0)}%
            </text>
          </g>
        );
      })}

      {/* Spot marker on left edge — small cyan tick (structural reference, not warning) */}
      <circle cx={LEFT_PAD} cy={yPrice(spot)} r={1.8} fill={colors.accentCyan} />
    </svg>
  );
}

function McStats({ data }: { data: McResponse }) {
  const upperEm = data.probabilities.find((p) => p.label.startsWith("+1σ"));
  const lowerEm = data.probabilities.find((p) => p.label.startsWith("−1σ"));
  const callWall = data.probabilities.find((p) => p.label.startsWith("call wall"));

  return (
    <div className="grid grid-cols-5 mt-3 border-t border-hairline">
      <div className="border-r border-hairline">
        <MetricCell label="Mean Close" value={formatPrice(data.mean_close)} />
      </div>
      <div className="border-r border-hairline">
        <MetricCell
          label="95% Range"
          value={`${formatPrice(data.ci_95[0])} – ${formatPrice(data.ci_95[1])}`}
        />
      </div>
      <div className="border-r border-hairline">
        <MetricCell
          label="P(>+1σ)"
          value={upperEm ? `${(upperEm.prob_close_above * 100).toFixed(0)}%` : "—"}
        />
      </div>
      <div className="border-r border-hairline">
        <MetricCell
          label="P(>Call Wall)"
          value={callWall ? `${(callWall.prob_close_above * 100).toFixed(0)}%` : "—"}
        />
      </div>
      <MetricCell
        label="P(<−1σ)"
        value={lowerEm ? `${((1 - lowerEm.prob_close_above) * 100).toFixed(0)}%` : "—"}
      />
    </div>
  );
}
