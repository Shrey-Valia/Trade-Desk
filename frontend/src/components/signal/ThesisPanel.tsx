import type { SignalVerdict } from "@/types/signal";

/**
 * THESIS + SUGGESTED STRUCTURE. Two stacked hairline blocks. Both pull
 * straight from the verdict object — no UI-side narrative.
 */
export function ThesisPanel({ verdict }: { verdict: SignalVerdict }) {
  return (
    <section className="grid grid-cols-3 border-b border-hairline">
      <div className="col-span-2 border-r border-hairline px-4 py-3">
        <div className="text-tiny uppercase tracking-label-up text-fg-secondary mb-1.5">
          Thesis
        </div>
        <p className="text-body text-fg-primary leading-snug">{verdict.thesis}</p>
      </div>
      <div className="px-4 py-3">
        <div className="text-tiny uppercase tracking-label-up text-fg-secondary mb-1.5">
          Suggested structure
        </div>
        {verdict.suggested_structure ? (
          <>
            <div className="text-body text-fg-primary">{verdict.suggested_structure}</div>
            {verdict.suggested_structure_detail && (
              <div className="text-tiny text-fg-tertiary mt-1 tabular-nums">
                {verdict.suggested_structure_detail}
              </div>
            )}
          </>
        ) : (
          <div className="text-tiny text-fg-tertiary">
            No defined-risk structure recommended at this conviction level.
          </div>
        )}
      </div>
    </section>
  );
}
