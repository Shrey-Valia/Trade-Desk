import { useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { useCancelOrder, useTrades } from "@/hooks/useTrades";
import { linkOcoOrders, unlinkOcoOrders, updateWorkingOrder } from "@/lib/api";
import type { Trade, WorkingOrderPatch } from "@/types/journal";

/**
 * Resting limit/stop orders that haven't filled yet — the "pending" state.
 * The order monitor fills them server-side when the option mark crosses the
 * trigger; until then they sit here with edit + cancel affordances. Styled
 * with an amber accent + pulsing dot so a pending order is unmistakable (a
 * placed limit/stop is NOT an immediate fill). Polls every 8s so a
 * monitor-driven fill drops the row promptly. Renders nothing when empty.
 */
export function WorkingOrders() {
  const { data } = useTrades({ status: "working" }, { refetchInterval: 8_000 });
  const cancel = useCancelOrder();
  const queryClient = useQueryClient();
  const orders = data?.trades ?? [];

  // OCO linking: "link OCO" enters select mode; clicking rows toggles them;
  // LINK fires. The monitor already cancels siblings when one fills — this
  // is the missing UI to create the pairing.
  const [selecting, setSelecting] = useState(false);
  const [selected, setSelected] = useState<number[]>([]);
  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: ["journal", "trades"] });
  const link = useMutation({
    mutationFn: () => linkOcoOrders(selected),
    onSuccess: () => {
      invalidate();
      setSelecting(false);
      setSelected([]);
    },
    onError: invalidate, // 409 → a member filled underneath; reconcile
  });
  const unlink = useMutation({
    mutationFn: (ids: number[]) => unlinkOcoOrders(ids),
    onSuccess: invalidate,
  });
  if (orders.length === 0) return null;

  const toggle = (id: number) =>
    setSelected((prev) =>
      prev.includes(id)
        ? prev.filter((x) => x !== id)
        : prev.length < 4
          ? [...prev, id]
          : prev,
    );

  return (
    <section
      className="border-t-2 border-amber bg-tier-1 shrink-0"
      aria-label="Pending orders"
    >
      <div className="flex items-center justify-between px-3 pt-1.5">
        <span className="flex items-center gap-1.5 text-tiny uppercase tracking-label-up text-amber font-medium">
          <span className="inline-block w-1.5 h-1.5 rounded-full bg-amber animate-pulse" />
          Pending orders
        </span>
        <span className="flex items-center gap-2">
          {orders.length > 1 && !selecting && (
            <button
              type="button"
              onClick={() => setSelecting(true)}
              className="uppercase tracking-label-up text-fg-tertiary-2 hover:text-amber"
              style={{ fontSize: 10 }}
              title="Pick 2–4 working orders to pair: when one fills, the others are cancelled (one-cancels-the-other)"
            >
              link OCO
            </button>
          )}
          {selecting && (
            <>
              <button
                type="button"
                onClick={() => link.mutate()}
                disabled={selected.length < 2 || link.isPending}
                className="uppercase tracking-label-up text-amber border border-amber px-1 disabled:opacity-40"
                style={{ fontSize: 10 }}
              >
                link {selected.length}
              </button>
              <button
                type="button"
                onClick={() => {
                  setSelecting(false);
                  setSelected([]);
                }}
                className="uppercase tracking-label-up text-fg-tertiary-2 hover:text-fg-secondary"
                style={{ fontSize: 10 }}
              >
                cancel
              </button>
            </>
          )}
          <span
            className="uppercase tracking-label-up text-amber"
            style={{ fontSize: 11 }}
          >
            {orders.length} working · awaiting fill
          </span>
        </span>
      </div>
      <div className="flex flex-col px-3 py-1 gap-1">
        {orders.map((o) => (
          <WorkingRow
            key={o.id}
            order={o}
            onCancel={() => cancel.mutate(o.id)}
            cancelling={cancel.isPending}
            selecting={selecting}
            selected={selected.includes(o.id)}
            onToggleSelect={() => toggle(o.id)}
            onUnlinkGroup={(group) =>
              unlink.mutate(
                orders.filter((x) => x.oco_group === group).map((x) => x.id),
              )
            }
          />
        ))}
      </div>
    </section>
  );
}

/** Compact "+500C −505C" leg tape for a multi-leg working structure. */
export function describeWorkingLegs(legs: Trade["legs"]): string {
  return legs
    .map(
      (l) =>
        `${l.action === "buy" ? "+" : "−"}${
          (l.contracts ?? 1) > 1 ? `${l.contracts}×` : ""
        }${l.strike}${l.side === "call" ? "C" : "P"}`,
    )
    .join(" ");
}

/** "tp 2× · sl 0.5×" — the premium exits attached at open, if any. */
export function describePremiumMults(order: {
  tp_premium_mult?: number | null;
  sl_premium_mult?: number | null;
}): string | null {
  const parts: string[] = [];
  if (order.tp_premium_mult != null) parts.push(`tp ${order.tp_premium_mult}×`);
  if (order.sl_premium_mult != null) parts.push(`sl ${order.sl_premium_mult}×`);
  return parts.length ? parts.join(" · ") : null;
}

function WorkingRow({
  order,
  onCancel,
  cancelling,
  selecting = false,
  selected = false,
  onToggleSelect,
  onUnlinkGroup,
}: {
  order: Trade;
  onCancel: () => void;
  cancelling: boolean;
  /** OCO select mode: rows become click-to-toggle targets. */
  selecting?: boolean;
  selected?: boolean;
  onToggleSelect?: () => void;
  onUnlinkGroup?: (group: string) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [confirmCancel, setConfirmCancel] = useState(false);
  // A multi-leg structure's trigger is the NET premium (debit +, credit −);
  // single legs trade in plain option premium.
  const multiLeg = order.legs.length > 1;
  const leg = order.legs[0];
  const side = leg?.side ?? "call";
  const action = leg?.action ?? "buy";
  // Trigger resolution mirrors the chain overlay badge (useWorkingOrdersByStrike):
  // a stop order's resting level is its stop_price; limit/stop_limit rest at
  // limit_price. Falling back keeps the strip in step with the cell badge.
  const trigger = order.limit_price ?? order.stop_price ?? null;
  const triggerLabel =
    trigger == null
      ? "$—"
      : trigger < 0
        ? `$${Math.abs(trigger).toFixed(2)} credit`
        : `$${trigger.toFixed(2)}`;
  const mults = describePremiumMults(order);
  return (
    <div className="flex flex-col gap-1">
      <div
        className={[
          "flex items-center gap-2 tabular-nums",
          selecting ? "cursor-pointer" : "",
          selected ? "bg-tier-2 outline outline-1 outline-amber" : "",
        ].join(" ")}
        style={{ fontSize: 11 }}
        onClick={selecting ? onToggleSelect : undefined}
      >
        {selecting && (
          // The checkbox is the ☑/☐ indicator itself, not the row: a real
          // focusable button so Tab reaches it and Space/Enter toggle it,
          // and so the row's edit/oco/cancel buttons aren't nested inside a
          // checkbox role. Whole-row click still toggles for mouse users.
          <button
            type="button"
            role="checkbox"
            aria-checked={selected}
            aria-label={`Select ${order.symbol} ${order.order_type} order for OCO pairing`}
            onClick={(e) => {
              e.stopPropagation();
              onToggleSelect?.();
            }}
            className={[
              "leading-none",
              selected ? "text-amber" : "text-fg-tertiary hover:text-amber",
            ].join(" ")}
            style={{ fontSize: 10 }}
          >
            <span aria-hidden>{selected ? "☑" : "☐"}</span>
          </button>
        )}
        <span
          className="uppercase tracking-label-up text-amber border border-amber px-1 leading-none"
          style={{ fontSize: 10, paddingBlock: 1 }}
          title="Resting until the option mark crosses the trigger — not filled yet"
        >
          {multiLeg ? `net ${order.order_type}` : order.order_type}
        </span>
        {order.oco_group && (
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              onUnlinkGroup?.(order.oco_group as string);
            }}
            className="uppercase tracking-label-up text-cyan border border-cyan/60 px-1 leading-none hover:text-bearish hover:border-bearish"
            style={{ fontSize: 10, paddingBlock: 1 }}
            title="OCO-linked: when a sibling fills, this order is cancelled. Click to unlink the group."
          >
            oco
          </button>
        )}
        <span className="text-fg-primary">{order.symbol}</span>
        <span className="text-fg-tertiary-2">
          {multiLeg
            ? `${order.strategy.replace(/_/g, " ")} ${describeWorkingLegs(order.legs)}`
            : `${action} ${leg?.strike ?? ""} ${side}`}
        </span>
        {mults && (
          <span
            className="text-fg-tertiary-2"
            style={{ fontSize: 10 }}
            title="Premium exits attached at open — TP/SL as multiples of the entry premium"
          >
            {mults}
          </span>
        )}
        <span
          className="text-amber ml-auto"
          title={
            multiLeg
              ? "Waiting for the structure's NET mark to reach this price (debit positive, credit negative)"
              : "Waiting for the mark to reach this trigger"
          }
        >
          waiting @ {triggerLabel}
        </span>
        <button
          type="button"
          onClick={() => setEditing((e) => !e)}
          aria-pressed={editing}
          aria-label="Edit order"
          className={[
            "uppercase tracking-label-up leading-none px-1 transition-colors duration-100",
            editing ? "text-amber" : "text-fg-tertiary hover:text-amber",
          ].join(" ")}
          style={{ fontSize: 10 }}
        >
          edit
        </button>
        {confirmCancel ? (
          <span className="flex items-center gap-1.5 leading-none">
            <button
              type="button"
              onClick={onCancel}
              disabled={cancelling}
              aria-label="Confirm cancel order"
              className="uppercase tracking-label-up text-bearish hover:text-bearish disabled:opacity-50"
              style={{ fontSize: 10 }}
            >
              cancel?
            </button>
            <button
              type="button"
              onClick={() => setConfirmCancel(false)}
              aria-label="Keep order"
              className="uppercase tracking-label-up text-fg-tertiary hover:text-fg-primary"
              style={{ fontSize: 10 }}
            >
              keep
            </button>
          </span>
        ) : (
          <button
            type="button"
            onClick={() => setConfirmCancel(true)}
            disabled={cancelling}
            aria-label="Cancel order"
            className="text-fg-tertiary hover:text-bearish disabled:opacity-50 leading-none"
            style={{ fontSize: 14 }}
          >
            ×
          </button>
        )}
      </div>
      {editing && (
        <EditOrderForm order={order} onClose={() => setEditing(false)} />
      )}
    </div>
  );
}

/**
 * Inline modify form for a WORKING order — new trigger price(s) + TIF, saved
 * via PATCH /api/journal/trades/{id}/order. Field set follows the order type:
 *   - limit / stop  → one trigger (rests at limit_price; a stop's level is
 *     also stored there, mirroring the ticket)
 *   - stop_limit    → arm (stop_price) + resting limit (limit_price)
 * A multi-leg net limit may be negative (credit), so its input is unclamped.
 * A 409 (filled/cancelled while editing) surfaces the backend detail verbatim.
 */
function EditOrderForm({ order, onClose }: { order: Trade; onClose: () => void }) {
  const qc = useQueryClient();
  const multiLeg = order.legs.length > 1;
  const hasStop = order.order_type === "stop_limit";
  const [limitPrice, setLimitPrice] = useState<number | null>(
    order.limit_price ?? null,
  );
  const [stopPrice, setStopPrice] = useState<number | null>(
    order.stop_price ?? null,
  );
  const [tif, setTif] = useState<"day" | "gtc">(order.time_in_force);

  const mutation = useMutation({
    mutationFn: (patch: WorkingOrderPatch) => updateWorkingOrder(order.id, patch),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["journal", "trades"] });
      onClose();
    },
  });

  // Single-leg premiums must be > 0; a multi-leg NET limit may be 0/negative.
  const limitOk =
    limitPrice != null && Number.isFinite(limitPrice) && (multiLeg || limitPrice > 0);
  const stopOk = !hasStop || (stopPrice != null && stopPrice > 0);
  const canSave = limitOk && stopOk && !mutation.isPending;

  // Synchronous double-submit guard — mutation.isPending only flips next render,
  // so two fast clicks would both pass canSave and send two modify requests.
  const submittingRef = useRef(false);
  const save = () => {
    if (submittingRef.current || !canSave || limitPrice == null) return;
    submittingRef.current = true;
    mutation.mutate(
      {
        limit_price: limitPrice,
        ...(hasStop && stopPrice != null ? { stop_price: stopPrice } : {}),
        time_in_force: tif,
      },
      { onSettled: () => (submittingRef.current = false) },
    );
  };

  const limitLabel = multiLeg
    ? "net @"
    : order.order_type === "stop"
      ? "stop @"
      : "limit @";
  return (
    <div
      className="flex flex-col gap-1 pl-2 border-l border-amber tabular-nums"
      style={{ fontSize: 11 }}
    >
      <div className="flex items-center gap-2 flex-wrap">
        {hasStop && (
          <EditPriceInput
            label="arms @"
            ariaLabel="Edit stop arm price"
            value={stopPrice}
            onChange={setStopPrice}
          />
        )}
        <EditPriceInput
          label={limitLabel}
          ariaLabel="Edit limit price"
          value={limitPrice}
          onChange={setLimitPrice}
          allowNegative={multiLeg}
        />
        <span className="flex items-center gap-1">
          <span
            className="uppercase tracking-label-up text-fg-tertiary-2"
            style={{ fontSize: 10 }}
          >
            TIF
          </span>
          {(["day", "gtc"] as const).map((t) => (
            <button
              key={t}
              type="button"
              onClick={() => setTif(t)}
              aria-pressed={tif === t}
              title={
                t === "day"
                  ? "Day — cancelled at the next session if still unfilled"
                  : "GTC — rests until filled or cancelled"
              }
              className={[
                "uppercase tracking-label-up rounded-btn px-1.5 transition-colors duration-100 select-none",
                tif === t
                  ? "bg-tier-3 border border-amber text-amber"
                  : "bg-tier-2 border border-tier-3 text-fg-secondary hover:bg-tier-3 hover:text-fg-primary",
              ].join(" ")}
              style={{ height: 20, fontSize: 10 }}
            >
              {t}
            </button>
          ))}
        </span>
        <button
          type="button"
          onClick={save}
          disabled={!canSave}
          className={[
            "uppercase tracking-label-up rounded-btn px-2 font-semibold transition-colors duration-100",
            canSave
              ? "bg-tier-3 border border-amber text-amber hover:bg-amber hover:text-tier-0"
              : "bg-tier-1 border border-tier-2 text-fg-disabled cursor-not-allowed",
          ].join(" ")}
          style={{ height: 20, fontSize: 10 }}
        >
          {mutation.isPending ? "saving…" : "save"}
        </button>
        <button
          type="button"
          onClick={onClose}
          className="uppercase tracking-label-up text-fg-tertiary hover:text-fg-primary px-1"
          style={{ fontSize: 10 }}
        >
          cancel
        </button>
      </div>
      {mutation.isError && (
        <span
          className="text-bearish"
          role="alert"
          title={(mutation.error as Error)?.message}
        >
          {(mutation.error as Error)?.message}
        </span>
      )}
    </div>
  );
}

function EditPriceInput({
  label,
  ariaLabel,
  value,
  onChange,
  allowNegative = false,
}: {
  label: string;
  ariaLabel: string;
  value: number | null;
  onChange: (v: number | null) => void;
  allowNegative?: boolean;
}) {
  return (
    <label className="flex items-center gap-1">
      <span
        className="uppercase tracking-label-up text-fg-tertiary-2"
        style={{ fontSize: 10 }}
      >
        {label}
      </span>
      <input
        type="number"
        inputMode="decimal"
        {...(allowNegative ? {} : { min: 0 })}
        step={0.01}
        value={value ?? ""}
        onChange={(e) => {
          const v = parseFloat(e.target.value);
          onChange(Number.isFinite(v) ? v : null);
        }}
        placeholder="0.00"
        aria-label={ariaLabel}
        className="bg-tier-2 border border-tier-3 rounded-btn text-fg-primary tabular-nums text-right px-1"
        style={{ width: 60, height: 20, fontSize: 11 }}
      />
    </label>
  );
}
