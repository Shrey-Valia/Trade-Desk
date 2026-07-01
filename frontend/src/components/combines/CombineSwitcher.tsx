import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { useActivateCombine, useCombines } from "@/hooks/useCombines";

/**
 * Account switcher pill — the one way to change which combine the app is
 * pointed at (mirrors the trading terminal's header dropdown). Shows the
 * active combine; the dropdown lists every open combine with its copy-trade
 * role (L = lead, F = follower) and a "start a new combine" action.
 *
 * Switching activates via POST /api/combines/{id}/activate. Used in the
 * Dashboard, Accounts, and Journal headers so switching is consistent and
 * the cards don't each need their own button.
 */
export function CombineSwitcher({ size = "sm" }: { size?: "sm" | "md" }) {
  const { data } = useCombines();
  const activate = useActivateCombine();
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);

  const combines = data?.combines ?? [];
  const openCombines = combines.filter((c) => c.status !== "archived");
  const activeId = data?.active_combine_id ?? null;
  const leadId = data?.copy_lead_combine_id ?? null;
  const active = combines.find((c) => c.id === activeId) ?? openCombines[0];
  // Breached = balance has fallen below the MLL floor (the "blew up" signal).
  // Mirrors the terminal header's red-border treatment.
  const breached = active != null && active.balance < active.mll;
  const h = size === "md" ? "h-10" : "h-8";

  if (!data) return null;

  if (openCombines.length === 0) {
    return (
      <button
        type="button"
        onClick={() => navigate("/combines/new")}
        className={`${h} px-3 rounded-btn uppercase tracking-label-up flex items-center gap-2 bg-amber text-tier-0 hover:opacity-90`}
        style={{ fontSize: 12, fontWeight: 500 }}
      >
        + Start a combine
      </button>
    );
  }

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="listbox"
        aria-expanded={open}
        title="Switch the active combine"
        className={[
          h,
          "px-3 rounded-btn flex items-center gap-2 transition-colors",
          breached
            ? "bg-tier-2 border border-bearish text-bearish"
            : "bg-tier-2 border border-tier-3 text-fg-primary hover:bg-tier-3",
        ].join(" ")}
        style={{ fontSize: 12, fontWeight: 500 }}
      >
        <span className="uppercase tracking-label-up truncate" style={{ maxWidth: 160 }}>
          {active?.name ?? "Combine"}
        </span>
        {active && (
          <CopyRoleBadge
            isLead={active.id === leadId}
            isFollower={active.copy_follow}
          />
        )}
        <span className="text-fg-tertiary-2" style={{ fontSize: 12 }}>
          ▾
        </span>
      </button>

      {open && (
        <>
          <div className="fixed inset-0 z-20" onClick={() => setOpen(false)} aria-hidden />
          <div
            role="listbox"
            className="absolute left-0 top-full mt-1 z-30 bg-tier-2 border border-tier-3 rounded-btn overflow-hidden"
            style={{ minWidth: 300 }}
          >
            {openCombines.map((c) => {
              const isActive = c.id === activeId;
              return (
                <button
                  key={c.id}
                  type="button"
                  onClick={() => {
                    if (!isActive) activate.mutate(c.id);
                    setOpen(false);
                  }}
                  className={[
                    "w-full text-left px-3 py-2 tabular-nums",
                    isActive
                      ? "text-amber bg-tier-3"
                      : "text-fg-secondary hover:bg-tier-3 hover:text-fg-primary",
                  ].join(" ")}
                >
                  <div className="flex items-center gap-2">
                    <span className="uppercase tracking-label-up" style={{ fontSize: 12 }}>
                      {c.name}
                    </span>
                    {isActive && (
                      <span
                        className="border border-amber text-amber px-1 uppercase tracking-label-up"
                        style={{ fontSize: 11, borderRadius: 2 }}
                      >
                        active
                      </span>
                    )}
                    <StageBadge funded={c.funded} failed={c.outcome === "failed"} />
                    <CopyRoleBadge isLead={c.id === leadId} isFollower={c.copy_follow} />
                  </div>
                  <div className="text-fg-tertiary-2" style={{ fontSize: 12 }}>
                    {c.tier} · {c.account_code}
                  </div>
                </button>
              );
            })}
            <button
              type="button"
              onClick={() => {
                setOpen(false);
                navigate("/combines/new");
              }}
              className="w-full text-left px-3 py-2 text-amber hover:bg-tier-3 border-t border-tier-3 uppercase tracking-label-up"
              style={{ fontSize: 12 }}
            >
              + Start a new combine
            </button>
          </div>
        </>
      )}
    </div>
  );
}

/**
 * Lifecycle-stage chip — where the combine sits in its life:
 *   EVAL    in evaluation (neutral)
 *   FUNDED  passed → funded account (bullish green)
 *   FAILED  breached the MLL (bearish red)
 * Distinct from the amber ACTIVE (which-one-is-selected) and cyan L/F (copy).
 */
export function StageBadge({
  funded,
  failed,
}: {
  funded: boolean;
  failed: boolean;
}) {
  const base = "px-1 uppercase tracking-label-up shrink-0";
  const style = { fontSize: 11, borderRadius: 2 } as const;
  if (funded) {
    return (
      <span title="Funded account" className={`border border-bullish text-bullish ${base}`} style={style}>
        Funded
      </span>
    );
  }
  if (failed) {
    return (
      <span title="Evaluation failed — MLL breached" className={`border border-bearish text-bearish ${base}`} style={style}>
        Failed
      </span>
    );
  }
  return (
    <span title="In evaluation" className={`border border-hairline-strong text-fg-secondary ${base}`} style={style}>
      Eval
    </span>
  );
}

/**
 * Copy-trade role chip — cyan so it reads as the "copy trading" axis,
 * distinct from amber (active). Lead is filled, follower is outlined.
 */
export function CopyRoleBadge({
  isLead,
  isFollower,
}: {
  isLead: boolean;
  isFollower: boolean;
}) {
  if (isLead) {
    return (
      <span
        title="Copy-trade lead"
        className="bg-cyan text-tier-0 px-1 font-medium shrink-0"
        style={{ fontSize: 11, borderRadius: 2, lineHeight: "14px" }}
      >
        L
      </span>
    );
  }
  if (isFollower) {
    return (
      <span
        title="Copy-trade follower"
        className="border border-cyan text-cyan px-1 shrink-0"
        style={{ fontSize: 11, borderRadius: 2, lineHeight: "14px" }}
      >
        F
      </span>
    );
  }
  return null;
}
