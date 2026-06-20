import { Coachmark } from "@/components/positions/Coachmark";
import { useChartPrefs } from "@/stores/chartPrefs";

interface Entry {
  label: string;
  meaning: string;
  swatch: { color: string; style: "solid" | "dashed" | "dotted" | "arrow" };
}

const POSITION_ENTRIES: Entry[] = [
  {
    label: "BE",
    meaning: "Position breakeven (today)",
    swatch: { color: "#D4537E", style: "solid" },
  },
  {
    label: "BE✕",
    meaning: "Position breakeven (expiration)",
    swatch: { color: "#D4537E", style: "dotted" },
  },
  {
    label: "▲",
    meaning: "Entry price + date",
    swatch: { color: "#D4537E", style: "arrow" },
  },
];

const MARKET_ENTRIES: Entry[] = [
  { label: "EM±", meaning: "Expected move", swatch: { color: "#F0A030", style: "dashed" } },
  { label: "CW",  meaning: "Call wall",     swatch: { color: "#E85C5C", style: "solid" } },
  { label: "PW",  meaning: "Put wall",      swatch: { color: "#4DD17C", style: "solid" } },
  { label: "MP",  meaning: "Max pain",      swatch: { color: "#4FB8C8", style: "dashed" } },
  { label: "GF",  meaning: "Gamma flip",    swatch: { color: "#4FB8C8", style: "dashed" } },
];

/**
 * Chart legend overlay. Compact, dismissible, hairline-bordered.
 *
 * Lives in the top-left corner of the price chart so the right-axis
 * price labels stay readable. Two sections: position-level (magenta —
 * "MY POSITION") and market-level (the existing 6 annotations).
 *
 * The market-annotation toggle here drives the same store the
 * AnnotatedChart reads; hiding annotations from the legend hides them
 * on the chart simultaneously.
 */
export function ChartLegend({ hasActivePosition }: { hasActivePosition: boolean }) {
  const showLegend = useChartPrefs((s) => s.showLegend);
  const showMarketAnnotations = useChartPrefs((s) => s.showMarketAnnotations);
  const toggleMarketAnnotations = useChartPrefs((s) => s.toggleMarketAnnotations);
  const setShowLegend = useChartPrefs((s) => s.setShowLegend);

  if (!showLegend) {
    return (
      <button
        type="button"
        onClick={() => setShowLegend(true)}
        className="absolute top-2 left-2 z-10 text-tiny uppercase tracking-label-up text-fg-tertiary hover:text-fg-primary bg-tier-1/90 border border-hairline px-1.5 py-0.5"
        title="Show chart legend"
        style={{ borderRadius: 0 }}
      >
        Legend
      </button>
    );
  }

  return (
    <div
      className="absolute top-2 left-2 z-10 bg-tier-1/90 border border-hairline backdrop-blur-sm"
      style={{ borderRadius: 0, minWidth: 196 }}
    >
      <header className="flex items-center justify-between border-b border-hairline px-2 py-1">
        <span className="text-tiny uppercase tracking-label-up text-fg-secondary">
          Legend
        </span>
        <button
          type="button"
          onClick={() => setShowLegend(false)}
          aria-label="Hide legend"
          className="text-tiny text-fg-tertiary hover:text-fg-primary leading-none"
          style={{ fontSize: 11 }}
        >
          ×
        </button>
      </header>
      {hasActivePosition && (
        <div className="relative px-2 py-1.5 border-b border-hairline">
          <Coachmark
            hint="magentaBE"
            label="Your position"
            body="Magenta solid is your breakeven recomputed at today's time-to-expiry. The dotted line is the breakeven at expiration."
            side="bottom"
            enabled={hasActivePosition}
          />
          <div className="text-tiny uppercase tracking-label-up text-fg-tertiary mb-0.5"
               style={{ fontSize: 11 }}>
            My position
          </div>
          {POSITION_ENTRIES.map((e) => (
            <LegendRow key={e.label} entry={e} />
          ))}
        </div>
      )}
      <div className="px-2 py-1.5">
        <div className="flex items-center justify-between mb-0.5">
          <span
            className="text-tiny uppercase tracking-label-up text-fg-tertiary"
            style={{ fontSize: 11 }}
          >
            Market structure
          </span>
          <button
            type="button"
            onClick={toggleMarketAnnotations}
            className={[
              "text-tiny uppercase tracking-label-up px-1",
              showMarketAnnotations
                ? "text-amber"
                : "text-fg-tertiary hover:text-fg-primary",
            ].join(" ")}
            title={showMarketAnnotations ? "Hide annotations" : "Show annotations"}
            style={{ fontSize: 11 }}
          >
            {showMarketAnnotations ? "ON" : "OFF"}
          </button>
        </div>
        {MARKET_ENTRIES.map((e) => (
          <LegendRow
            key={e.label}
            entry={e}
            dimmed={!showMarketAnnotations}
          />
        ))}
      </div>
    </div>
  );
}

function LegendRow({ entry, dimmed }: { entry: Entry; dimmed?: boolean }) {
  return (
    <div className={`flex items-center gap-2 py-px ${dimmed ? "opacity-40" : ""}`}>
      <Swatch color={entry.swatch.color} style={entry.swatch.style} />
      <span
        className="text-tiny text-fg-primary tabular-nums"
        style={{ fontSize: 12, minWidth: 24 }}
      >
        {entry.label}
      </span>
      <span className="text-tiny text-fg-tertiary" style={{ fontSize: 12 }}>
        {entry.meaning}
      </span>
    </div>
  );
}

function Swatch({
  color,
  style,
}: {
  color: string;
  style: "solid" | "dashed" | "dotted" | "arrow";
}) {
  if (style === "arrow") {
    return (
      <span
        aria-hidden
        className="inline-block"
        style={{ width: 16, color, fontSize: 11, lineHeight: 1, textAlign: "center" }}
      >
        ▲
      </span>
    );
  }
  // Use border-bottom of an inline element to render a line swatch in
  // the requested style — no SVG needed for the legend.
  const borderStyle =
    style === "solid" ? "solid" : style === "dashed" ? "dashed" : "dotted";
  return (
    <span
      aria-hidden
      className="inline-block"
      style={{
        width: 16,
        height: 0,
        borderBottomWidth: 2,
        borderBottomStyle: borderStyle,
        borderBottomColor: color,
      }}
    />
  );
}
