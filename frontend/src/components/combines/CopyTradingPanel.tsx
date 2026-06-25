import { useEffect, useState } from "react";

import { UIButton } from "@/components/ui/UIButton";
import { useCombines, useUpdateCopyConfig } from "@/hooks/useCombines";

/** Copy multiplier bounds — must match the backend FollowerConfig schema
 *  (routers/combines.py: ge=0.1, le=10.0). */
const MULT_MIN = 0.1;
const MULT_MAX = 10.0;

/** Clamp a free-typed multiplier into the accepted range, rounded to a
 *  sane 0.01 step. Returns null for un-parseable input so the caller can
 *  hold the previous committed value. */
function parseMultiplier(raw: string): number | null {
  const n = Number(raw);
  if (!raw.trim() || Number.isNaN(n)) return null;
  return Math.min(MULT_MAX, Math.max(MULT_MIN, Math.round(n * 100) / 100));
}

/**
 * Copy-trading controls: pick one LEAD combine and toggle which others
 * FOLLOW it (with a per-follower size multiplier). The lead's 0DTE opens
 * mirror to enabled followers — clamped to each follower's contract cap and
 * skipped if it's daily-loss-locked or failed. Applies immediately.
 *
 * Renders just the inner content (no outer border) so callers wrap it in
 * their own chrome — the Accounts page card and the Settings section both
 * reuse it.
 */
export function CopyTradingPanel() {
  const { data } = useCombines();
  const update = useUpdateCopyConfig();
  const combines = (data?.combines ?? []).filter((c) => c.status !== "archived");
  const lead = data?.copy_lead_combine_id ?? null;
  const followers = combines
    .filter((c) => c.copy_follow)
    .map((c) => ({ combine_id: c.id, multiplier: c.copy_multiplier }));
  const followerMap = new Map(followers.map((f) => [f.combine_id, f.multiplier]));

  const setLead = (id: number | null) =>
    update.mutate({
      lead_combine_id: id,
      followers: followers.filter((f) => f.combine_id !== id),
    });
  const toggleFollower = (id: number) =>
    update.mutate({
      lead_combine_id: lead,
      followers: followerMap.has(id)
        ? followers.filter((f) => f.combine_id !== id)
        : [...followers, { combine_id: id, multiplier: 1 }],
    });
  const setMultiplier = (id: number, multiplier: number) =>
    update.mutate({
      lead_combine_id: lead,
      followers: followers.map((f) =>
        f.combine_id === id ? { ...f, multiplier } : f,
      ),
    });

  const followerOptions = combines.filter((c) => c.id !== lead);

  return (
    <div className="flex flex-col gap-3">
      <div>
        <div
          className="uppercase tracking-label-up text-fg-secondary"
          style={{ fontSize: 11, letterSpacing: "0.08em" }}
        >
          Copy trading
        </div>
        <div className="text-fg-tertiary mt-0.5" style={{ fontSize: 11, lineHeight: 1.35 }}>
          Mirror the lead account&rsquo;s 0DTE opens to the followers you enable
          — each scaled by its multiplier and clamped to that account&rsquo;s
          contract cap, and skipped if it&rsquo;s daily-loss-locked or has failed.
        </div>
      </div>

      {combines.length < 2 ? (
        <div className="text-tiny text-fg-tertiary-2">
          Copy trading needs at least two combines. Start another to enable it.
        </div>
      ) : (
        <>
          <label className="flex items-center justify-between gap-3">
            <span className="text-tiny text-fg-secondary">Lead account</span>
            <select
              value={lead ?? ""}
              disabled={update.isPending}
              onChange={(e) => setLead(e.target.value ? Number(e.target.value) : null)}
              className="h-8 px-2 bg-tier-2 border border-hairline text-fg-primary text-tiny rounded-btn focus:border-amber focus:outline-none disabled:opacity-50"
              style={{ minWidth: 240 }}
            >
              <option value="">Off — no copying</option>
              {combines.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name} · {c.tier}
                </option>
              ))}
            </select>
          </label>

          {lead != null && (
            <div className="flex flex-col gap-1.5">
              <span
                className="uppercase tracking-label-up text-fg-tertiary-2"
                style={{ fontSize: 11 }}
              >
                Follower accounts
              </span>
              {followerOptions.length === 0 ? (
                <span className="text-tiny text-fg-tertiary-2">
                  No other accounts to follow.
                </span>
              ) : (
                followerOptions.map((c) => {
                  const on = followerMap.has(c.id);
                  const mult = followerMap.get(c.id) ?? 1;
                  return (
                    <div
                      key={c.id}
                      className="flex items-center justify-between gap-3 border border-hairline bg-tier-2 px-2.5 py-1.5"
                      style={{ borderRadius: 4 }}
                    >
                      <span className="text-tiny text-fg-primary truncate">
                        {c.name}{" "}
                        <span className="text-fg-tertiary-2">· {c.tier}</span>
                      </span>
                      <div className="flex items-center gap-2 shrink-0">
                        {on && (
                          <MultiplierPicker
                            value={mult}
                            cap={c.max_contracts}
                            onChange={(m) => setMultiplier(c.id, m)}
                          />
                        )}
                        <FollowToggle
                          on={on}
                          onChange={() => toggleFollower(c.id)}
                        />
                      </div>
                    </div>
                  );
                })
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
}

/**
 * Per-follower size multiplier — a free numeric input (0.1×–10.0×) applied
 * to the lead's contract count before clamping to this follower's scaling
 * cap. Commits the clamped value on blur / Enter so transient keystrokes
 * (e.g. an empty field mid-edit) don't fire a mutation; the helper line
 * shows the resulting clamped contract count for a 1-contract lead position
 * so the user sees the cap bite (`mult × N` capped at `cap`).
 */
function MultiplierPicker({
  value,
  cap,
  onChange,
}: {
  value: number;
  cap: number;
  onChange: (m: number) => void;
}) {
  const [draft, setDraft] = useState(String(value));
  // Re-sync the field when the committed value changes from elsewhere
  // (toggle off→on resets to 1, another tab edits it, etc.).
  useEffect(() => setDraft(String(value)), [value]);

  const commit = () => {
    const parsed = parseMultiplier(draft);
    if (parsed == null) {
      setDraft(String(value)); // revert un-parseable input
      return;
    }
    setDraft(String(parsed));
    if (parsed !== value) onChange(parsed);
  };

  // What a 1-contract lead leg resolves to on this follower: round the
  // scaled size (min 1 for an enabled follower) then clamp to the cap.
  const previewMult = parseMultiplier(draft) ?? value;
  const resolved = Math.min(cap, Math.max(1, Math.round(1 * previewMult)));

  return (
    <div className="flex items-center gap-1.5 shrink-0">
      <div className="flex items-center">
        <input
          type="number"
          inputMode="decimal"
          min={MULT_MIN}
          max={MULT_MAX}
          step={0.1}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onBlur={commit}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              (e.target as HTMLInputElement).blur();
            }
          }}
          aria-label="Size multiplier"
          className="h-7 w-14 px-1.5 text-right tabular-nums bg-tier-0 border border-hairline text-fg-primary focus:border-amber focus:outline-none"
          style={{ borderRadius: 4, fontSize: 12 }}
        />
        <span className="text-fg-tertiary-2 pl-0.5" style={{ fontSize: 11 }}>
          ×
        </span>
      </div>
      <span
        className="text-fg-tertiary-2 tabular-nums whitespace-nowrap"
        style={{ fontSize: 11 }}
        title={`Per lead contract → ${resolved} (capped at ${cap})`}
      >
        →&nbsp;{resolved}/c
      </span>
    </div>
  );
}

function FollowToggle({ on, onChange }: { on: boolean; onChange: () => void }) {
  return (
    <UIButton
      role="switch"
      aria-checked={on}
      onClick={onChange}
      active={on}
      size="sm"
      className="uppercase tracking-label-up min-w-[64px]"
    >
      {on ? "Following" : "Follow"}
    </UIButton>
  );
}
