/**
 * Amber dashed banner — fires when the verdict was influenced by
 * services/mock_flow.py. Visual treatment mirrors the failingBaseline
 * MetricCell border so users recognize it as a "warning, not data" cue.
 */
export function MockFlowBanner({ sweepCount }: { sweepCount: number }) {
  return (
    <div
      role="note"
      className="border-l-2 border-amber bg-tier-1 px-3 py-2 text-xs2 text-fg-primary"
    >
      <span className="text-amber uppercase tracking-label-up text-tiny">
        Demo notice
      </span>
      <span className="ml-3">
        This verdict includes <strong>{sweepCount}</strong> simulated sweep
        prints from <code className="text-fg-secondary">services/mock_flow.py</code>.
        Real flow integration would replace this without composer changes.
      </span>
    </div>
  );
}
