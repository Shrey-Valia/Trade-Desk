import { useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { PageHeader } from "@/components/layout/PageHeader";
import { useAccountState } from "@/hooks/useAccountState";
import { useCombines, usePurchaseCombine, useRenameCombine } from "@/hooks/useCombines";
import type { TierSpec } from "@/types/account";
import type { CombineOut } from "@/types/combine";

type TierChoice = "50K" | "100K" | "150K";

/**
 * /combines/new — the purchase funnel.
 *
 *   1. PICK TIER   catalog cards (real specs, $XX placeholder price)
 *   2. PAYMENT     order summary + PLACEHOLDER fake-success button
 *   3. LAUNCH      name the combine, jump to dashboard/terminal
 *
 * Payment is PLACEHOLDER ECONOMICS until Stripe lands: the "Complete
 * payment" button fires POST /api/combines/purchase directly, which
 * records a placeholder_paid payment row server-side. Pricing ($XX)
 * and profit split are pending business decisions — do not invent
 * numbers here.
 */
export function NewCombinePage() {
  const combines = useCombines();
  const slotsUsed = combines.data?.slots_used ?? 0;
  const slotsTotal = combines.data?.slots_total ?? 5;
  const atCap = combines.data != null && slotsUsed >= slotsTotal;

  const [tier, setTier] = useState<TierChoice | null>(null);
  const [purchased, setPurchased] = useState<CombineOut | null>(null);
  const step = purchased ? 3 : tier ? 2 : 1;

  return (
    <div className="flex flex-col h-full min-h-0 bg-tier-0">
      <PageHeader
        title="Start a Trading Combine"
        subtitle={`${slotsUsed} of ${slotsTotal} combine slots used`}
      />
      <main className="flex-1 min-h-0 overflow-y-auto">
        <div className="mx-auto px-6 py-6 flex flex-col gap-5" style={{ maxWidth: 860 }}>
          <StepRail step={step} />
          {step === 1 && (
            <PickTier
              atCap={atCap}
              slotsUsed={slotsUsed}
              slotsTotal={slotsTotal}
              onPick={(t) => setTier(t)}
            />
          )}
          {step === 2 && tier && (
            <Payment
              tier={tier}
              onBack={() => setTier(null)}
              onPurchased={(c) => setPurchased(c)}
            />
          )}
          {step === 3 && purchased && <Launch combine={purchased} />}
        </div>
      </main>
    </div>
  );
}

function StepRail({ step }: { step: 1 | 2 | 3 }) {
  const items = ["Pick a combine", "Payment", "Name & launch"];
  return (
    <div className="flex items-center gap-3">
      {items.map((label, i) => {
        const n = (i + 1) as 1 | 2 | 3;
        const state = n < step ? "done" : n === step ? "active" : "todo";
        return (
          <div key={label} className="flex items-center gap-3">
            {i > 0 && <span className="w-8 h-px bg-tier-3" aria-hidden />}
            <span className="flex items-center gap-1.5">
              <span
                className={[
                  "inline-flex items-center justify-center w-5 h-5 rounded-full border text-tiny tabular-nums",
                  state === "active"
                    ? "border-amber text-amber"
                    : state === "done"
                      ? "border-bullish text-bullish"
                      : "border-tier-3 text-fg-tertiary-2",
                ].join(" ")}
              >
                {state === "done" ? "✓" : n}
              </span>
              <span
                className={`text-tiny uppercase tracking-label-up ${
                  state === "active" ? "text-fg-primary" : "text-fg-tertiary-2"
                }`}
              >
                {label}
              </span>
            </span>
          </div>
        );
      })}
    </div>
  );
}

// -- step 1: tier catalog -----------------------------------------------------

function PickTier({
  atCap,
  slotsUsed,
  slotsTotal,
  onPick,
}: {
  atCap: boolean;
  slotsUsed: number;
  slotsTotal: number;
  onPick: (t: TierChoice) => void;
}) {
  const { data: account } = useAccountState();
  const { data: combines } = useCombines();
  // Tier catalog: prefer account-state payload; fall back to the
  // hardcoded specs so a zero-combine user (whose /state 404s) still
  // sees the cards.
  const tiers: TierSpec[] = account?.tiers ?? FALLBACK_TIERS;
  void combines;

  return (
    <>
      {atCap && (
        <div className="border border-warning text-warning text-tiny px-3 py-2">
          You hold {slotsUsed} of {slotsTotal} combines — the maximum. Archive
          one from the dashboard to free a slot before purchasing another.
        </div>
      )}
      <div className="grid gap-4" style={{ gridTemplateColumns: "repeat(3, 1fr)" }}>
        {tiers.map((t) => (
          <TierCard key={t.key} tier={t} disabled={atCap} onPick={onPick} />
        ))}
      </div>
      <p className="text-tiny text-fg-tertiary">
        Every combine is a paper-trading evaluation: trade 0DTE options within
        the loss limits, hit the profit target, keep the account. Display-only
        rules today — see the dashboard&rsquo;s Path to Funding.
      </p>
    </>
  );
}

const FALLBACK_TIERS: TierSpec[] = [
  { key: "50K", label: "50K Combine", starting_balance: 50_000, trailing_distance: 2_000, initial_mll: 48_000, dll_amount: 1_500 },
  { key: "100K", label: "100K Combine", starting_balance: 100_000, trailing_distance: 4_000, initial_mll: 96_000, dll_amount: 3_000 },
  { key: "150K", label: "150K Combine", starting_balance: 150_000, trailing_distance: 4_500, initial_mll: 145_500, dll_amount: 4_500 },
];

const PROFIT_TARGETS: Record<string, number> = {
  "50K": 3_000,
  "100K": 6_000,
  "150K": 9_000,
};

function TierCard({
  tier,
  disabled,
  onPick,
}: {
  tier: TierSpec;
  disabled: boolean;
  onPick: (t: TierChoice) => void;
}) {
  return (
    <div className="border border-hairline-strong bg-tier-1 flex flex-col" style={{ borderRadius: 4 }}>
      <div className="px-4 pt-3 pb-2 border-b border-hairline">
        <div className="text-medium font-medium text-fg-primary">{tier.label}</div>
        <div className="flex items-baseline gap-1 mt-1">
          {/* PLACEHOLDER — pricing is a pending business decision. */}
          <span className="text-large font-medium text-amber">$XX</span>
          <span className="text-tiny text-fg-tertiary-2">/ month</span>
        </div>
      </div>
      <div className="px-4 py-3 flex flex-col gap-1.5 tabular-nums flex-1">
        <SpecRow label="Account size" value={`$${tier.starting_balance.toLocaleString()}`} />
        <SpecRow label="Profit target" value={`$${(PROFIT_TARGETS[tier.key] ?? 0).toLocaleString()}`} />
        <SpecRow label="Max loss limit" value={`trails $${tier.trailing_distance.toLocaleString()}`} />
        <SpecRow label="Daily loss limit" value={`$${tier.dll_amount.toLocaleString()}`} />
        <SpecRow label="Markets" value="0DTE options" />
      </div>
      <div className="px-4 pb-3">
        <button
          type="button"
          disabled={disabled}
          onClick={() => onPick(tier.key as TierChoice)}
          className="w-full h-8 uppercase tracking-label-up border border-amber text-amber bg-tier-2 hover:bg-tier-3 disabled:opacity-40 disabled:cursor-not-allowed rounded-btn font-medium"
          style={{ fontSize: 11 }}
        >
          Select {tier.key}
        </button>
      </div>
    </div>
  );
}

function SpecRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline justify-between">
      <span className="uppercase tracking-label-up text-fg-tertiary-2" style={{ fontSize: 9 }}>
        {label}
      </span>
      <span className="text-tiny text-fg-secondary">{value}</span>
    </div>
  );
}

// -- step 2: placeholder payment ----------------------------------------------

function Payment({
  tier,
  onBack,
  onPurchased,
}: {
  tier: TierChoice;
  onBack: () => void;
  onPurchased: (c: CombineOut) => void;
}) {
  const purchase = usePurchaseCombine();
  const spec = useMemo(
    () => FALLBACK_TIERS.find((t) => t.key === tier)!,
    [tier],
  );

  return (
    <div className="border border-hairline-strong bg-tier-1 mx-auto w-full" style={{ maxWidth: 480, borderRadius: 4 }}>
      <div className="px-4 py-3 border-b border-hairline flex items-baseline justify-between">
        <span className="text-medium font-medium text-fg-primary">Order summary</span>
        <button
          type="button"
          onClick={onBack}
          className="text-tiny text-fg-tertiary-2 hover:text-fg-primary uppercase tracking-label-up"
        >
          ← change tier
        </button>
      </div>
      <div className="px-4 py-3 flex flex-col gap-1.5 tabular-nums">
        <SpecRow label="Plan" value={spec.label} />
        <SpecRow label="Account size" value={`$${spec.starting_balance.toLocaleString()}`} />
        <SpecRow label="Billed" value="monthly, cancel anytime" />
        <div className="border-t border-hairline my-1.5" />
        <div className="flex items-baseline justify-between">
          <span className="uppercase tracking-label-up text-fg-secondary" style={{ fontSize: 10 }}>
            Due today
          </span>
          {/* PLACEHOLDER — pricing pending. */}
          <span className="text-medium font-medium text-amber">$XX.00</span>
        </div>
      </div>
      <div className="px-4 pb-4 flex flex-col gap-2">
        <div
          className="border border-dashed border-tier-3 text-fg-tertiary-2 text-tiny px-3 py-2 text-center"
          style={{ borderRadius: 4 }}
        >
          PLACEHOLDER — Stripe checkout pending. The button below records a
          placeholder payment and provisions the combine immediately.
        </div>
        <button
          type="button"
          disabled={purchase.isPending}
          onClick={() =>
            purchase.mutate({ tier }, { onSuccess: (c) => onPurchased(c) })
          }
          className="h-10 w-full uppercase tracking-label-up bg-action-buy hover:bg-action-buy-hover text-white font-semibold rounded-btn disabled:opacity-50"
          style={{ fontSize: 12 }}
        >
          {purchase.isPending ? "Processing…" : "Complete payment (placeholder)"}
        </button>
        {purchase.isError && (
          <div className="text-tiny text-bearish" role="alert">
            {(purchase.error as Error).message}
          </div>
        )}
      </div>
    </div>
  );
}

// -- step 3: name & launch ------------------------------------------------------

function Launch({ combine }: { combine: CombineOut }) {
  const navigate = useNavigate();
  const rename = useRenameCombine();
  const [name, setName] = useState(combine.name);
  const dirty = name.trim() !== combine.name && name.trim().length > 0;

  return (
    <div className="border border-hairline-strong bg-tier-1 mx-auto w-full" style={{ maxWidth: 480, borderRadius: 4 }}>
      <div className="px-4 py-3 border-b border-hairline">
        <div className="text-medium font-medium text-bullish">
          Combine provisioned ✓
        </div>
        <div className="text-tiny text-fg-tertiary-2 mt-0.5 tabular-nums">
          {combine.account_code} · ${combine.starting_balance.toLocaleString()} ·
          target ${combine.profit_target.toLocaleString()}
        </div>
      </div>
      <div className="px-4 py-3 flex flex-col gap-2">
        <label className="flex flex-col gap-1">
          <span className="uppercase tracking-label-up text-fg-tertiary-2" style={{ fontSize: 9 }}>
            Combine name
          </span>
          <div className="flex gap-2">
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              maxLength={64}
              className="flex-1 h-8 px-2 bg-tier-2 border border-tier-3 rounded-btn text-fg-primary focus:border-amber focus:outline-none"
              style={{ fontSize: 13 }}
            />
            <button
              type="button"
              disabled={!dirty || rename.isPending}
              onClick={() => rename.mutate({ id: combine.id, name: name.trim() })}
              className="h-8 px-3 text-tiny uppercase tracking-label-up border border-hairline text-fg-secondary hover:bg-tier-2 disabled:opacity-40 rounded-btn"
            >
              {rename.isPending ? "Saving…" : "Save"}
            </button>
          </div>
        </label>
      </div>
      <div className="px-4 pb-4 grid grid-cols-2 gap-2">
        <button
          type="button"
          onClick={() => navigate("/dashboard")}
          className="h-9 uppercase tracking-label-up border border-amber text-amber bg-tier-2 hover:bg-tier-3 rounded-btn font-medium"
          style={{ fontSize: 11 }}
        >
          Open dashboard
        </button>
        <Link
          to="/positions"
          className="h-9 inline-flex items-center justify-center uppercase tracking-label-up bg-action-buy hover:bg-action-buy-hover text-white font-semibold rounded-btn"
          style={{ fontSize: 11 }}
        >
          Start trading →
        </Link>
      </div>
    </div>
  );
}
