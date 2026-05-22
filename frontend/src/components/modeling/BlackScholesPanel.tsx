import { useMemo, useState } from "react";
import { useStrategyPayoff } from "@/hooks/useStrategyPayoff";
import { colors } from "@/lib/design";
import { formatPrice } from "@/lib/formatters";
import { TOOLTIPS } from "@/lib/tooltips";
import { MetricCell } from "@/components/ui/MetricCell";
import type { BsResponse, StrategyType } from "@/types/bs";
import { ModelingPanelSkeleton } from "./ModelingPanelSkeleton";
import { StrategyPicker } from "./StrategyPicker";

const VB_W = 510;
const VB_H = 190;
const TOP = 8;
const BOTTOM = 178;
const LEFT_PAD = 6;
const RIGHT_PAD = 6;

interface Props {
  symbol: string;
}

/**
 * Black-Scholes panel — right half of Row E (commit 12). Expiry payoff
 * renders in FG PRIMARY 1.6px solid; current-value curve in FG SECONDARY
 * dashed; breakeven verticals in cyan dashed. Greeks split into 4 separate
 * MetricCells (Δ, Γ, Θ, V) per Pass 7 maximalist resolution.
 */
export function BlackScholesPanel({ symbol }: Props) {
  const [strategy, setStrategy] = useState<StrategyType>("long_straddle");
  const { data, isLoading, isError, error } = useStrategyPayoff(symbol, strategy);

  return (
    <div className="px-4 py-2 flex flex-col h-full min-h-0">
      <div className="flex items-center justify-between mb-2 shrink-0">
        <span className="text-xs2 uppercase tracking-label-up text-fg-secondary">
          Black-Scholes · Payoff
        </span>
        <StrategyPicker value={strategy} onChange={setStrategy} />
      </div>

      <div className="flex-1 min-h-0">
        {isLoading && <ModelingPanelSkeleton title="Black-Scholes" />}
        {isError && (
          <div className="text-tiny text-fg-secondary">
            {((error as Error)?.message ?? "").toLowerCase().includes("insufficient")
              ? "Insufficient options data to model"
              : (error as Error)?.message}
          </div>
        )}
        {data && <PayoffChart data={data} />}
      </div>
      {data && (
        <div className="shrink-0">
          <BsStats data={data} />
        </div>
      )}
    </div>
  );
}

function PayoffChart({ data }: { data: BsResponse }) {
  const { payoff_at_expiry, current_value, breakevens, unlimited_loss, unlimited_gain, edge_pnl_low, edge_pnl_high } = data;

  const { yMin, yMax, xMin, xMax } = useMemo(() => {
    const pnls = [...payoff_at_expiry.map((p) => p.pnl), ...current_value.map((p) => p.pnl)];
    const lo = Math.min(...pnls);
    const hi = Math.max(...pnls);
    const pad = (hi - lo) * 0.1 || 1;
    return {
      yMin: lo - pad,
      yMax: hi + pad,
      xMin: payoff_at_expiry[0].price,
      xMax: payoff_at_expiry[payoff_at_expiry.length - 1].price,
    };
  }, [payoff_at_expiry, current_value]);

  const xScale = (p: number) =>
    LEFT_PAD + ((p - xMin) / (xMax - xMin)) * (VB_W - LEFT_PAD - RIGHT_PAD);
  const yScale = (v: number) =>
    BOTTOM - ((v - yMin) / (yMax - yMin)) * (BOTTOM - TOP);
  const zeroY = yScale(0);

  const expiryPath = payoff_at_expiry.map((p, i) => `${i === 0 ? "M" : "L"}${xScale(p.price)},${yScale(p.pnl)}`).join(" ");
  const currentPath = current_value.map((p, i) => `${i === 0 ? "M" : "L"}${xScale(p.price)},${yScale(p.pnl)}`).join(" ");

  // Profit / loss fills under the expiry curve, clipped at y=0. 8% opacity
  // per DESIGN.md — faint enough to read as fill, not as foreground.
  const profitArea =
    `M${xScale(xMin)},${zeroY} ` +
    payoff_at_expiry
      .map((p) => `L${xScale(p.price)},${yScale(Math.max(p.pnl, 0))}`)
      .join(" ") +
    ` L${xScale(xMax)},${zeroY} Z`;
  const lossArea =
    `M${xScale(xMin)},${zeroY} ` +
    payoff_at_expiry
      .map((p) => `L${xScale(p.price)},${yScale(Math.min(p.pnl, 0))}`)
      .join(" ") +
    ` L${xScale(xMax)},${zeroY} Z`;

  return (
    <svg viewBox={`0 0 ${VB_W} ${VB_H}`} style={{ width: "100%", height: "100%" }} preserveAspectRatio="none">
      <path d={profitArea} fill={colors.bullish} opacity={0.08} />
      <path d={lossArea} fill={colors.bearish} opacity={0.08} />

      <line x1={LEFT_PAD} x2={VB_W - RIGHT_PAD} y1={zeroY} y2={zeroY} stroke={colors.fgTertiary} strokeWidth={0.5} opacity={0.6} />

      <path d={currentPath} fill="none" stroke={colors.fgSecondary} strokeWidth={1.4} strokeDasharray="3 2" opacity={0.85} />
      <path d={expiryPath} fill="none" stroke={colors.fgPrimary} strokeWidth={1.6} />

      {breakevens.map((be, i) => (
        <g key={i}>
          <line x1={xScale(be)} x2={xScale(be)} y1={TOP} y2={BOTTOM} stroke={colors.accentCyan} strokeWidth={0.6} strokeDasharray="2 2" opacity={0.85} />
          <text x={xScale(be) + 2} y={zeroY - 3} fontSize={9} fill={colors.accentCyan} fontWeight={500}>
            BE {be.toFixed(0)}
          </text>
        </g>
      ))}

      {unlimited_loss && (
        <UnlimitedEdge
          x={edge_pnl_high < edge_pnl_low ? VB_W - RIGHT_PAD - 100 : LEFT_PAD + 4}
          y={BOTTOM - 14}
          text={`↓ ${formatPrice(edge_pnl_high < edge_pnl_low ? edge_pnl_high : edge_pnl_low)} at ${formatPrice(edge_pnl_high < edge_pnl_low ? xMax : xMin)} and worsening`}
          color={colors.bearish}
        />
      )}
      {unlimited_gain && (
        <UnlimitedEdge
          x={edge_pnl_high > edge_pnl_low ? VB_W - RIGHT_PAD - 100 : LEFT_PAD + 4}
          y={TOP + 4}
          text={`↑ ${formatPrice(Math.max(edge_pnl_high, edge_pnl_low))} at ${formatPrice(edge_pnl_high > edge_pnl_low ? xMax : xMin)} and growing`}
          color={colors.bullish}
        />
      )}
    </svg>
  );
}

function UnlimitedEdge({ x, y, text, color }: { x: number; y: number; text: string; color: string }) {
  return (
    <g>
      <rect x={x - 2} y={y - 8} width={text.length * 4.2 + 4} height={11} fill={colors.bgTier1} opacity={0.85} />
      <text x={x} y={y} fontSize={9} fill={color} fontWeight={500}>
        {text}
      </text>
    </g>
  );
}

function BsStats({ data }: { data: BsResponse }) {
  const isCredit = data.cost_debit_credit < 0;
  const costLabel = isCredit ? "Credit" : "Debit";
  const costValue = formatPrice(Math.abs(data.cost_debit_credit));

  const maxGainCard = data.unlimited_gain
    ? { value: "—", sub: "unlimited beyond range" }
    : { value: data.max_gain != null ? formatPrice(data.max_gain) : "—", sub: undefined };
  const maxLossCard = data.unlimited_loss
    ? { value: "—", sub: "unlimited beyond range" }
    : { value: data.max_loss != null ? formatPrice(data.max_loss) : "—", sub: undefined };

  return (
    <div className="grid grid-cols-4 mt-3 border-t border-hairline">
      <div className="border-r border-hairline">
        <MetricCell label={costLabel} value={costValue} />
      </div>
      <div className="border-r border-hairline">
        <MetricCell label="Max Gain" value={maxGainCard.value} subContext={maxGainCard.sub} />
      </div>
      <div className="border-r border-hairline">
        <MetricCell label="Max Loss" value={maxLossCard.value} subContext={maxLossCard.sub} />
      </div>
      <MetricCell
        label="P(profit)"
        value={data.prob_profit != null ? `${(data.prob_profit * 100).toFixed(0)}%` : "—"}
      />

      <div className="border-r border-t border-hairline">
        <MetricCell
          label="Δ Delta"
          value={data.greeks.delta.toFixed(2)}
          subContext="position delta"
          tooltip={TOOLTIPS.delta}
        />
      </div>
      <div className="border-r border-t border-hairline">
        <MetricCell
          label="Γ Gamma"
          value={data.greeks.gamma.toFixed(3)}
          subContext="delta rate of change"
          tooltip={TOOLTIPS.gamma}
        />
      </div>
      <div className="border-r border-t border-hairline">
        <MetricCell
          label="Θ Theta"
          value={data.greeks.theta.toFixed(2)}
          subContext="daily decay"
          tooltip={TOOLTIPS.theta}
        />
      </div>
      <div className="border-t border-hairline">
        <MetricCell
          label="V Vega"
          value={data.greeks.vega.toFixed(2)}
          subContext="vol sensitivity"
          tooltip={TOOLTIPS.vega}
        />
      </div>
    </div>
  );
}
