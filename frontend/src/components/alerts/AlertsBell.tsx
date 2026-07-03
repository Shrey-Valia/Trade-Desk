import { useState } from "react";

import { Modal } from "@/components/ui/Modal";
import {
  useAlerts,
  useCreateAlert,
  useDeleteAlert,
  useRearmAlert,
} from "@/hooks/useAlerts";
import type { Alert, AlertDirection } from "@/types/alert";

/**
 * Alerts bell + panel (WS6).
 *
 * A header affordance: a bell button badged with the count of active alerts
 * (and tinted bear-red when any have triggered), opening a modal to create,
 * list, re-arm, and delete price / earnings / fill alerts.
 *
 * Purely presentational — the 15s evaluation loop (useAlertEvaluator) is
 * mounted by RailShell so alerts keep firing on routes where this bell
 * isn't rendered.
 */
export function AlertsBell({ symbol }: { symbol: string | null }) {
  const [open, setOpen] = useState(false);
  const { data } = useAlerts();

  const alerts = data?.alerts ?? [];
  const activeCount = alerts.filter((a) => a.status === "active").length;
  const hasTriggered = alerts.some((a) => a.status === "triggered");

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        aria-label={`Alerts${activeCount ? ` (${activeCount} active)` : ""}`}
        title="Price & event alerts"
        className="relative h-9 w-9 flex items-center justify-center bg-tier-2 border border-tier-3 hover:bg-tier-3 rounded-btn text-fg-secondary hover:text-fg-primary"
      >
        <svg
          width={18}
          height={18}
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth={1.8}
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden
        >
          <path d="M18 8a6 6 0 0 0-12 0c0 7-3 9-3 9h18s-3-2-3-9" />
          <path d="M13.7 21a2 2 0 0 1-3.4 0" />
        </svg>
        {(activeCount > 0 || hasTriggered) && (
          <span
            className={`absolute -top-1 -right-1 min-w-[16px] h-4 px-1 rounded-full text-[10px] leading-4 text-white text-center ${
              hasTriggered ? "bg-bearish" : "bg-amber"
            }`}
          >
            {hasTriggered ? "!" : activeCount}
          </span>
        )}
      </button>
      <Modal
        open={open}
        onClose={() => setOpen(false)}
        labelledBy="alerts-panel-title"
        align="top"
        panelClassName="w-full max-w-md bg-tier-1 border border-hairline-strong rounded-btn shadow-2xl flex flex-col max-h-[80vh]"
      >
        <div className="flex items-center justify-between px-4 py-3 border-b border-hairline shrink-0">
          <h2 id="alerts-panel-title" className="text-medium font-medium text-fg-primary">
            Alerts
          </h2>
          <button
            type="button"
            onClick={() => setOpen(false)}
            aria-label="Close alerts"
            className="text-medium leading-none text-fg-secondary hover:text-fg-primary px-1"
          >
            ×
          </button>
        </div>
        <NewAlertForm symbol={symbol} />
        <AlertList alerts={alerts} />
      </Modal>
    </>
  );
}

function NewAlertForm({ symbol }: { symbol: string | null }) {
  const create = useCreateAlert();
  const [sym, setSym] = useState(symbol ?? "SPY");
  const [direction, setDirection] = useState<AlertDirection>("above");
  const [threshold, setThreshold] = useState<string>("");
  const [note, setNote] = useState("");

  const thresholdNum = parseFloat(threshold);
  const valid = sym.trim().length > 0 && Number.isFinite(thresholdNum) && thresholdNum > 0;

  return (
    <form
      className="px-4 py-3 border-b border-hairline shrink-0 flex flex-col gap-2"
      onSubmit={(e) => {
        e.preventDefault();
        if (!valid) return;
        create.mutate(
          {
            kind: "price",
            symbol: sym.trim().toUpperCase(),
            direction,
            threshold: thresholdNum,
            note: note.trim(),
          },
          {
            onSuccess: () => {
              setThreshold("");
              setNote("");
            },
          },
        );
      }}
    >
      <span className="text-tiny uppercase tracking-label-up text-fg-secondary">
        New price alert
      </span>
      <div className="flex items-center gap-2 tabular-nums">
        <label className="sr-only" htmlFor="alert-symbol">
          Symbol
        </label>
        <input
          id="alert-symbol"
          value={sym}
          onChange={(e) => setSym(e.target.value.toUpperCase())}
          placeholder="SPY"
          className="w-20 bg-tier-2 border border-tier-3 rounded-btn px-2 py-1.5 text-sm text-fg-primary uppercase"
        />
        <div className="flex" style={{ gap: 4 }}>
          {(["above", "below"] as const).map((d) => (
            <button
              key={d}
              type="button"
              onClick={() => setDirection(d)}
              aria-pressed={direction === d}
              className={[
                "uppercase tracking-label-up rounded-btn px-2 py-1.5 text-tiny",
                direction === d
                  ? "bg-tier-3 border border-amber text-amber"
                  : "bg-tier-2 border border-tier-3 text-fg-secondary hover:bg-tier-3",
              ].join(" ")}
            >
              {d}
            </button>
          ))}
        </div>
        <label className="sr-only" htmlFor="alert-threshold">
          Threshold price
        </label>
        <input
          id="alert-threshold"
          type="number"
          inputMode="decimal"
          min={0}
          step={0.01}
          value={threshold}
          onChange={(e) => setThreshold(e.target.value)}
          placeholder="price"
          className="flex-1 min-w-0 bg-tier-2 border border-tier-3 rounded-btn px-2 py-1.5 text-sm text-fg-primary text-right tabular-nums"
        />
      </div>
      <label className="sr-only" htmlFor="alert-note">
        Note
      </label>
      <input
        id="alert-note"
        value={note}
        onChange={(e) => setNote(e.target.value)}
        placeholder="Note (optional)"
        maxLength={160}
        className="bg-tier-2 border border-tier-3 rounded-btn px-2 py-1.5 text-sm text-fg-primary"
      />
      <button
        type="submit"
        disabled={!valid || create.isPending}
        className="self-end bg-action-buy hover:bg-action-buy-hover disabled:bg-tier-1 disabled:text-fg-disabled text-white rounded-btn px-3 py-1.5 text-sm font-medium"
      >
        {create.isPending ? "Adding…" : "Add alert"}
      </button>
    </form>
  );
}

function AlertList({ alerts }: { alerts: Alert[] }) {
  const del = useDeleteAlert();
  const rearm = useRearmAlert();

  if (alerts.length === 0) {
    return (
      <div className="px-4 py-6 text-sm text-fg-tertiary-2 text-center">
        No alerts yet. Add a price alert above.
      </div>
    );
  }

  return (
    <ul className="overflow-y-auto min-h-0 divide-y divide-hairline">
      {alerts.map((a) => {
        const triggered = a.status === "triggered";
        const cond =
          a.kind === "price"
            ? `${a.direction === "below" ? "≤" : "≥"} $${a.threshold}`
            : a.kind;
        return (
          <li key={a.id} className="flex items-center gap-2 px-4 py-2.5">
            <span
              className={`shrink-0 w-1.5 h-1.5 rounded-full ${
                triggered ? "bg-bearish" : "bg-bullish"
              }`}
              aria-hidden
            />
            <div className="flex-1 min-w-0">
              <div className="text-sm text-fg-primary tabular-nums">
                <span className="font-medium">{a.symbol}</span>{" "}
                <span className="text-fg-secondary">{cond}</span>
                {triggered && (
                  <span className="ml-2 text-tiny uppercase tracking-label-up text-bearish">
                    fired
                  </span>
                )}
              </div>
              {a.note && (
                <div className="text-tiny text-fg-tertiary-2 truncate">{a.note}</div>
              )}
            </div>
            {triggered && (
              <button
                type="button"
                onClick={() => rearm.mutate(a.id)}
                className="text-tiny text-cyan hover:underline shrink-0"
              >
                re-arm
              </button>
            )}
            <button
              type="button"
              onClick={() => del.mutate(a.id)}
              aria-label={`Delete alert for ${a.symbol}`}
              className="text-medium leading-none text-fg-tertiary hover:text-bearish shrink-0 px-1"
            >
              ×
            </button>
          </li>
        );
      })}
    </ul>
  );
}
