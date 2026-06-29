import { useMemo, useState } from "react";

import { useAccountState } from "@/hooks/useAccountState";
import { useTradeTicket } from "@/stores/tradeTicket";

/**
 * WS5 — position-sizing / risk calculator. Self-contained: given the
 * account-risk % the trader is willing to lose, a stop distance ($/share off
 * the option premium), and the entry premium, it computes the suggested
 * contract count and the resulting max loss.
 *
 * Math (per-contract = 100 shares):
 *   risk_budget   = balance × risk%/100
 *   loss_per_ctr  = stop_distance × 100         (premium $/share → $/contract)
 *   suggested     = floor(risk_budget / loss_per_ctr)        (≥ 0)
 *   max_loss      = suggested × loss_per_ctr
 *
 * Premium seeds the stop default (a 50% premium stop) and the cost line, but
 * the sizing is driven by the STOP distance, not the whole premium — a stop
 * caps the loss below the full debit. Reads balance from the live account
 * state and the entry premium from the current ticket selection when present.
 */
export function PositionSizer() {
  const { data: account } = useAccountState();
  const selection = useTradeTicket((s) => s.selection);
  const balance = account?.balance ?? 0;

  const seededPremium = selection?.price ?? null;
  const [riskPct, setRiskPct] = useState<number>(1);
  const [premium, setPremium] = useState<number | null>(seededPremium);
  // Default stop = half the premium (a 50% stop-out) when we have one.
  const [stopDistance, setStopDistance] = useState<number | null>(
    seededPremium != null ? round2(seededPremium * 0.5) : null,
  );

  const result = useMemo(
    () => computeSizing({ balance, riskPct, stopDistance }),
    [balance, riskPct, stopDistance],
  );

  const debitPerCtr =
    premium != null && premium > 0 ? premium * 100 : null;

  return (
    <div className="flex flex-col gap-1.5 px-3 py-2 tabular-nums">
      <div className="flex items-center justify-between">
        <span className="text-tiny uppercase tracking-label-up text-fg-secondary">
          Position sizer
        </span>
        <span className="text-fg-tertiary-2" style={{ fontSize: 11 }}>
          bal ${fmt(balance)}
        </span>
      </div>

      <div className="grid grid-cols-3 gap-2">
        <NumField
          label="risk %"
          value={riskPct}
          onChange={(v) => setRiskPct(v ?? 0)}
          step={0.25}
          max={100}
          suffix="%"
        />
        <NumField
          label="stop $/sh"
          value={stopDistance}
          onChange={setStopDistance}
          step={0.05}
          ariaLabel="Stop distance per share"
        />
        <NumField
          label="premium"
          value={premium}
          onChange={setPremium}
          step={0.05}
          ariaLabel="Entry premium per share"
        />
      </div>

      <div className="flex flex-col gap-0.5 pt-0.5" aria-live="polite">
        <Stat
          label="suggested"
          value={
            result.valid
              ? `${result.suggested} ${result.suggested === 1 ? "contract" : "contracts"}`
              : "—"
          }
          tone="amber"
        />
        <Stat
          label="risk budget"
          value={result.valid ? `$${fmt(result.riskBudget)}` : `$${fmt(balance * (riskPct / 100))}`}
        />
        <Stat
          label="max loss"
          value={result.valid ? `$${fmt(result.maxLoss)}` : "—"}
          tone="bearish"
        />
        {debitPerCtr != null && (
          <Stat
            label="full debit"
            value={
              result.valid
                ? `$${fmt(debitPerCtr * result.suggested)} (${result.suggested}×)`
                : `$${fmt(debitPerCtr)}/ctr`
            }
          />
        )}
      </div>

      {!result.valid && (
        <span className="text-fg-tertiary-2" style={{ fontSize: 11 }}>
          {result.reason}
        </span>
      )}
    </div>
  );
}

export interface SizingInput {
  balance: number;
  riskPct: number;
  stopDistance: number | null;
}

export interface SizingResult {
  valid: boolean;
  suggested: number;
  riskBudget: number;
  lossPerContract: number;
  maxLoss: number;
  reason: string;
}

/** Pure sizing math — exported for unit testing. */
export function computeSizing({
  balance,
  riskPct,
  stopDistance,
}: SizingInput): SizingResult {
  const riskBudget = balance * (riskPct / 100);
  if (balance <= 0) {
    return blank(riskBudget, "Account balance unavailable.");
  }
  if (!(riskPct > 0)) {
    return blank(riskBudget, "Set a risk % above 0.");
  }
  if (stopDistance == null || !(stopDistance > 0)) {
    return blank(riskBudget, "Set a stop distance above 0.");
  }
  const lossPerContract = stopDistance * 100;
  const suggested = Math.max(0, Math.floor(riskBudget / lossPerContract));
  return {
    valid: suggested > 0,
    suggested,
    riskBudget,
    lossPerContract,
    maxLoss: suggested * lossPerContract,
    reason:
      suggested > 0
        ? ""
        : "Risk budget below one contract's stop loss — widen risk % or tighten the stop.",
  };
}

function blank(riskBudget: number, reason: string): SizingResult {
  return {
    valid: false,
    suggested: 0,
    riskBudget,
    lossPerContract: 0,
    maxLoss: 0,
    reason,
  };
}

function round2(v: number): number {
  return Math.round(v * 100) / 100;
}

function fmt(v: number): string {
  return v.toLocaleString(undefined, {
    minimumFractionDigits: 0,
    maximumFractionDigits: 0,
  });
}

function Stat({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone?: "amber" | "bearish";
}) {
  const color =
    tone === "amber"
      ? "text-amber"
      : tone === "bearish"
        ? "text-bearish"
        : "text-fg-secondary";
  return (
    <div className="flex items-baseline justify-between" style={{ fontSize: 12 }}>
      <span className="uppercase tracking-label-up text-fg-tertiary-2" style={{ fontSize: 11 }}>
        {label}
      </span>
      <span className={`tabular-nums ${color}`}>{value}</span>
    </div>
  );
}

function NumField({
  label,
  value,
  onChange,
  step,
  max,
  suffix,
  ariaLabel,
}: {
  label: string;
  value: number | null;
  onChange: (v: number | null) => void;
  step: number;
  max?: number;
  suffix?: string;
  ariaLabel?: string;
}) {
  return (
    <label className="flex flex-col gap-0.5" style={{ fontSize: 11 }}>
      <span className="uppercase tracking-label-up text-fg-tertiary-2">{label}</span>
      <div className="flex items-center gap-0.5">
        <input
          type="number"
          inputMode="decimal"
          min={0}
          max={max}
          step={step}
          value={value ?? ""}
          onChange={(e) => {
            const v = parseFloat(e.target.value);
            onChange(Number.isFinite(v) ? v : null);
          }}
          aria-label={ariaLabel ?? label}
          className="bg-tier-2 border border-tier-3 rounded-btn text-fg-primary tabular-nums text-right px-1.5 w-full"
          style={{ height: 24, fontSize: 12 }}
        />
        {suffix && <span className="text-fg-tertiary-2">{suffix}</span>}
      </div>
    </label>
  );
}
