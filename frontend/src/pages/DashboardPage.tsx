import { useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { EquityCurveSvg } from "@/components/analytics/EquityCurveSvg";
import { PageHeader } from "@/components/layout/PageHeader";
import { MetricPill } from "@/components/ui/MetricPill";
import { useAccountState } from "@/hooks/useAccountState";
import {
  useActivateCombine,
  useArchiveCombine,
  useCombines,
  useRenameCombine,
} from "@/hooks/useCombines";
import { useJournalAnalytics } from "@/hooks/useJournalAnalytics";
import type { CombineOut } from "@/types/combine";

/**
 * /dashboard — the prop-firm management home (Topstep-style).
 *
 * (This file previously held the retired Analysis-mode dashboard — a
 * thin CalendarStrip/WatchlistColumn/StockDetailView composition; those
 * components remain on disk, and the old composition lives in git.)
 *
 * Top: active-combine summary pills + Start a Trading Combine CTA.
 * Middle: account balance over time (closed-trade equity offset to
 * absolute balance) + performance tracker, with the Path to Funding
 * objectives rail on the right. Bottom: every owned combine as a
 * managed card (activate / rename / archive).
 *
 * Everything here is display + management; rule numbers come from the
 * same computed account-state/combines payloads the terminal header
 * uses. Objectives are display-only — nothing settles a combine yet.
 */
export function DashboardPage() {
  const combines = useCombines();
  const hasAny = (combines.data?.combines.length ?? 0) > 0;

  return (
    <div className="flex flex-col h-full min-h-0 bg-tier-0">
      <PageHeader
        title="Dashboard"
        subtitle={
          combines.data
            ? `${combines.data.slots_used} of ${combines.data.slots_total} combine slots used`
            : undefined
        }
      />
      <main className="flex-1 min-h-0 overflow-y-auto border-t border-hairline">
        {combines.isPending ? (
          <div className="px-4 py-6 text-tiny text-fg-tertiary-2">
            Loading combines…
          </div>
        ) : !hasAny ? (
          <FirstCombineHero />
        ) : (
          <DashboardBody />
        )}
      </main>
    </div>
  );
}

function FirstCombineHero() {
  return (
    <div className="h-full flex flex-col items-center justify-center gap-3 px-6 text-center">
      <span
        className="uppercase tracking-label-up text-fg-secondary"
        style={{ fontSize: 9, letterSpacing: "0.08em" }}
      >
        No combines yet
      </span>
      <span className="text-display font-medium text-fg-primary">
        Start your first Trading Combine.
      </span>
      <span className="text-tiny text-fg-tertiary max-w-md leading-relaxed">
        Pick an account size, trade 0DTE options within the loss limits, and
        work toward the profit target. Your dashboard tracks every rule live.
      </span>
      <Link
        to="/combines/new"
        className="mt-2 h-9 px-4 inline-flex items-center uppercase tracking-label-up border border-amber text-amber bg-tier-1 hover:bg-tier-2 font-medium"
        style={{ fontSize: 12, borderRadius: 0 }}
      >
        Start a Trading Combine →
      </Link>
    </div>
  );
}

function DashboardBody() {
  const { data: account } = useAccountState();
  const activeCombineId = account?.combine_id ?? null;
  const analytics = useJournalAnalytics(
    activeCombineId != null ? { combineId: activeCombineId } : {},
  );

  return (
    <div className="p-3.5 flex flex-col gap-3.5">
      {/* Top strip: active combine identity + CTAs */}
      <div className="flex items-center gap-3 flex-wrap">
        {account && (
          <>
            <MetricPill label="BAL" value={formatDollar(account.balance)} />
            <MetricPill
              label="CLOSED P&L"
              value={formatSigned(account.realized_pnl)}
              signed={account.realized_pnl}
            />
            <MetricPill label="MLL" value={formatDollar(account.mll)} />
            <MetricPill
              label="DLL"
              value={`${formatDollar(account.dll_used)} / ${formatDollar(account.dll_budget)}`}
              tone={account.dll_breached ? "bearish" : "default"}
            />
          </>
        )}
        <div className="ml-auto flex items-center gap-2">
          <Link
            to="/positions"
            className="h-8 px-3 inline-flex items-center text-tiny uppercase tracking-label-up border border-hairline text-fg-secondary hover:bg-tier-2 hover:text-fg-primary"
            style={{ borderRadius: 0 }}
          >
            Launch terminal →
          </Link>
          <Link
            to="/combines/new"
            className="h-8 px-3 inline-flex items-center text-tiny uppercase tracking-label-up border border-amber text-amber bg-tier-1 hover:bg-tier-2 font-medium"
            style={{ borderRadius: 0 }}
          >
            Start a Trading Combine
          </Link>
        </div>
      </div>

      {/* Middle: balance curve + perf | path to funding */}
      <div className="grid gap-3.5 items-start" style={{ gridTemplateColumns: "2fr 1fr" }}>
        <div className="flex flex-col gap-3.5 min-w-0">
          <BalancePanel
            startingBalance={account?.starting_balance ?? 0}
            combineName={account?.combine_name}
            analytics={analytics}
          />
          <PerformancePanel analytics={analytics} />
        </div>
        <PathToFunding />
      </div>

      <CombineCards />
    </div>
  );
}

// -- balance over time ---------------------------------------------------------

function BalancePanel({
  startingBalance,
  combineName,
  analytics,
}: {
  startingBalance: number;
  combineName: string | undefined;
  analytics: ReturnType<typeof useJournalAnalytics>;
}) {
  const equity = analytics.data?.equity;
  // The equity curve is cumulative closed P&L; offset by the combine's
  // starting balance so the chart reads as account balance.
  const points = useMemo(
    () =>
      (equity?.points ?? []).map((p) => ({
        date: p.date,
        cumulative_pnl: startingBalance + p.cumulative_pnl,
      })),
    [equity, startingBalance],
  );

  return (
    <Panel
      title="Account balance over time"
      right={combineName ? `${combineName} · closed trades` : ""}
    >
      {points.length >= 2 ? (
        <div style={{ height: 220 }}>
          <EquityCurveSvg
            points={points}
            drawdownPeakDate={equity?.drawdown_peak_date}
            drawdownTroughDate={equity?.drawdown_trough_date}
          />
        </div>
      ) : (
        <div
          className="flex items-center justify-center text-tiny text-fg-tertiary-2"
          style={{ height: 220 }}
        >
          {analytics.isPending
            ? "Loading…"
            : "The balance curve appears after your first two closed trades."}
        </div>
      )}
    </Panel>
  );
}

// -- performance tracker --------------------------------------------------------

function PerformancePanel({
  analytics,
}: {
  analytics: ReturnType<typeof useJournalAnalytics>;
}) {
  const k = analytics.data?.kpis;
  return (
    <Panel title="Performance tracker" right="closed trades on this combine">
      <div className="grid grid-cols-4 gap-3">
        <Stat
          label="Win rate"
          value={k?.win_rate != null ? `${Math.round(k.win_rate * 100)}%` : "—"}
          sub={k ? `${k.closed_trades} closed` : undefined}
        />
        <Stat
          label="Avg winning trade"
          value={k?.avg_winner != null ? formatDollar(k.avg_winner) : "—"}
          tone="bullish"
        />
        <Stat
          label="Avg losing trade"
          value={k?.avg_loser != null ? formatDollar(Math.abs(k.avg_loser)) : "—"}
          tone="bearish"
        />
        <Stat
          label="Avg hold"
          value={k?.avg_hold_min != null ? formatMinutes(k.avg_hold_min) : "—"}
        />
      </div>
    </Panel>
  );
}

function Stat({
  label,
  value,
  sub,
  tone,
}: {
  label: string;
  value: string;
  sub?: string;
  tone?: "bullish" | "bearish";
}) {
  const cls =
    tone === "bullish"
      ? "text-bullish"
      : tone === "bearish"
        ? "text-bearish"
        : "text-fg-primary";
  return (
    <div className="flex flex-col gap-0.5">
      <span
        className="uppercase tracking-label-up text-fg-tertiary-2"
        style={{ fontSize: 9 }}
      >
        {label}
      </span>
      <span className={`text-large font-medium tabular-nums ${cls}`}>{value}</span>
      {sub && (
        <span className="text-tiny text-fg-tertiary-2 tabular-nums">{sub}</span>
      )}
    </div>
  );
}

// -- path to funding -------------------------------------------------------------

function PathToFunding() {
  const { data: account } = useAccountState();
  if (!account) return null;
  const target = account.profit_target ?? 0;
  const progress = account.objective_progress ?? 0;
  const cushion = account.balance - account.mll;
  const dllRemaining = Math.max(0, account.dll_budget - account.dll_used);

  return (
    <Panel title="Path to funding" right={account.account_code ?? ""}>
      <div className="flex flex-col gap-3">
        {/* Objective: profit target */}
        <div className="flex flex-col gap-1">
          <div className="flex items-baseline justify-between">
            <span
              className="uppercase tracking-label-up text-fg-secondary"
              style={{ fontSize: 10 }}
            >
              Profit target
            </span>
            <span className="text-tiny tabular-nums text-fg-secondary">
              {formatSigned(account.realized_pnl)} / ${target.toLocaleString()}
            </span>
          </div>
          <ProgressBar
            fraction={progress}
            tone={progress >= 1 ? "bullish" : "amber"}
          />
          <span className="text-tiny text-fg-tertiary-2">
            {progress >= 1
              ? "Target reached — evaluation review is a manual step for now."
              : `${Math.round(progress * 100)}% of the way there.`}
          </span>
        </div>

        <div className="border-t border-hairline" />

        <RuleRow
          label="Maximum loss limit"
          value={formatDollar(account.mll)}
          status={
            account.balance < account.mll
              ? { text: "BREACHED", tone: "bearish" }
              : {
                  text: `$${Math.round(cushion).toLocaleString()} cushion`,
                  tone: "ok",
                }
          }
          hint="Trails your high-water mark; capped at the starting balance."
        />
        <RuleRow
          label="Daily loss limit"
          value={`${formatDollar(dllRemaining)} left today`}
          status={
            account.dll_breached
              ? { text: "HIT TODAY", tone: "bearish" }
              : { text: "ok", tone: "ok" }
          }
          hint="Resets at the next ET trading day. Display-only."
        />

        <div className="border-t border-hairline" />
        <span className="text-tiny text-fg-tertiary leading-relaxed">
          Rules are computed from closed trades — the same numbers as the
          terminal header. Pass/fail settlement is not automated yet;
          objectives here are your scoreboard.
        </span>
      </div>
    </Panel>
  );
}

function RuleRow({
  label,
  value,
  status,
  hint,
}: {
  label: string;
  value: string;
  status: { text: string; tone: "ok" | "bearish" };
  hint: string;
}) {
  return (
    <div className="flex flex-col gap-0.5">
      <div className="flex items-baseline justify-between gap-2">
        <span
          className="uppercase tracking-label-up text-fg-secondary"
          style={{ fontSize: 10 }}
        >
          {label}
        </span>
        <span
          className={`text-tiny uppercase tracking-label-up ${
            status.tone === "bearish" ? "text-bearish" : "text-bullish"
          }`}
          style={{ fontSize: 9 }}
        >
          {status.text}
        </span>
      </div>
      <span className="text-tiny tabular-nums text-fg-primary">{value}</span>
      <span className="text-tiny text-fg-tertiary-2" style={{ fontSize: 10 }}>
        {hint}
      </span>
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
    <div
      className="h-1.5 bg-tier-2 relative"
      role="progressbar"
      aria-valuenow={Math.round(pct)}
      aria-valuemin={0}
      aria-valuemax={100}
    >
      <div
        className={`absolute inset-y-0 left-0 ${tone === "bullish" ? "bg-bullish" : "bg-amber"}`}
        style={{ width: `${pct}%` }}
      />
    </div>
  );
}

// -- combine cards -----------------------------------------------------------------

function CombineCards() {
  const { data } = useCombines();
  const combines = data?.combines ?? [];
  if (combines.length === 0) return null;
  return (
    <Panel
      title="Your combines"
      right={`${data?.slots_used ?? 0} of ${data?.slots_total ?? 5} slots used`}
    >
      <div
        className="grid gap-3"
        style={{ gridTemplateColumns: "repeat(3, minmax(0, 1fr))" }}
      >
        {combines.map((c) => (
          <CombineCard
            key={c.id}
            combine={c}
            isActive={c.id === data?.active_combine_id}
          />
        ))}
      </div>
    </Panel>
  );
}

function CombineCard({
  combine,
  isActive,
}: {
  combine: CombineOut;
  isActive: boolean;
}) {
  const activate = useActivateCombine();
  const archive = useArchiveCombine();
  const rename = useRenameCombine();
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(combine.name);
  const [confirmArchive, setConfirmArchive] = useState(false);
  const archived = combine.status === "archived";

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
              className="text-fg-primary font-medium truncate text-left hover:text-amber"
              style={{ fontSize: 13 }}
            >
              {combine.name}
            </button>
          )}
          {isActive && !archived && (
            <span
              className="border border-amber text-amber px-1 uppercase tracking-label-up shrink-0"
              style={{ fontSize: 8, borderRadius: 2 }}
            >
              active
            </span>
          )}
          {archived && (
            <span
              className="border border-tier-3 text-fg-tertiary-2 px-1 uppercase tracking-label-up shrink-0"
              style={{ fontSize: 8, borderRadius: 2 }}
            >
              archived
            </span>
          )}
        </div>
        <div
          className="text-fg-tertiary-2 tabular-nums mt-0.5"
          style={{ fontSize: 10 }}
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
        <div className="mt-1">
          <ProgressBar
            fraction={combine.objective_progress}
            tone={combine.objective_progress >= 1 ? "bullish" : "amber"}
          />
          <span className="text-tiny text-fg-tertiary-2" style={{ fontSize: 9 }}>
            {Math.round(combine.objective_progress * 100)}% of $
            {combine.profit_target.toLocaleString()} target
          </span>
        </div>
      </div>
      {!archived && (
        <div className="px-3 pb-2.5 flex items-center gap-2">
          {!isActive && (
            <button
              type="button"
              disabled={activate.isPending}
              onClick={() => activate.mutate(combine.id)}
              className="h-6 px-2 text-tiny uppercase tracking-label-up border border-amber text-amber hover:bg-tier-2 disabled:opacity-50"
              style={{ borderRadius: 0 }}
            >
              Activate
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
        style={{ fontSize: 9 }}
      >
        {label}
      </span>
      <span className={`text-tiny ${cls}`}>{value}</span>
    </div>
  );
}

// -- shared -------------------------------------------------------------------

function Panel({
  title,
  right,
  children,
}: {
  title: string;
  right?: string;
  children: React.ReactNode;
}) {
  return (
    <div
      className="border border-hairline-strong bg-tier-1"
      style={{ borderRadius: 4 }}
    >
      <div className="flex items-baseline justify-between px-3 py-1.5 border-b border-hairline">
        <span className="text-tiny uppercase tracking-label-up text-fg-secondary">
          {title}
        </span>
        {right && (
          <span
            className="uppercase tracking-label-up text-fg-tertiary-2 tabular-nums"
            style={{ fontSize: 9 }}
          >
            {right}
          </span>
        )}
      </div>
      <div className="px-3 py-2.5">{children}</div>
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

function formatMinutes(min: number): string {
  if (min < 60) return `${Math.round(min)}m`;
  const h = Math.floor(min / 60);
  const m = Math.round(min % 60);
  return `${h}h ${m}m`;
}
