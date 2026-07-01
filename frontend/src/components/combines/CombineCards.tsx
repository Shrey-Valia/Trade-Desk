import { useState } from "react";

import { CopyRoleBadge, StageBadge } from "@/components/combines/CombineSwitcher";
import {
  useActivateAccount,
  useArchiveCombine,
  useRenameCombine,
  useResetCombine,
} from "@/hooks/useCombines";
import type { CombineOut } from "@/types/combine";

/**
 * Responsive grid of combine ("account") cards — balance, closed P&L, MLL,
 * profit-target progress, plus rename / archive and the funded-activation
 * prompt. Switching the active combine happens via the header CombineSwitcher
 * pill, so the cards carry no "switch" button — the ACTIVE badge marks the
 * current one and L/F badges mark the copy-trade lead / followers.
 */
export function CombineCardsGrid({
  combines,
  activeCombineId,
  leadCombineId,
}: {
  combines: CombineOut[];
  activeCombineId: number | null | undefined;
  leadCombineId?: number | null;
}) {
  return (
    <div
      className="grid gap-3"
      style={{ gridTemplateColumns: "repeat(auto-fit, minmax(280px, 360px))" }}
    >
      {combines.map((c) => (
        <CombineCard
          key={c.id}
          combine={c}
          isActive={c.id === activeCombineId}
          isLead={c.id === leadCombineId}
        />
      ))}
    </div>
  );
}

function CombineCard({
  combine,
  isActive,
  isLead,
}: {
  combine: CombineOut;
  isActive: boolean;
  isLead: boolean;
}) {
  const archive = useArchiveCombine();
  const rename = useRenameCombine();
  const reset = useResetCombine();
  const activateAccount = useActivateAccount();
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(combine.name);
  const [confirmArchive, setConfirmArchive] = useState(false);
  const archived = combine.status === "archived";
  const failed = combine.outcome === "failed";

  const commitRename = () => {
    const trimmed = name.trim();
    setEditing(false);
    if (trimmed && trimmed !== combine.name) {
      rename.mutate({ id: combine.id, name: trimmed });
    } else {
      setName(combine.name);
    }
  };

  return (
    <div
      className={[
        "border bg-tier-1 flex flex-col",
        archived
          ? "border-hairline opacity-60"
          : isActive
            ? "border-amber"
            : "border-hairline-strong",
      ].join(" ")}
      style={{ borderRadius: 4 }}
    >
      <div className="px-3 pt-2.5 pb-2 border-b border-hairline">
        <div className="flex items-center gap-2">
          {editing ? (
            <input
              type="text"
              value={name}
              autoFocus
              maxLength={64}
              onChange={(e) => setName(e.target.value)}
              onBlur={commitRename}
              onKeyDown={(e) => {
                if (e.key === "Enter") (e.target as HTMLInputElement).blur();
                if (e.key === "Escape") {
                  setName(combine.name);
                  setEditing(false);
                }
              }}
              className="flex-1 h-6 px-1.5 bg-tier-2 border border-tier-3 text-fg-primary focus:border-amber focus:outline-none rounded-btn"
              style={{ fontSize: 12 }}
            />
          ) : (
            <button
              type="button"
              onClick={() => !archived && setEditing(true)}
              title={archived ? undefined : "Rename"}
              className="text-fg-primary font-medium truncate text-left hover:text-fg-secondary"
              style={{ fontSize: 13 }}
            >
              {combine.name}
            </button>
          )}
          {isActive && !archived && (
            <span
              className="border border-hairline-strong text-fg-secondary px-1 uppercase tracking-label-up shrink-0"
              style={{ fontSize: 11, borderRadius: 2 }}
            >
              active
            </span>
          )}
          {archived && (
            <span
              className="border border-tier-3 text-fg-tertiary-2 px-1 uppercase tracking-label-up shrink-0"
              style={{ fontSize: 11, borderRadius: 2 }}
            >
              archived
            </span>
          )}
          {!archived && <StageBadge funded={combine.funded} failed={failed} />}
          <CopyRoleBadge isLead={isLead} isFollower={combine.copy_follow} />
        </div>
        <div
          className="text-fg-tertiary-2 tabular-nums mt-0.5"
          style={{ fontSize: 12 }}
        >
          {combine.tier} · {combine.account_code}
        </div>
      </div>
      <div className="px-3 py-2 flex flex-col gap-1 tabular-nums flex-1">
        <CardRow label="Balance" value={formatDollar(combine.balance)} />
        <CardRow
          label="Closed P&L"
          value={formatSigned(combine.realized_pnl)}
          tone={
            combine.realized_pnl > 0
              ? "bullish"
              : combine.realized_pnl < 0
                ? "bearish"
                : undefined
          }
        />
        <CardRow label="MLL" value={formatDollar(combine.mll)} />
        {combine.funded && combine.activation_required && (
          <div className="flex items-center justify-between gap-2">
            <span
              className="uppercase tracking-label-up text-fg-tertiary-2"
              style={{ fontSize: 11 }}
            >
              Payouts
            </span>
            <button
              type="button"
              disabled={activateAccount.isPending}
              onClick={() => activateAccount.mutate(combine.id)}
              title={
                combine.activation_fee > 0
                  ? `Activate this funded account — a one-time $${combine.activation_fee} fee unlocks payouts (simulated).`
                  : "Activate this funded account — free on the no-activation plan — to unlock payouts."
              }
              className="h-5 px-1.5 text-tiny uppercase tracking-label-up border border-hairline-strong text-fg-primary hover:bg-tier-2 hover:border-hairline disabled:opacity-50"
              style={{ borderRadius: 0, fontSize: 11 }}
            >
              {activateAccount.isPending
                ? "…"
                : combine.activation_fee > 0
                  ? `Activate $${combine.activation_fee}`
                  : "Activate (free)"}
            </button>
          </div>
        )}
        {combine.funded && !combine.activation_required && (
          <CardRow
            label="Payout avail."
            value={formatDollar(combine.payout_eligible)}
            tone={combine.payout_eligible > 0 ? "bullish" : undefined}
          />
        )}
        <div className="mt-1">
          <ProgressBar
            fraction={combine.objective_progress}
            tone={combine.objective_progress >= 1 ? "bullish" : "amber"}
          />
          <span className="text-tiny text-fg-tertiary-2" style={{ fontSize: 11 }}>
            {Math.round(combine.objective_progress * 100)}% of $
            {combine.profit_target.toLocaleString()} target
          </span>
        </div>
      </div>
      {!archived && (
        <div className="px-3 pb-2.5 flex items-center gap-2">
          {failed && (
            <button
              type="button"
              disabled={reset.isPending}
              onClick={() => reset.mutate(combine.id)}
              title="Restart the evaluation. Trade history is kept; the eval P&L starts fresh."
              className="h-6 px-2 text-tiny uppercase tracking-label-up border border-bullish text-bullish hover:bg-tier-2 disabled:opacity-50"
              style={{ borderRadius: 0 }}
            >
              Reset
            </button>
          )}
          <div className="ml-auto">
            {confirmArchive ? (
              <span className="flex items-center gap-2">
                <span className="text-tiny text-fg-tertiary-2">sure?</span>
                <button
                  type="button"
                  disabled={archive.isPending}
                  onClick={() => archive.mutate(combine.id)}
                  className="h-6 px-2 text-tiny uppercase tracking-label-up border border-bearish text-bearish hover:bg-tier-2"
                  style={{ borderRadius: 0 }}
                >
                  Archive
                </button>
                <button
                  type="button"
                  onClick={() => setConfirmArchive(false)}
                  className="text-tiny text-fg-tertiary-2 hover:text-fg-primary"
                >
                  cancel
                </button>
              </span>
            ) : (
              <button
                type="button"
                onClick={() => setConfirmArchive(true)}
                title="Frees a combine slot. History is kept; archived combines can't trade."
                className="h-6 px-2 text-tiny uppercase tracking-label-up text-fg-tertiary-2 hover:text-bearish"
              >
                Archive
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function CardRow({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone?: "bullish" | "bearish";
}) {
  const cls =
    tone === "bullish"
      ? "text-bullish"
      : tone === "bearish"
        ? "text-bearish"
        : "text-fg-secondary";
  return (
    <div className="flex items-baseline justify-between">
      <span
        className="uppercase tracking-label-up text-fg-tertiary-2"
        style={{ fontSize: 11 }}
      >
        {label}
      </span>
      <span className={`text-tiny ${cls}`}>{value}</span>
    </div>
  );
}

function ProgressBar({
  fraction,
  tone,
}: {
  fraction: number;
  tone: "amber" | "bullish";
}) {
  const pct = Math.max(0, Math.min(1, fraction)) * 100;
  return (
    <div className="h-1.5 bg-tier-2 relative">
      <div
        className={`absolute inset-y-0 left-0 ${tone === "bullish" ? "bg-bullish" : "bg-amber"}`}
        style={{ width: `${pct}%` }}
      />
    </div>
  );
}

function formatDollar(v: number): string {
  if (!Number.isFinite(v)) return "—";
  return `$${v.toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

function formatSigned(v: number): string {
  if (!Number.isFinite(v)) return "$0.00";
  const sign = v > 0 ? "+" : v < 0 ? "−" : "";
  return `${sign}$${Math.abs(v).toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}
