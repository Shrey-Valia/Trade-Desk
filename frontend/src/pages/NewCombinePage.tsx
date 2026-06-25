import { useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { PageHeader } from "@/components/layout/PageHeader";
import { useAccountState } from "@/hooks/useAccountState";
import { useCombines, usePurchaseCombine, useRenameCombine } from "@/hooks/useCombines";
import {
  activationFee,
  MAX_CONTRACTS,
  monthlyPrice,
  splitPct,
  type PricingPath,
  type SplitToken,
} from "@/lib/pricing";
import type { TierSpec } from "@/types/account";
import type { CombineOut } from "@/types/combine";

type TierChoice = "50K" | "100K" | "150K";

/**
 * /combines/new — "Choose your account" (Topstep-style buy page).
 *
 *   1. CHOOSE   one Funding-path toggle (No Activation Fee / Standard) re-prices
 *               three tier cards; pick a size.
 *   2. CONFIGURE  choose the profit split (50/50 base, 80/20 = +$10/mo), see the
 *               final price, confirm.
 *   3. LAUNCH   name the combine, jump to dashboard/terminal.
 *
 * Trade Desk is a paper prop firm — prices are real (lib/pricing.ts, mirrored
 * from the backend) but the checkout is simulated (no card charged). Honest
 * nudges: No-Activation is the default path and 50/50 is the base split, with
 * 80/20 framed as a +$10/mo upgrade; every cost (incl. the $149 activation fee)
 * is shown upfront and both options are equally easy to pick. Colour follows
 * the app system — amber = selected/active, blue (action-buy) only on the final
 * purchase CTA.
 */
export function NewCombinePage() {
  const combines = useCombines();
  const slotsUsed = combines.data?.slots_used ?? 0;
  const slotsTotal = combines.data?.slots_total ?? 5;
  const atCap = combines.data != null && slotsUsed >= slotsTotal;

  const [path, setPath] = useState<PricingPath>("no_activation");
  const [tier, setTier] = useState<TierChoice | null>(null);
  const [purchased, setPurchased] = useState<CombineOut | null>(null);

  return (
    <div className="flex flex-col h-full min-h-0 bg-tier-0">
      <PageHeader
        title="Start a Trading Combine"
        subtitle={`${slotsUsed} of ${slotsTotal} combine slots used`}
      />
      <main className="flex-1 min-h-0 overflow-y-auto">
        {purchased ? (
          <div className="mx-auto px-6 py-8" style={{ maxWidth: 520 }}>
            <Launch combine={purchased} />
          </div>
        ) : tier ? (
          <div className="mx-auto px-6 py-8" style={{ maxWidth: 560 }}>
            <Configure
              tier={tier}
              path={path}
              onBack={() => setTier(null)}
              onPurchased={setPurchased}
            />
          </div>
        ) : (
          <ChooseAccount
            path={path}
            setPath={setPath}
            atCap={atCap}
            slotsUsed={slotsUsed}
            slotsTotal={slotsTotal}
            onPick={setTier}
          />
        )}
      </main>
    </div>
  );
}

// -- step 1: choose path + size -----------------------------------------------

function ChooseAccount({
  path,
  setPath,
  atCap,
  slotsUsed,
  slotsTotal,
  onPick,
}: {
  path: PricingPath;
  setPath: (p: PricingPath) => void;
  atCap: boolean;
  slotsUsed: number;
  slotsTotal: number;
  onPick: (t: TierChoice) => void;
}) {
  const { data: account } = useAccountState();
  const tiers: TierSpec[] = account?.tiers ?? FALLBACK_TIERS;

  return (
    <div className="mx-auto px-6 py-8 flex flex-col items-center gap-6" style={{ maxWidth: 1040 }}>
      <h1 className="font-medium text-fg-primary" style={{ fontSize: 28 }}>
        Choose your account
      </h1>

      <SegToggle
        value={path}
        onChange={(v) => setPath(v as PricingPath)}
        options={[
          { value: "activation", label: "Standard" },
          { value: "no_activation", label: "No Activation Fee" },
        ]}
      />

      <InfoBanner>
        {path === "no_activation"
          ? "No Activation Fee — the lowest all-in cost when you pass: a higher monthly, but $0 to unlock your funded account. (Standard charges a one-time $149 when you get funded.)"
          : "Standard — a lower monthly while you build consistency, plus a one-time $149 activation fee when you pass and your account funds."}
      </InfoBanner>

      {atCap && (
        <div className="w-full border border-warning text-warning text-tiny px-3 py-2" style={{ maxWidth: 720 }}>
          You hold {slotsUsed} of {slotsTotal} combines — the maximum. Archive
          one from the dashboard to free a slot before purchasing another.
        </div>
      )}

      <div className="grid gap-4 w-full grid-cols-1 sm:grid-cols-3">
        {tiers.map((t) => (
          <AccountCard
            key={t.key}
            tier={t}
            path={path}
            recommended={t.key === "100K"}
            disabled={atCap}
            onPick={() => onPick(t.key as TierChoice)}
          />
        ))}
      </div>

      <span className="text-tiny text-fg-tertiary text-center" style={{ maxWidth: 560 }}>
        Simulated checkout — this is a paper evaluation, so no card is charged.
        You&rsquo;ll pick your profit split next.
      </span>
    </div>
  );
}

const FALLBACK_TIERS: TierSpec[] = [
  { key: "50K", label: "50K Combine", starting_balance: 50_000, trailing_distance: 2_000, initial_mll: 48_000, dll_amount: 1_500 },
  { key: "100K", label: "100K Combine", starting_balance: 100_000, trailing_distance: 3_000, initial_mll: 97_000, dll_amount: 3_000 },
  { key: "150K", label: "150K Combine", starting_balance: 150_000, trailing_distance: 4_500, initial_mll: 145_500, dll_amount: 4_500 },
];

const PROFIT_TARGETS: Record<string, number> = {
  "50K": 3_000,
  "100K": 6_000,
  "150K": 9_000,
};

function AccountCard({
  tier,
  path,
  recommended,
  disabled,
  onPick,
}: {
  tier: TierSpec;
  path: PricingPath;
  recommended: boolean;
  disabled: boolean;
  onPick: () => void;
}) {
  // Headline = the 50/50 base (the cheaper, default split); 80/20 is +$10 in
  // the configure step.
  const monthly = monthlyPrice(tier.key, path, "50_50");
  const fee = activationFee(path);

  return (
    <div
      className={[
        "relative bg-tier-1 flex flex-col",
        recommended ? "border-2 border-amber" : "border border-hairline-strong",
      ].join(" ")}
      style={{ borderRadius: 6 }}
    >
      {recommended && (
        <div
          className="text-center uppercase tracking-label-up text-amber border-b border-amber py-1"
          style={{ fontSize: 11 }}
        >
          Most popular
        </div>
      )}
      <div className="px-4 pt-3.5 pb-3">
        <span
          className="inline-block uppercase tracking-label-up text-fg-tertiary-2 border border-hairline-strong px-2 py-0.5"
          style={{ fontSize: 11, borderRadius: 2 }}
        >
          {path === "no_activation" ? "No Activation Fee" : "Standard"}
        </span>
        <div className="text-medium font-medium text-fg-primary mt-2">
          {tier.key} Combine
        </div>
        <div className="flex items-baseline gap-1 mt-1">
          <span className="text-display font-medium text-fg-primary tabular-nums">
            ${monthly}
          </span>
          <span className="text-tiny text-fg-tertiary-2">.00 / month</span>
        </div>
      </div>

      <div className="px-4 py-3 flex flex-col gap-2 tabular-nums flex-1 border-t border-hairline">
        <SpecRow label="Account size" value={`$${tier.starting_balance.toLocaleString()}`} />
        <SpecRow label="Profit target" value={`$${(PROFIT_TARGETS[tier.key] ?? 0).toLocaleString()}`} />
        <SpecRow label="Max position" value={`up to ${MAX_CONTRACTS[tier.key] ?? 1} contracts`} />
        <SpecRow label="Max loss limit" value={`trails $${tier.trailing_distance.toLocaleString()}`} />
        <SpecRow label="Daily loss limit" value={`$${tier.dll_amount.toLocaleString()}`} />
        <SpecRow
          label="Activation fee"
          value={fee > 0 ? `$${fee} when funded` : "$0 — none"}
          tone={fee > 0 ? "muted" : "good"}
        />
      </div>

      <div className="px-4 pb-4 pt-1">
        <button
          type="button"
          disabled={disabled}
          onClick={onPick}
          className={[
            "w-full h-9 uppercase tracking-label-up font-medium rounded-btn disabled:opacity-40 disabled:cursor-not-allowed",
            recommended
              ? "bg-amber text-tier-0 hover:opacity-90"
              : "border border-amber text-amber bg-tier-2 hover:bg-tier-3",
          ].join(" ")}
          style={{ fontSize: 11 }}
        >
          Select {tier.key}
        </button>
      </div>
    </div>
  );
}

// -- step 2: configure split + confirm ----------------------------------------

function Configure({
  tier,
  path,
  onBack,
  onPurchased,
}: {
  tier: TierChoice;
  path: PricingPath;
  onBack: () => void;
  onPurchased: (c: CombineOut) => void;
}) {
  const purchase = usePurchaseCombine();
  const spec = useMemo(() => FALLBACK_TIERS.find((t) => t.key === tier)!, [tier]);
  const [split, setSplit] = useState<SplitToken>("50_50");

  const monthly = monthlyPrice(tier, path, split);
  const fee = activationFee(path);

  return (
    <div className="border border-hairline-strong bg-tier-1 w-full" style={{ borderRadius: 6 }}>
      <div className="px-4 py-3 border-b border-hairline flex items-baseline justify-between">
        <span className="text-medium font-medium text-fg-primary">{spec.label}</span>
        <button
          type="button"
          onClick={onBack}
          className="text-tiny text-fg-tertiary-2 hover:text-fg-primary uppercase tracking-label-up"
        >
          ← change
        </button>
      </div>

      <div className="px-4 py-3 flex flex-col gap-3">
        <span className="uppercase tracking-label-up text-fg-tertiary-2" style={{ fontSize: 11 }}>
          Choose your profit split
        </span>
        <div className="grid gap-2" style={{ gridTemplateColumns: "repeat(2, 1fr)" }}>
          <SplitCard
            selected={split === "50_50"}
            onClick={() => setSplit("50_50")}
            title="50 / 50"
            price={`$${monthlyPrice(tier, path, "50_50")}/mo`}
            note="You keep 50% of funded profit"
          />
          <SplitCard
            selected={split === "80_20"}
            onClick={() => setSplit("80_20")}
            title="80 / 20"
            price={`+$10/mo · $${monthlyPrice(tier, path, "80_20")}/mo`}
            note="You keep 80% of funded profit"
          />
        </div>

        <div className="border-t border-hairline pt-3 flex flex-col gap-1.5 tabular-nums">
          <SpecRow label="Plan" value={`${spec.label} · ${path === "no_activation" ? "No Activation Fee" : "Standard"}`} />
          <SpecRow label="Account size" value={`$${spec.starting_balance.toLocaleString()}`} />
          <SpecRow label="Profit split" value={`you keep ${splitPct(split)}%`} />
          <SpecRow
            label="Activation fee"
            value={fee > 0 ? `$${fee} when funded` : "$0 — none"}
            tone={fee > 0 ? "muted" : "good"}
          />
          <SpecRow label="Billed" value="monthly, cancel anytime" />
          <div className="border-t border-hairline my-1.5" />
          <div className="flex items-baseline justify-between">
            <span className="uppercase tracking-label-up text-fg-secondary" style={{ fontSize: 12 }}>
              Due today
            </span>
            <span className="text-medium font-medium text-fg-primary tabular-nums">
              ${monthly}.00
            </span>
          </div>
        </div>
      </div>

      <div className="px-4 pb-4 flex flex-col gap-2">
        <div
          className="border border-hairline text-fg-tertiary-2 text-tiny px-3 py-2 text-center"
          style={{ borderRadius: 4 }}
        >
          Simulated checkout — no card is charged. Your path &amp; split lock in
          at purchase.
        </div>
        <button
          type="button"
          disabled={purchase.isPending}
          onClick={() =>
            purchase.mutate(
              { tier, pricing_path: path, split },
              { onSuccess: (c) => onPurchased(c) },
            )
          }
          className="h-10 w-full uppercase tracking-label-up bg-action-buy hover:bg-action-buy-hover text-white font-semibold rounded-btn disabled:opacity-50"
          style={{ fontSize: 12 }}
        >
          {purchase.isPending ? "Processing…" : `Start combine — $${monthly}/mo`}
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

function SplitCard({
  selected,
  onClick,
  title,
  price,
  note,
}: {
  selected: boolean;
  onClick: () => void;
  title: string;
  price: string;
  note: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={selected}
      className={[
        "flex flex-col items-start gap-0.5 px-3 py-2 text-left transition-colors",
        selected ? "border-2 border-amber bg-tier-2" : "border border-hairline-strong bg-tier-1 hover:bg-tier-2",
      ].join(" ")}
      style={{ borderRadius: 4 }}
    >
      <span className={`text-tiny font-medium ${selected ? "text-amber" : "text-fg-primary"}`}>
        {title}
      </span>
      <span className="text-tiny tabular-nums text-fg-secondary">{price}</span>
      <span className="text-fg-tertiary-2" style={{ fontSize: 11 }}>
        {note}
      </span>
    </button>
  );
}

function SpecRow({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone?: "muted" | "good";
}) {
  const valueCls =
    tone === "good" ? "text-bullish" : tone === "muted" ? "text-fg-tertiary" : "text-fg-secondary";
  return (
    <div className="flex items-baseline justify-between">
      <span className="uppercase tracking-label-up text-fg-tertiary-2" style={{ fontSize: 11 }}>
        {label}
      </span>
      <span className={`text-tiny ${valueCls}`}>{value}</span>
    </div>
  );
}

// -- segmented toggle (amber = selected, app convention) ----------------------

function SegToggle({
  value,
  onChange,
  options,
}: {
  value: string;
  onChange: (v: string) => void;
  options: { value: string; label: string }[];
}) {
  return (
    <div
      className="inline-flex items-center gap-1 p-1 bg-tier-2 border border-hairline rounded-full"
      role="tablist"
    >
      {options.map((o) => {
        const selected = o.value === value;
        return (
          <button
            key={o.value}
            type="button"
            role="tab"
            aria-selected={selected}
            onClick={() => onChange(o.value)}
            className={[
              "px-4 h-8 rounded-full text-tiny font-medium uppercase tracking-label-up transition-colors",
              selected ? "bg-amber text-tier-0" : "text-fg-secondary hover:text-fg-primary",
            ].join(" ")}
            style={{ fontSize: 11 }}
          >
            {o.label}
          </button>
        );
      })}
    </div>
  );
}

function InfoBanner({ children }: { children: React.ReactNode }) {
  return (
    <div
      className="flex items-start gap-2 bg-tier-2 border border-hairline px-4 py-2.5 text-tiny text-fg-secondary"
      style={{ maxWidth: 720, borderRadius: 6 }}
    >
      <span
        className="inline-flex items-center justify-center shrink-0 border border-amber text-amber rounded-full"
        style={{ width: 16, height: 16, fontSize: 12 }}
        aria-hidden
      >
        i
      </span>
      <span className="leading-relaxed">{children}</span>
    </div>
  );
}

// -- step 3: name & launch ----------------------------------------------------

function Launch({ combine }: { combine: CombineOut }) {
  const navigate = useNavigate();
  const rename = useRenameCombine();
  const [name, setName] = useState(combine.name);
  const dirty = name.trim() !== combine.name && name.trim().length > 0;

  return (
    <div className="border border-hairline-strong bg-tier-1 w-full" style={{ borderRadius: 4 }}>
      <div className="px-4 py-3 border-b border-hairline">
        <div className="text-medium font-medium text-bullish">
          Combine provisioned ✓
        </div>
        <div className="text-tiny text-fg-tertiary-2 mt-0.5 tabular-nums">
          {combine.account_code} · ${combine.starting_balance.toLocaleString()} ·
          target ${combine.profit_target.toLocaleString()} · ${combine.monthly_price}/mo
        </div>
      </div>
      <div className="px-4 py-3 flex flex-col gap-2">
        <label className="flex flex-col gap-1">
          <span className="uppercase tracking-label-up text-fg-tertiary-2" style={{ fontSize: 11 }}>
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
