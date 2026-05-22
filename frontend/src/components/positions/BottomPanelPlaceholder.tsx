import { useState } from "react";

/**
 * Bottom panel placeholder for Phase 1+ (journal + payoff curve).
 *
 * Collapsible: chevron toggles between a ~28px collapsed strip and an
 * ~140px expanded empty container. The label uses the same uppercase
 * tracked treatment as our other section headers so it sits in the
 * design system even while empty.
 */
export function BottomPanelPlaceholder() {
  const [expanded, setExpanded] = useState(true);
  return (
    <section className="border-t border-hairline bg-tier-0 shrink-0">
      <button
        type="button"
        onClick={() => setExpanded((e) => !e)}
        aria-expanded={expanded}
        className="w-full flex items-center justify-between px-4 py-1.5 hover:bg-tier-1"
      >
        <span className="text-tiny uppercase tracking-label-up text-fg-secondary">
          Journal & Payoff
        </span>
        <span className="flex items-center gap-2">
          <span className="text-tiny text-fg-tertiary normal-case">
            coming soon
          </span>
          <span aria-hidden className="text-tiny text-fg-tertiary">
            {expanded ? "▾" : "▴"}
          </span>
        </span>
      </button>
      {expanded && (
        <div
          className="flex items-center justify-center text-tiny text-fg-tertiary border-t border-hairline"
          style={{ height: 120 }}
        >
          Phase 1 — journal entry · Phase 2 — payoff curve overlay
        </div>
      )}
    </section>
  );
}
