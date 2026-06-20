import { useCancelOrder, useTrades } from "@/hooks/useTrades";
import type { Trade } from "@/types/journal";

/**
 * Resting limit/stop orders that haven't filled yet. The order monitor
 * fills them server-side when the option mark crosses the trigger; until
 * then they sit here with a cancel affordance. Polls every 8s so a
 * monitor-driven fill drops the row promptly. Renders nothing when empty.
 */
export function WorkingOrders() {
  const { data } = useTrades({ status: "working" }, { refetchInterval: 8_000 });
  const cancel = useCancelOrder();
  const orders = data?.trades ?? [];
  if (orders.length === 0) return null;

  return (
    <section
      className="border-t border-hairline bg-tier-0 shrink-0"
      aria-label="Working orders"
    >
      <div className="flex items-baseline justify-between px-3 pt-1.5">
        <span className="text-tiny uppercase tracking-label-up text-fg-secondary">
          Working orders
        </span>
        <span
          className="uppercase tracking-label-up text-fg-tertiary-2"
          style={{ fontSize: 11 }}
        >
          {orders.length} resting
        </span>
      </div>
      <div className="flex flex-col px-3 py-1 gap-1">
        {orders.map((o) => (
          <WorkingRow
            key={o.id}
            order={o}
            onCancel={() => cancel.mutate(o.id)}
            cancelling={cancel.isPending}
          />
        ))}
      </div>
    </section>
  );
}

function WorkingRow({
  order,
  onCancel,
  cancelling,
}: {
  order: Trade;
  onCancel: () => void;
  cancelling: boolean;
}) {
  const leg = order.legs[0];
  const side = leg?.side ?? "call";
  const action = leg?.action ?? "buy";
  return (
    <div className="flex items-center gap-2 tabular-nums" style={{ fontSize: 11 }}>
      <span
        className="uppercase tracking-label-up text-amber"
        style={{ fontSize: 11 }}
        title="Resting until the option mark crosses the trigger"
      >
        {order.order_type}
      </span>
      <span className="text-fg-primary">{order.symbol}</span>
      <span className="text-fg-tertiary-2">
        {action} {leg?.strike ?? ""} {side}
      </span>
      <span className="text-fg-secondary ml-auto">
        @ ${order.limit_price?.toFixed(2) ?? "—"}
      </span>
      <button
        type="button"
        onClick={onCancel}
        disabled={cancelling}
        aria-label="Cancel order"
        className="text-fg-tertiary hover:text-bearish disabled:opacity-50 leading-none"
        style={{ fontSize: 14 }}
      >
        ×
      </button>
    </div>
  );
}
