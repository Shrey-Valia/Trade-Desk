import { useModelSignals } from "@/hooks/useModelSignals";
import { TOOLTIPS } from "@/lib/tooltips";
import { MetricCell } from "@/components/ui/MetricCell";
import { SkeletonCard } from "@/components/ui/SkeletonCard";
import type {
  CatboostErMove,
  LstmVolForecast,
  RfRegime,
  VolEdge,
} from "@/types/models";

// Helper: stack a definition above the per-instance interpretation/rationale
// so the tooltip is both educational AND specific to the current value.
const compose = (definition: string, instance: string | undefined): string =>
  instance ? `${definition}\n\n${instance}` : definition;

interface Props {
  symbol: string;
}

/**
 * Row D — 4 inline MetricCells, same treatment as Row C. Commit 11.
 *
 * failingBaseline=true on a cell paints its bottom border as 1px dashed
 * amber instead of the standard hairline — replaces the Phase 7.9 amber
 * card-border treatment that screamed too loudly in light theme.
 *
 * Production order: input signals on the left (LSTM, CatBoost, Regime),
 * synthesis on the right (Vol Edge).
 */
export function ModelSignalsRow({ symbol }: Props) {
  const { data, isLoading } = useModelSignals(symbol);

  const allEmpty =
    !!data &&
    !isLoading &&
    data.lstm_vol_forecast == null &&
    data.catboost_er_move == null &&
    data.rf_regime == null &&
    data.vol_edge == null;
  if (allEmpty) {
    return (
      <div className="px-4 py-3 border-b border-hairline text-tiny text-fg-secondary text-center">
        Model signals unavailable for this ticker
      </div>
    );
  }

  if (isLoading) {
    return (
      <div className="border-b border-hairline grid grid-cols-4">
        {(["LSTM · vol 7d", "CatBoost · ER", "RF · regime", "Vol Edge"]).map((label, i) => (
          <div key={label} className={i < 3 ? "border-r border-hairline" : ""}>
            <SkeletonCard label={label} />
          </div>
        ))}
      </div>
    );
  }

  return (
    <div className="border-b border-hairline grid grid-cols-4">
      <div className="border-r border-hairline">
        <LstmVolCell data={data?.lstm_vol_forecast ?? null} />
      </div>
      <div className="border-r border-hairline">
        <CatBoostCell data={data?.catboost_er_move ?? null} />
      </div>
      <div className="border-r border-hairline">
        <RegimeCell data={data?.rf_regime ?? null} />
      </div>
      <VolEdgeCell data={data?.vol_edge ?? null} />
    </div>
  );
}

const truncate = (s: string, n: number): string =>
  s.length <= n ? s : `${s.slice(0, n - 1)}…`;

function LstmVolCell({ data }: { data: LstmVolForecast | null }) {
  if (data == null) {
    return <MetricCell label="LSTM · vol 7d" value="—" subContext="insufficient data" />;
  }
  const valueText = `${data.predicted_rv_7d.toFixed(1)}%`;
  const subParts: string[] = [];
  if (data.current_iv30 != null && data.vrp_implied != null) {
    const sign = data.vrp_implied >= 0 ? "+" : "";
    subParts.push(`iv ${data.current_iv30.toFixed(1)}% · vrp ${sign}${data.vrp_implied.toFixed(1)}`);
  }
  if (!data.baseline_beaten) {
    subParts.push("fails baseline");
  }
  const sub = subParts.length ? truncate(subParts.join(" · "), 28) : truncate(data.interpretation, 28);

  return (
    <MetricCell
      label="LSTM · vol 7d"
      value={valueText}
      subContext={sub}
      tooltip={compose(TOOLTIPS.lstm_vol, data.interpretation)}
      failingBaseline={!data.baseline_beaten}
    />
  );
}

function CatBoostCell({ data }: { data: CatboostErMove | null }) {
  if (data == null) {
    return <MetricCell label="CatBoost · ER" value="—" subContext="no earnings ≤30d" />;
  }
  const untrained = data.n_training_events === 0;
  const hasIssue = !data.baseline_beaten || untrained;
  const valueText = untrained ? "—" : `±${data.value.toFixed(1)}%`;
  const subParts: string[] = [];
  if (data.implied_compare != null && !untrained) {
    subParts.push(`vs implied ${data.implied_compare.toFixed(1)}%`);
  }
  if (data.n_training_events > 0 && !data.baseline_beaten) {
    subParts.push("iterating");
  }
  const sub = subParts.length ? truncate(subParts.join(" · "), 28) : truncate(data.interpretation, 28);

  return (
    <MetricCell
      label="CatBoost · ER"
      value={valueText}
      subContext={sub}
      tooltip={compose(TOOLTIPS.catboost_er, data.interpretation)}
      failingBaseline={hasIssue}
    />
  );
}

function RegimeCell({ data }: { data: RfRegime | null }) {
  if (data == null) {
    return <MetricCell label="RF · regime" value="—" subContext="no regime data" />;
  }
  const confidencePct = Math.round(data.confidence * 100);
  const tooltipLines = data.contributing_signals.map(
    (s) => `${s.name}: ${s.value} (${s.rule})`,
  );
  const instance = ["Rule-based classification", ...tooltipLines].join("\n");
  const sub = truncate(`${confidencePct}% match · rule-based`, 28);

  return (
    <MetricCell
      label="RF · regime"
      value={data.label}
      subContext={sub}
      tooltip={compose(TOOLTIPS.rf_regime, instance)}
    />
  );
}

function VolEdgeCell({ data }: { data: VolEdge | null }) {
  if (data == null) {
    return <MetricCell label="Vol Edge" value="—" subContext="signal unavailable" />;
  }
  // Verdict color: bullish-on-vol (sell premium / pre-ER rich) = green,
  // bearish-on-vol (favor buying) = red, elevated caution = primary (amber
  // isn't exposed via valueColor — caution stays neutral here).
  const verdictColor: "primary" | "bullish" | "bearish" = (() => {
    switch (data.verdict) {
      case "favor_selling":
      case "pre_earnings_rich":
        return "bullish";
      case "favor_buying":
        return "bearish";
      default:
        return "primary";
    }
  })();

  const sub =
    data.signals_used.length > 0
      ? truncate(`via ${data.signals_used.join(" + ")}`, 28)
      : "rule-based on lstm + regime";

  return (
    <MetricCell
      label="Vol Edge"
      value={data.label}
      valueColor={verdictColor}
      subContext={sub}
      tooltip={compose(TOOLTIPS.vol_edge, data.rationale)}
    />
  );
}
