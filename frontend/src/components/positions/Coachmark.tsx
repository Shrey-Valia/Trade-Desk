import { useEffect, useState } from "react";

import { useCoachmarks } from "@/stores/coachmarks";

type CoachmarkKey = "scrubber" | "magentaBE";

interface Props {
  hint: CoachmarkKey;
  label: string;
  body: string;
  /** Anchor side — where the coachmark sits relative to its parent. */
  side?: "top" | "bottom";
  /** Show only after this condition is true. Lets us defer a hint until
   *  the element it points at actually exists (e.g. wait for a position
   *  to be active before pointing at the scrubber). */
  enabled?: boolean;
}

/**
 * Lightweight first-run hint. Anchored absolutely inside a relatively-
 * positioned parent; auto-dismisses on outside click after a tiny delay
 * so the user can click the underlying element first.
 *
 * No multi-step tour, no overlay, no focus-trap — Phase 1 spec
 * deliberately keeps this to two coachmarks max, dismissible.
 */
export function Coachmark({ hint, label, body, side = "top", enabled = true }: Props) {
  const seen = useCoachmarks((s) => s.seen[hint]);
  const dismiss = useCoachmarks((s) => s.dismiss);
  const [armed, setArmed] = useState(false);

  // Defer mount by a tick so the chart / scrubber renders first; avoids
  // pointing at an element that hasn't laid out yet.
  useEffect(() => {
    if (seen || !enabled) return;
    const t = setTimeout(() => setArmed(true), 600);
    return () => clearTimeout(t);
  }, [seen, enabled]);

  if (seen || !enabled || !armed) return null;

  const positionClass =
    side === "top" ? "bottom-full mb-1" : "top-full mt-1";

  return (
    <div
      role="status"
      className={`absolute left-0 ${positionClass} z-30 max-w-[280px] bg-tier-1 border border-amber px-2 py-1.5`}
      style={{ borderRadius: 0 }}
    >
      <div className="flex items-start gap-2">
        <div className="flex-1 min-w-0">
          <div className="text-tiny uppercase tracking-label-up text-amber" style={{ fontSize: 9 }}>
            {label}
          </div>
          <div className="text-tiny text-fg-primary mt-0.5 leading-snug" style={{ fontSize: 10 }}>
            {body}
          </div>
        </div>
        <button
          type="button"
          onClick={() => dismiss(hint)}
          aria-label="Dismiss hint"
          className="shrink-0 text-tiny text-fg-tertiary hover:text-fg-primary leading-none -mt-px"
          style={{ fontSize: 12 }}
        >
          ×
        </button>
      </div>
    </div>
  );
}
