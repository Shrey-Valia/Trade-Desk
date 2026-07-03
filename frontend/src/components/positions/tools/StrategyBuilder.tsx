import { useEffect, useMemo, useState } from "react";

import { useChainTable } from "@/hooks/useChainTable";
import { useMarketStatus } from "@/hooks/useMarket";
import { useOpenZeroDteMultiLeg } from "@/hooks/useOpenZeroDteMultiLeg";
import { premiumExitForDirection, useTradeTicket } from "@/stores/tradeTicket";
import type { ChainStrikeRow, MultiLegSpec } from "@/types/zerodte";

/**
 * WS5 — multi-leg strategy builder. Presets (vertical / iron condor /
 * butterfly) auto-place legs off the live ATM + strike grid; a CUSTOM mode
 * lets the trader edit each leg's side/action/strike/ratio. Fires the
 * multi-leg open endpoint (one Trade carrying all legs).
 *
 * Self-contained: reads the chain table for the symbol to resolve real
 * strikes; the open path on the backend re-prices each leg at the indicative
 * market fill and gates via the scaling cap, so this is a pure builder UI.
 */

type Preset = "vertical" | "iron_condor" | "butterfly" | "custom";

interface Props {
  symbol: string;
}

export function StrategyBuilder({ symbol }: Props) {
  const { data: chain } = useChainTable(symbol, 12);
  const { data: marketStatus } = useMarketStatus();
  const marketOpen = marketStatus?.status === "open";
  const openMulti = useOpenZeroDteMultiLeg();

  const strikes = useMemo(
    () => (chain?.rows ?? []).map((r) => r.strike).sort((a, b) => a - b),
    [chain],
  );
  const atm = chain?.atm_strike ?? null;
  const step = useMemo(() => strikeStep(strikes), [strikes]);

  const [preset, setPreset] = useState<Preset>("vertical");
  const [contracts, setContracts] = useState(1);
  const [legs, setLegs] = useState<MultiLegSpec[]>([]);

  // Re-derive preset legs whenever the preset / ATM / step changes (but not in
  // custom mode, where the user owns the legs).
  useEffect(() => {
    if (preset === "custom") return;
    if (atm == null) return;
    setLegs(presetLegs(preset, atm, step));
  }, [preset, atm, step]);

  const canFire =
    marketOpen && atm != null && legs.length >= 2 && !openMulti.isPending;

  // Premium-exit presets (ticket store, shared with the single-leg ticket).
  // A structure's direction isn't a button here — derive net debit/credit
  // from the live chain prices; when the legs can't be priced client-side,
  // send nothing (defensive: the backend is the pricing authority).
  const premiumExit = useTradeTicket((s) => s.premiumExit);
  const netPremium = useMemo(
    () => netPremiumPerShare(chain?.rows ?? [], legs),
    [chain, legs],
  );

  const fire = () => {
    if (!canFire) return;
    const exits =
      netPremium != null
        ? premiumExitForDirection(premiumExit, netPremium >= 0)
        : { tp: null, sl: null };
    openMulti.mutate({
      symbol,
      contracts,
      strategy: preset,
      legs,
      tp_premium_mult: exits.tp,
      sl_premium_mult: exits.sl,
    });
  };

  const netLabel = describeLegs(legs);

  return (
    <div className="flex flex-col gap-1.5 px-3 py-2 tabular-nums">
      <div className="flex items-center justify-between">
        <span className="text-tiny uppercase tracking-label-up text-fg-secondary">
          Strategy builder
        </span>
        <span className="text-fg-tertiary-2" style={{ fontSize: 11 }}>
          {symbol} · ATM {atm ?? "—"}
        </span>
      </div>

      {/* Preset selector */}
      <div className="flex flex-wrap" style={{ gap: 4 }}>
        {(["vertical", "iron_condor", "butterfly", "custom"] as const).map((p) => (
          <button
            key={p}
            type="button"
            onClick={() => setPreset(p)}
            aria-pressed={preset === p}
            className={[
              "uppercase tracking-label-up transition-colors duration-100 select-none rounded-btn px-2",
              preset === p
                ? "bg-tier-3 border border-amber text-amber"
                : "bg-tier-2 border border-tier-3 text-fg-secondary hover:bg-tier-3 hover:text-fg-primary",
            ].join(" ")}
            style={{ height: 24, fontSize: 11 }}
          >
            {p.replace("_", " ")}
          </button>
        ))}
      </div>

      {/* Legs editor */}
      <div className="flex flex-col gap-1">
        {legs.map((leg, i) => (
          <LegRow
            key={i}
            leg={leg}
            editable={preset === "custom"}
            strikes={strikes}
            onChange={(next) =>
              setLegs((prev) => prev.map((l, j) => (j === i ? next : l)))
            }
            onRemove={
              preset === "custom" && legs.length > 2
                ? () => setLegs((prev) => prev.filter((_, j) => j !== i))
                : undefined
            }
          />
        ))}
        {preset === "custom" && legs.length < 6 && (
          <button
            type="button"
            onClick={() =>
              setLegs((prev) => [
                ...prev,
                { side: "call", action: "buy", strike: atm ?? strikes[0] ?? 0, ratio: 1 },
              ])
            }
            className="self-start text-amber hover:text-amber uppercase tracking-label-up rounded-btn border border-tier-3 px-2 hover:bg-tier-3"
            style={{ height: 22, fontSize: 11 }}
          >
            + add leg
          </button>
        )}
      </div>

      {/* Size + fire */}
      <div className="flex items-center gap-2 pt-0.5">
        <label className="flex items-center gap-1" style={{ fontSize: 11 }}>
          <span className="uppercase tracking-label-up text-fg-tertiary-2">qty</span>
          <input
            type="number"
            min={1}
            max={100}
            step={1}
            value={contracts}
            onChange={(e) => {
              const v = parseInt(e.target.value, 10);
              setContracts(Number.isFinite(v) ? Math.max(1, Math.min(100, v)) : 1);
            }}
            aria-label="Base contracts"
            className="bg-tier-2 border border-tier-3 rounded-btn text-fg-primary tabular-nums text-right px-1.5"
            style={{ width: 52, height: 24, fontSize: 12 }}
          />
        </label>
        <span className="text-fg-tertiary-2 truncate" style={{ fontSize: 11 }} title={netLabel}>
          {netLabel}
        </span>
        <button
          type="button"
          onClick={fire}
          disabled={!canFire}
          className={[
            "ml-auto rounded-btn px-3 font-semibold uppercase tracking-label-up transition-colors duration-100",
            canFire
              ? "bg-action-buy hover:bg-action-buy-hover text-white"
              : "bg-tier-1 text-fg-disabled cursor-not-allowed",
          ].join(" ")}
          style={{ height: 28, fontSize: 12 }}
        >
          {openMulti.isPending ? "submitting…" : "open structure"}
        </button>
      </div>

      {!marketOpen && (
        <span className="text-warning" style={{ fontSize: 11 }}>
          Market closed — structures open during the regular session.
        </span>
      )}
      {openMulti.isError && (
        <span className="text-bearish truncate" style={{ fontSize: 11 }} title={(openMulti.error as Error)?.message}>
          {(openMulti.error as Error)?.message}
        </span>
      )}
    </div>
  );
}

function LegRow({
  leg,
  editable,
  strikes,
  onChange,
  onRemove,
}: {
  leg: MultiLegSpec;
  editable: boolean;
  strikes: number[];
  onChange: (next: MultiLegSpec) => void;
  onRemove?: () => void;
}) {
  const actionColor =
    leg.action === "buy" ? "text-bullish" : "text-bearish";
  if (!editable) {
    return (
      <div
        className="flex items-center gap-2 tabular-nums text-fg-secondary"
        style={{ fontSize: 12 }}
      >
        <span className={`uppercase ${actionColor}`} style={{ width: 32 }}>
          {leg.action === "buy" ? "buy" : "sell"}
        </span>
        <span className="text-fg-primary">{leg.strike}</span>
        <span className="uppercase text-fg-tertiary-2">{leg.side}</span>
        {(leg.ratio ?? 1) > 1 && (
          <span className="text-amber">×{leg.ratio}</span>
        )}
      </div>
    );
  }
  return (
    <div className="flex items-center gap-1 tabular-nums" style={{ fontSize: 11 }}>
      <select
        value={leg.action}
        onChange={(e) => onChange({ ...leg, action: e.target.value as "buy" | "sell" })}
        aria-label="Leg action"
        className="bg-tier-2 border border-tier-3 rounded-btn text-fg-primary uppercase px-1"
        style={{ height: 22 }}
      >
        <option value="buy">buy</option>
        <option value="sell">sell</option>
      </select>
      <select
        value={leg.side}
        onChange={(e) => onChange({ ...leg, side: e.target.value as "call" | "put" })}
        aria-label="Leg side"
        className="bg-tier-2 border border-tier-3 rounded-btn text-fg-primary uppercase px-1"
        style={{ height: 22 }}
      >
        <option value="call">call</option>
        <option value="put">put</option>
      </select>
      <select
        value={leg.strike}
        onChange={(e) => onChange({ ...leg, strike: parseFloat(e.target.value) })}
        aria-label="Leg strike"
        className="bg-tier-2 border border-tier-3 rounded-btn text-fg-primary tabular-nums px-1"
        style={{ height: 22 }}
      >
        {strikes.map((k) => (
          <option key={k} value={k}>
            {k}
          </option>
        ))}
      </select>
      <input
        type="number"
        min={1}
        max={10}
        step={1}
        value={leg.ratio ?? 1}
        onChange={(e) => {
          const v = parseInt(e.target.value, 10);
          onChange({ ...leg, ratio: Number.isFinite(v) ? Math.max(1, Math.min(10, v)) : 1 });
        }}
        aria-label="Leg ratio"
        title="Ratio (× base contracts)"
        className="bg-tier-2 border border-tier-3 rounded-btn text-fg-primary tabular-nums text-right px-1"
        style={{ width: 38, height: 22 }}
      />
      {onRemove && (
        <button
          type="button"
          onClick={onRemove}
          aria-label="Remove leg"
          className="text-fg-tertiary-2 hover:text-bearish px-1"
          style={{ fontSize: 14, lineHeight: 1 }}
        >
          ×
        </button>
      )}
    </div>
  );
}

// --- preset leg derivation --------------------------------------------------

/** The typical strike increment from the live grid (median gap, fallback 1). */
export function strikeStep(strikes: number[]): number {
  if (strikes.length < 2) return 1;
  const gaps: number[] = [];
  for (let i = 1; i < strikes.length; i++) {
    const g = +(strikes[i] - strikes[i - 1]).toFixed(4);
    if (g > 0) gaps.push(g);
  }
  if (!gaps.length) return 1;
  gaps.sort((a, b) => a - b);
  return gaps[Math.floor(gaps.length / 2)];
}

/** Build the legs for a preset, centered on ATM with `step` width.
 *  Exported for unit testing. */
export function presetLegs(preset: Preset, atm: number, step: number): MultiLegSpec[] {
  const w = step > 0 ? step : 1;
  switch (preset) {
    case "vertical":
      // Bull call spread: long ATM call, short 1-strike-OTM call.
      return [
        { side: "call", action: "buy", strike: atm, ratio: 1 },
        { side: "call", action: "sell", strike: atm + w, ratio: 1 },
      ];
    case "iron_condor":
      // Short put + call spreads bracketing ATM.
      return [
        { side: "put", action: "buy", strike: atm - 2 * w, ratio: 1 },
        { side: "put", action: "sell", strike: atm - w, ratio: 1 },
        { side: "call", action: "sell", strike: atm + w, ratio: 1 },
        { side: "call", action: "buy", strike: atm + 2 * w, ratio: 1 },
      ];
    case "butterfly":
      // Long call butterfly: +1 wing, −2 body, +1 wing.
      return [
        { side: "call", action: "buy", strike: atm - w, ratio: 1 },
        { side: "call", action: "sell", strike: atm, ratio: 2 },
        { side: "call", action: "buy", strike: atm + w, ratio: 1 },
      ];
    default:
      return [
        { side: "call", action: "buy", strike: atm, ratio: 1 },
        { side: "put", action: "buy", strike: atm, ratio: 1 },
      ];
  }
}

/**
 * Net premium of the structure per share (debit > 0, credit < 0), priced
 * off the live chain rows. Null when any leg's strike isn't on the fetched
 * grid or its price is unusable — callers must NOT guess direction then.
 * Exported for unit testing.
 */
export function netPremiumPerShare(
  rows: readonly Pick<ChainStrikeRow, "strike" | "call_price" | "put_price">[],
  legs: readonly MultiLegSpec[],
): number | null {
  if (!legs.length) return null;
  let net = 0;
  for (const leg of legs) {
    const row = rows.find((r) => r.strike === leg.strike);
    if (!row) return null;
    const price = leg.side === "call" ? row.call_price : row.put_price;
    if (!Number.isFinite(price) || price < 0) return null;
    net += (leg.action === "buy" ? 1 : -1) * price * (leg.ratio ?? 1);
  }
  return net;
}

function describeLegs(legs: MultiLegSpec[]): string {
  if (!legs.length) return "no legs";
  return legs
    .map(
      (l) =>
        `${l.action === "buy" ? "+" : "-"}${(l.ratio ?? 1) > 1 ? `${l.ratio}×` : ""}${l.strike}${l.side[0].toUpperCase()}`,
    )
    .join(" ");
}
