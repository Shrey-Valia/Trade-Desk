import { UIButton } from "@/components/ui/UIButton";
import { useCombines, useUpdateCopyConfig } from "@/hooks/useCombines";

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
          style={{ fontSize: 9, letterSpacing: "0.08em" }}
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
                style={{ fontSize: 9 }}
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

/** Per-follower size multiplier — 0.5× / 1× / 2× of the lead's contracts. */
function MultiplierPicker({
  value,
  onChange,
}: {
  value: number;
  onChange: (m: number) => void;
}) {
  return (
    <div className="flex" style={{ gap: 4 }}>
      {[0.5, 1, 2].map((m) => (
        <UIButton
          key={m}
          size="sm"
          active={value === m}
          onClick={() => onChange(m)}
          aria-pressed={value === m}
          className="min-w-[40px] tabular-nums"
        >
          {m}×
        </UIButton>
      ))}
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
