import { useEffect, useMemo, useRef, useState } from "react";

import { PayoffCurveSvg } from "@/components/analytics/PayoffCurveSvg";
import { useChainTable } from "@/hooks/useChainTable";
import { useMarketStatus } from "@/hooks/useMarket";
import { useMultiLegPreview } from "@/hooks/useMultiLegPreview";
import { useOpenZeroDteMultiLeg } from "@/hooks/useOpenZeroDteMultiLeg";
import type {
  ChainStrikeRow,
  MultiLegSpec,
  OpenMultiLegInput,
} from "@/types/zerodte";

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

type Preset =
  | "vertical"
  | "call_credit"
  | "put_debit"
  | "put_spread"
  | "strangle"
  | "iron_condor"
  | "iron_butterfly"
  | "butterfly"
  | "custom";

// Chip display labels — the internal keys stay stable (wire + tests), but the
// UI reads directionally: "vertical" is a bull call debit, "put_spread" a bull
// put credit, so pair them with explicit bear variants under clear names.
const PRESET_LABELS: Record<Preset, string> = {
  vertical: "call debit",
  call_credit: "call credit",
  put_debit: "put debit",
  put_spread: "put credit",
  strangle: "strangle",
  iron_condor: "iron condor",
  iron_butterfly: "iron fly",
  butterfly: "butterfly",
  custom: "custom",
};

// Order the chips: the four directional verticals first (bull/bear × call/put),
// then the multi-leg/neutral structures, then custom.
const PRESET_ORDER: Preset[] = [
  "vertical",
  "call_credit",
  "put_debit",
  "put_spread",
  "strangle",
  "iron_condor",
  "iron_butterfly",
  "butterfly",
  "custom",
];

type OrderType = "market" | "limit" | "stop" | "stop_limit";

const ORDER_TYPE_LABELS: Record<OrderType, string> = {
  market: "market",
  limit: "limit",
  stop: "stop",
  stop_limit: "stop lim",
};

const ORDER_TYPE_HELP: Record<OrderType, string> = {
  market: "Fill now at the server-priced net premium.",
  limit: "Rest until the structure's NET mark reaches your limit (pay at most / collect at least).",
  stop: "Rest until the structure's NET rises to your stop, then fill at the market.",
  stop_limit: "Arm when the NET rises to your stop, then rest as a limit at your limit price.",
};

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
  // Working-order type on the structure's NET mark: market fills now; limit /
  // stop / stop_limit rest until the net satisfies their trigger(s).
  const [orderType, setOrderType] = useState<
    "market" | "limit" | "stop" | "stop_limit"
  >("market");
  const [limitPrice, setLimitPrice] = useState<number | null>(null);
  const [stopPrice, setStopPrice] = useState<number | null>(null);
  // Once the user types a price we stop re-seeding it from the live net.
  const [limitDirty, setLimitDirty] = useState(false);
  const [stopDirty, setStopDirty] = useState(false);
  // Time-in-force for a working order (matches the ticket default).
  const [tif, setTif] = useState<"day" | "gtc">("day");
  // Optional trailing-stop EXIT carried onto the filled structure ($/share of
  // net, or a fraction of net entry premium). Mutually exclusive.
  const [trailAmount, setTrailAmount] = useState<number | null>(null);
  const [trailPct, setTrailPct] = useState<number | null>(null);

  const needsLimit = orderType === "limit" || orderType === "stop_limit";
  const needsStop = orderType === "stop" || orderType === "stop_limit";
  const isWorking = orderType !== "market";

  // Re-derive preset legs whenever the preset / ATM / step changes (but not in
  // custom mode, where the user owns the legs).
  useEffect(() => {
    if (preset === "custom") return;
    if (atm == null) return;
    setLegs(presetLegs(preset, atm, step));
  }, [preset, atm, step]);

  // Live net debit/credit of the structure off the chain — used to seed the
  // net-limit price below. (The builder no longer borrows the single-leg
  // ticket's premium-exit multipliers: they rode onto every structure
  // invisibly, and their debit/credit direction was derived from this CLIENT
  // net while the server re-derives it from the crossed-quote net, so a
  // near-zero-net structure could 400. Premium exits on a structure are a
  // future builder-local control, not a hidden inheritance.)
  const netPremium = useMemo(
    () => netPremiumPerShare(chain?.rows ?? [], legs),
    [chain, legs],
  );

  // Seed / track the NET trigger price(s) from the live computed net premium
  // until the user types their own value. Re-seeds as legs reprice so the
  // pre-fill stays honest, but never clobbers a hand-entered price.
  useEffect(() => {
    if (!needsLimit || limitDirty) return;
    setLimitPrice(netPremium != null ? +netPremium.toFixed(2) : null);
  }, [needsLimit, netPremium, limitDirty]);
  useEffect(() => {
    if (!needsStop || stopDirty) return;
    setStopPrice(netPremium != null ? +netPremium.toFixed(2) : null);
  }, [needsStop, netPremium, stopDirty]);

  // Live risk graph for the structure AS SUBMITTED (short legs negative):
  // payoff curves, breakevens, max profit/loss, POP — the missing half of
  // every builder that shows a leg list and fires blind.
  const preview = useMultiLegPreview(symbol, legs, contracts);

  // A no-0DTE day serves the NEAREST upcoming expiry (server fallback) —
  // fine for BROWSING, but this builder opens strictly-0DTE structures, so
  // firing would only 409 at the server after showing a live risk graph
  // (review wave 9, finding 10: the old chain 409 disabled the builder with
  // a reason; the fallback regressed that to fire-then-fail).
  const chainIsToday = chain?.expiry_is_today !== false;

  const canFire =
    marketOpen &&
    chainIsToday &&
    atm != null &&
    legs.length >= 2 &&
    !openMulti.isPending &&
    (!needsLimit || limitPrice != null) &&
    (!needsStop || stopPrice != null);

  // Synchronous double-submit guard: openMulti.isPending only flips on the next
  // render, so two fast clicks would both pass canFire and fire two identical
  // multi-leg orders (doubling exposure). The ref blocks the second click in
  // the same tick — same pattern as TradeTicket / QuickOrder.
  const submittingRef = useRef(false);
  const fire = () => {
    if (submittingRef.current || !canFire) return;
    const payload = multiLegOrderPayload({
      symbol,
      contracts,
      strategy: preset,
      legs,
      orderType,
      limitPrice,
      stopPrice,
      trailAmount,
      trailPct,
      timeInForce: tif,
      tp: null,
      sl: null,
    });
    if (!payload) return;
    submittingRef.current = true;
    openMulti.mutate(payload, {
      onSettled: () => {
        submittingRef.current = false;
      },
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
        {PRESET_ORDER.map((p) => (
          <button
            key={p}
            type="button"
            onClick={() => {
              setPreset(p);
              // New preset = new legs — a hand-entered net limit no longer
              // describes this structure, so fall back to live re-seeding.
              setLimitDirty(false);
            }}
            aria-pressed={preset === p}
            className={[
              "uppercase tracking-label-up transition-colors duration-100 select-none rounded-btn px-2",
              preset === p
                ? "bg-tier-3 border border-amber text-amber"
                : "bg-tier-2 border border-tier-3 text-fg-secondary hover:bg-tier-3 hover:text-fg-primary",
            ].join(" ")}
            style={{ height: 24, fontSize: 11 }}
          >
            {PRESET_LABELS[p]}
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

      {/* Risk graph — payoff at expiry + today, POP, extremes. */}
      {preview.data && (
        <div className="flex flex-col gap-0.5 border border-hairline bg-tier-1 px-1.5 pt-1 pb-1.5">
          <div style={{ height: 96 }}>
            <PayoffCurveSvg
              prices={preview.data.prices}
              payoffExpiration={preview.data.payoff_expiration}
              payoffToday={preview.data.payoff_today}
              breakevens={preview.data.breakevens}
              spot={preview.data.spot}
            />
          </div>
          <div
            className="flex items-center justify-between tabular-nums text-fg-secondary"
            style={{ fontSize: 11 }}
          >
            <span
              title="Probability of profit at expiry for the structure as submitted — risk-neutral Black-Scholes at the ATM IV."
            >
              POP{" "}
              <span className="text-fg-primary">
                {preview.data.pop_long != null
                  ? `${Math.round(preview.data.pop_long * 100)}%`
                  : "—"}
              </span>
            </span>
            <span className="text-bullish" title="Max profit at expiry">
              max{" "}
              {preview.data.max_profit == null
                ? "unl"
                : `+$${Math.abs(preview.data.max_profit).toFixed(0)}`}
            </span>
            <span className="text-bearish" title="Max loss at expiry">
              risk{" "}
              {preview.data.max_loss == null
                ? "unl"
                : `−$${Math.abs(preview.data.max_loss).toFixed(0)}`}
            </span>
            <span
              className="text-position"
              title="Breakeven underlying price(s) at expiry"
            >
              BE{" "}
              {preview.data.breakevens.length
                ? preview.data.breakevens.map((b) => b.toFixed(0)).join("/")
                : "—"}
            </span>
            <span
              className="text-fg-secondary"
              title="Buying power this structure holds against your balance (margin model: max loss for defined-risk, Reg-T-style for naked sides). The open gate enforces it."
            >
              BP{" "}
              {preview.data.bp_requirement_long == null
                ? "—"
                : `$${Math.round(preview.data.bp_requirement_long).toLocaleString()}`}
            </span>
          </div>
        </div>
      )}

      {/* Order type on the structure's NET mark: market fills now; limit /
          stop / stop-limit rest as a working order until the net triggers. */}
      <div className="flex flex-col gap-0.5">
        <div className="flex flex-wrap items-center gap-2">
          <div className="flex" style={{ gap: 4 }}>
            {(["market", "limit", "stop", "stop_limit"] as const).map((m) => (
              <button
                key={m}
                type="button"
                onClick={() => {
                  setOrderType(m);
                  setLimitDirty(false);
                  setStopDirty(false);
                }}
                aria-pressed={orderType === m}
                title={ORDER_TYPE_HELP[m]}
                className={[
                  "uppercase tracking-label-up transition-colors duration-100 select-none rounded-btn px-2",
                  orderType === m
                    ? "bg-tier-3 border border-amber text-amber"
                    : "bg-tier-2 border border-tier-3 text-fg-secondary hover:bg-tier-3 hover:text-fg-primary",
                ].join(" ")}
                style={{ height: 22, fontSize: 10 }}
              >
                {ORDER_TYPE_LABELS[m]}
              </button>
            ))}
          </div>
          {needsStop && (
            <NetPriceInput
              label="stop @"
              value={stopPrice}
              onChange={(v) => {
                setStopDirty(true);
                setStopPrice(v);
              }}
              ariaLabel="Net stop trigger (per-share net premium of the structure)"
            />
          )}
          {needsLimit && (
            <NetPriceInput
              label="limit @"
              value={limitPrice}
              onChange={(v) => {
                setLimitDirty(true);
                setLimitPrice(v);
              }}
              ariaLabel="Net limit price (per-share net premium of the structure)"
            />
          )}
          {isWorking && (
            <div className="flex" style={{ gap: 2 }}>
              {(["day", "gtc"] as const).map((t) => (
                <button
                  key={t}
                  type="button"
                  onClick={() => setTif(t)}
                  aria-pressed={tif === t}
                  title={
                    t === "day"
                      ? "Day order — cancelled if it doesn't fill this session."
                      : "Good-til-cancelled — rests until filled or cancelled."
                  }
                  className={[
                    "uppercase tracking-label-up transition-colors duration-100 select-none rounded-btn px-1.5",
                    tif === t
                      ? "bg-tier-3 border border-amber text-amber"
                      : "bg-tier-2 border border-tier-3 text-fg-secondary hover:bg-tier-3 hover:text-fg-primary",
                  ].join(" ")}
                  style={{ height: 22, fontSize: 10 }}
                >
                  {t}
                </button>
              ))}
            </div>
          )}
        </div>
        {isWorking && (
          <span className="text-fg-tertiary-2" style={{ fontSize: 10 }}>
            net premium per 1× structure — a debit you pay is positive, a
            credit you receive is negative
            {needsStop && "; a stop fills once the net rises to it"}
          </span>
        )}
      </div>

      {/* Optional trailing-stop EXIT carried onto the filled structure. */}
      <TrailControl
        trailAmount={trailAmount}
        trailPct={trailPct}
        setTrailAmount={setTrailAmount}
        setTrailPct={setTrailPct}
      />

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
          {openMulti.isPending
            ? "submitting…"
            : isWorking
              ? "place order"
              : "open structure"}
        </button>
      </div>

      {!marketOpen && (
        <span className="text-warning" style={{ fontSize: 11 }}>
          Market closed — structures open during the regular session.
        </span>
      )}
      {marketOpen && !chainIsToday && (
        <span className="text-warning" style={{ fontSize: 11 }}>
          No 0DTE for {symbol} today — the chain shows exp {chain?.expiry} for
          reference; structures open on today&rsquo;s expiry only.
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

/** Compact signed net-premium input (debit positive / credit negative). */
function NetPriceInput({
  label,
  value,
  onChange,
  ariaLabel,
}: {
  label: string;
  value: number | null;
  onChange: (v: number | null) => void;
  ariaLabel: string;
}) {
  return (
    <label className="flex items-center gap-1" style={{ fontSize: 11 }}>
      <span className="uppercase tracking-label-up text-fg-tertiary-2">{label}</span>
      <input
        type="number"
        inputMode="decimal"
        step={0.01}
        value={value ?? ""}
        onChange={(e) => {
          const v = parseFloat(e.target.value);
          onChange(Number.isFinite(v) ? v : null);
        }}
        placeholder="0.00"
        aria-label={ariaLabel}
        className="bg-tier-2 border border-tier-3 rounded-btn text-fg-primary tabular-nums text-right px-1.5"
        style={{ width: 64, height: 22, fontSize: 11 }}
      />
    </label>
  );
}

/** Optional trailing-stop EXIT on the structure's net mark ($/share or % of
 *  net entry premium). Mutually exclusive — the two are wired so only one is
 *  ever set. Applies once the structure is filled. */
function TrailControl({
  trailAmount,
  trailPct,
  setTrailAmount,
  setTrailPct,
}: {
  trailAmount: number | null;
  trailPct: number | null;
  setTrailAmount: (a: number | null) => void;
  setTrailPct: (p: number | null) => void;
}) {
  const on = trailAmount != null || trailPct != null;
  const mode: "amount" | "pct" = trailPct != null ? "pct" : "amount";
  return (
    <div className="flex items-center gap-2 tabular-nums" style={{ fontSize: 11 }}>
      <button
        type="button"
        onClick={() => {
          if (on) {
            setTrailAmount(null);
            setTrailPct(null);
          } else {
            setTrailAmount(0.1);
            setTrailPct(null);
          }
        }}
        aria-pressed={on}
        title="Attach a trailing-stop exit on the structure's net mark; it activates once the order fills."
        className={[
          "uppercase tracking-label-up transition-colors duration-100 select-none rounded-btn px-2",
          on
            ? "bg-tier-3 border border-amber text-amber"
            : "bg-tier-2 border border-tier-3 text-fg-secondary hover:bg-tier-3 hover:text-fg-primary",
        ].join(" ")}
        style={{ height: 22, fontSize: 10 }}
      >
        trail stop
      </button>
      {on && (
        <>
          <div className="flex" style={{ gap: 2 }}>
            {(["amount", "pct"] as const).map((m) => (
              <button
                key={m}
                type="button"
                onClick={() => {
                  if (m === mode) return;
                  if (m === "pct") {
                    setTrailPct(0.1);
                    setTrailAmount(null);
                  } else {
                    setTrailAmount(0.1);
                    setTrailPct(null);
                  }
                }}
                aria-pressed={mode === m}
                aria-label={m === "amount" ? "Trail by net dollars" : "Trail by percent of net entry premium"}
                className={[
                  "tracking-label-up transition-colors duration-100 select-none rounded-btn",
                  mode === m
                    ? "bg-tier-3 border border-amber text-amber"
                    : "bg-tier-2 border border-tier-3 text-fg-secondary hover:bg-tier-3 hover:text-fg-primary",
                ].join(" ")}
                style={{ height: 22, width: 24, fontSize: 11 }}
              >
                {m === "amount" ? "$" : "%"}
              </button>
            ))}
          </div>
          {mode === "amount" ? (
            <input
              type="number"
              inputMode="decimal"
              min={0.01}
              step={0.05}
              value={trailAmount ?? ""}
              onChange={(e) => {
                const v = parseFloat(e.target.value);
                setTrailAmount(Number.isFinite(v) && v > 0 ? v : null);
              }}
              aria-label="Trailing stop distance ($/share of net)"
              className="bg-tier-2 border border-tier-3 rounded-btn text-fg-primary tabular-nums text-right px-1.5"
              style={{ width: 56, height: 22, fontSize: 11 }}
            />
          ) : (
            <input
              type="number"
              inputMode="decimal"
              min={0.1}
              max={100}
              step={0.5}
              value={trailPct != null ? +(trailPct * 100).toFixed(2) : ""}
              onChange={(e) => {
                const pct = parseFloat(e.target.value);
                setTrailPct(
                  Number.isFinite(pct) && pct > 0 ? Math.min(1, pct / 100) : null,
                );
              }}
              aria-label="Trailing stop distance (% of net entry premium)"
              className="bg-tier-2 border border-tier-3 rounded-btn text-fg-primary tabular-nums text-right px-1.5"
              style={{ width: 56, height: 22, fontSize: 11 }}
            />
          )}
        </>
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
    case "call_credit":
      // Bear call CREDIT spread: sell the 1-strike-OTM call, buy the wing
      // above — profits when the underlying stays below the short strike.
      return [
        { side: "call", action: "sell", strike: atm + w, ratio: 1 },
        { side: "call", action: "buy", strike: atm + 2 * w, ratio: 1 },
      ];
    case "put_debit":
      // Bear put DEBIT spread: buy the ATM put, sell the wing below —
      // profits on a move down, capped at the lower strike.
      return [
        { side: "put", action: "buy", strike: atm, ratio: 1 },
        { side: "put", action: "sell", strike: atm - w, ratio: 1 },
      ];
    case "put_spread":
      // Bull put CREDIT spread: sell the 1-strike-OTM put, buy the wing
      // below — the most-traded defined-risk premium-selling structure.
      return [
        { side: "put", action: "sell", strike: atm - w, ratio: 1 },
        { side: "put", action: "buy", strike: atm - 2 * w, ratio: 1 },
      ];
    case "strangle":
      // Long strangle: OTM call + OTM put — the straddle's cheaper cousin.
      return [
        { side: "call", action: "buy", strike: atm + w, ratio: 1 },
        { side: "put", action: "buy", strike: atm - w, ratio: 1 },
      ];
    case "iron_condor":
      // Short put + call spreads bracketing ATM.
      return [
        { side: "put", action: "buy", strike: atm - 2 * w, ratio: 1 },
        { side: "put", action: "sell", strike: atm - w, ratio: 1 },
        { side: "call", action: "sell", strike: atm + w, ratio: 1 },
        { side: "call", action: "buy", strike: atm + 2 * w, ratio: 1 },
      ];
    case "iron_butterfly":
      // Short ATM straddle bracketed by long wings — a defined-risk,
      // higher-credit cousin of the condor (short strikes meet at ATM).
      return [
        { side: "put", action: "buy", strike: atm - 2 * w, ratio: 1 },
        { side: "put", action: "sell", strike: atm, ratio: 1 },
        { side: "call", action: "sell", strike: atm, ratio: 1 },
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

/**
 * Assemble the /open-multi payload. A MARKET open omits the working-order
 * fields entirely (wire-compatible with backends that predate them). A working
 * order (limit / stop / stop_limit) sends its net trigger(s) — the structure's
 * net premium per 1× ($/share): debit positive, credit negative — plus any
 * trailing-stop exit and time-in-force. Returns null when a required trigger
 * price is missing (callers must not fire). Exported for unit testing.
 */
export function multiLegOrderPayload(args: {
  symbol: string;
  contracts: number;
  strategy: string;
  legs: MultiLegSpec[];
  orderType: "market" | "limit" | "stop" | "stop_limit";
  limitPrice: number | null;
  stopPrice?: number | null;
  trailAmount?: number | null;
  trailPct?: number | null;
  timeInForce?: "day" | "gtc";
  tp: number | null;
  sl: number | null;
}): OpenMultiLegInput | null {
  const trail =
    args.trailAmount != null && args.trailAmount > 0
      ? { trail_amount: args.trailAmount }
      : args.trailPct != null && args.trailPct > 0
        ? { trail_pct: args.trailPct }
        : {};
  const base: OpenMultiLegInput = {
    symbol: args.symbol,
    contracts: args.contracts,
    strategy: args.strategy,
    legs: args.legs,
    tp_premium_mult: args.tp,
    sl_premium_mult: args.sl,
    ...trail,
  };
  if (args.orderType === "market") return base;

  const needsLimit = args.orderType === "limit" || args.orderType === "stop_limit";
  const needsStop = args.orderType === "stop" || args.orderType === "stop_limit";
  const limitOk = args.limitPrice != null && Number.isFinite(args.limitPrice);
  const stopOk = args.stopPrice != null && Number.isFinite(args.stopPrice);
  if (needsLimit && !limitOk) return null;
  if (needsStop && !stopOk) return null;

  return {
    ...base,
    order_type: args.orderType,
    limit_price: needsLimit ? args.limitPrice : null,
    stop_price: needsStop ? args.stopPrice ?? null : null,
    time_in_force: args.timeInForce ?? "day",
  };
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
