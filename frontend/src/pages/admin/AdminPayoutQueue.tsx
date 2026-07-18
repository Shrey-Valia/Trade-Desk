import { Fragment, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { relativeTime } from "@/components/positions/panelChrome";
import { LoadError } from "@/components/ui/LoadError";
import {
  adminKeys,
  decidePayout,
  DENIAL_REASON_OPTIONS,
  errorMessage,
  fetchPayoutQueue,
  PAYOUT_STATES,
  type DenialReasonCode,
  type PayoutDecision,
  type PayoutQueueItem,
} from "@/lib/adminApi";
import { toast } from "@/stores/toast";

import {
  ActionModal,
  Btn,
  Chip,
  Field,
  FilterChips,
  fmtDateTime,
  fmtMoney,
  NUM_CLS,
  Panel,
  payoutStateTone,
  SELECT_CLS,
  TABLE_CLS,
  TABLE_FONT,
  TD_CLS,
  TEXTAREA_CLS,
  TH_CLS,
} from "./adminUi";

/**
 * Payouts — the human review desk. Default view is the actionable queue
 * (requested / under_review / held) in FIFO order; a row expands into the
 * reviewer context (balance, lifetime approved, days funded) and the
 * decision buttons. Deny REQUIRES a reason code (the backend 422s without
 * one). No optimistic writes: every decision invalidates + refetches, and
 * a 409 "invalid_transition" (someone else decided first) lands as a toast
 * over the refreshed truth.
 */

type Filter = "queue" | (typeof PAYOUT_STATES)[number];

const FILTERS: { key: Filter; label: string }[] = [
  { key: "queue", label: "Queue" },
  ...PAYOUT_STATES.map((s) => ({
    key: s as Filter,
    label: s.replace("_", " "),
  })),
];

export function AdminPayoutQueue() {
  const qc = useQueryClient();
  const [filter, setFilter] = useState<Filter>("queue");
  const [expandedId, setExpandedId] = useState<number | null>(null);
  const [denyTarget, setDenyTarget] = useState<PayoutQueueItem | null>(null);

  const state = filter === "queue" ? undefined : filter;
  const queue = useQuery({
    queryKey: adminKeys.payouts(state),
    queryFn: () => fetchPayoutQueue(state),
    staleTime: 10_000,
    refetchInterval: 30_000,
  });

  const decide = useMutation({
    mutationFn: (vars: {
      id: number;
      decision: PayoutDecision;
      reason_code?: DenialReasonCode;
      note?: string;
    }) =>
      decidePayout(vars.id, vars.decision, {
        reason_code: vars.reason_code,
        note: vars.note,
      }),
    onSuccess: (updated, vars) => {
      toast.success(
        `Payout #${updated.id} — ${vars.decision.replace("-", " ")} → ${updated.state.replace("_", " ")}.`,
      );
      setDenyTarget(null);
    },
    onError: (e) => toast.error(errorMessage(e)),
    // Refetch on success AND failure — a 409 invalid_transition means the
    // row moved underneath us and the table must show the new truth.
    onSettled: () => {
      qc.invalidateQueries({ queryKey: adminKeys.payoutsPrefix });
      qc.invalidateQueries({ queryKey: adminKeys.metrics });
      qc.invalidateQueries({ queryKey: adminKeys.actionsPrefix });
    },
  });

  return (
    <div className="flex flex-col gap-3">
      <Panel
        label={
          <>
            Payout review{" "}
            {queue.data && (
              <span className={`${NUM_CLS} text-fg-tertiary-2 normal-case`}>
                · {queue.data.total}
              </span>
            )}
          </>
        }
        actions={
          <FilterChips options={FILTERS} value={filter} onChange={(f) => {
            setFilter(f);
            setExpandedId(null);
          }} />
        }
      >
        {queue.isPending ? (
          <div className="px-3 py-4 text-tiny text-fg-tertiary-2">
            Loading the queue…
          </div>
        ) : queue.isError ? (
          <LoadError subject="the payout queue" onRetry={queue.refetch} />
        ) : queue.data.items.length === 0 ? (
          <div className="px-3 py-6 text-tiny text-fg-tertiary-2">
            {filter === "queue"
              ? "Queue clear — nothing awaiting review."
              : `No ${filter.replace("_", " ")} requests.`}
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className={TABLE_CLS} style={TABLE_FONT}>
              <thead>
                <tr>
                  <th className={TH_CLS}>#</th>
                  <th className={TH_CLS}>Requested</th>
                  <th className={TH_CLS}>Trader</th>
                  <th className={TH_CLS}>Account</th>
                  <th className={`${TH_CLS} text-right`}>Amount</th>
                  <th className={`${TH_CLS} text-right`}>Balance</th>
                  <th className={`${TH_CLS} text-right`}>Lifetime paid+appr.</th>
                  <th className={`${TH_CLS} text-right`}>Days funded</th>
                  <th className={TH_CLS}>State</th>
                </tr>
              </thead>
              <tbody>
                {queue.data.items.map((item) => (
                  <Fragment key={item.id}>
                    <tr
                      onClick={() =>
                        setExpandedId(expandedId === item.id ? null : item.id)
                      }
                      className={`cursor-pointer ${
                        expandedId === item.id ? "bg-tier-2" : "hover:bg-tier-2"
                      }`}
                    >
                      <td className={`${TD_CLS} ${NUM_CLS}`}>{item.id}</td>
                      <td className={TD_CLS} title={fmtDateTime(item.requested_at)}>
                        {relativeTime(item.requested_at)}
                      </td>
                      <td className={`${TD_CLS} text-fg-primary`}>
                        {item.user_email}
                      </td>
                      <td className={TD_CLS}>
                        <span className="uppercase">{item.tier}</span>{" "}
                        <span className={`${NUM_CLS} text-fg-tertiary-2`}>
                          {item.account_code}
                        </span>
                      </td>
                      <td
                        className={`${TD_CLS} ${NUM_CLS} text-right text-fg-primary font-medium`}
                      >
                        {fmtMoney(item.amount)}
                      </td>
                      <td className={`${TD_CLS} ${NUM_CLS} text-right`}>
                        {fmtMoney(item.balance)}
                      </td>
                      <td className={`${TD_CLS} ${NUM_CLS} text-right`}>
                        {fmtMoney(item.total_approved_payouts)}
                      </td>
                      <td className={`${TD_CLS} ${NUM_CLS} text-right`}>
                        {item.days_since_funded ?? "—"}
                      </td>
                      <td className={TD_CLS}>
                        <Chip tone={payoutStateTone(item.state)}>
                          {item.state.replace("_", " ")}
                        </Chip>
                      </td>
                    </tr>
                    {expandedId === item.id && (
                      <tr className="bg-tier-2">
                        <td colSpan={9} className="border-b border-hairline px-3 py-3">
                          <ReviewPane
                            item={item}
                            pending={decide.isPending}
                            onDecide={(decision) =>
                              decision === "deny"
                                ? setDenyTarget(item)
                                : decide.mutate({ id: item.id, decision })
                            }
                          />
                        </td>
                      </tr>
                    )}
                  </Fragment>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>

      <DenyModal
        // Remount per target so a prior deny's reason/note never leak in.
        key={denyTarget?.id ?? "closed"}
        target={denyTarget}
        pending={decide.isPending}
        onClose={() => setDenyTarget(null)}
        onDeny={(reasonCode, note) =>
          denyTarget &&
          decide.mutate({
            id: denyTarget.id,
            decision: "deny",
            reason_code: reasonCode,
            note: note || undefined,
          })
        }
      />
    </div>
  );
}

// -- expanded review pane -----------------------------------------------------

/** Which decision buttons a state offers (backend state machine mirror —
 *  requested/under_review/held are decidable; held un-parks via resume;
 *  approved closes via mark-paid; denied/paid are terminal). */
function actionsFor(state: string): PayoutDecision[] {
  switch (state) {
    case "requested":
    case "under_review":
      return ["approve", "hold", "deny"];
    case "held":
      return ["approve", "resume", "deny"];
    case "approved":
      return ["mark-paid"];
    default:
      return [];
  }
}

const DECISION_LABEL: Record<PayoutDecision, string> = {
  approve: "Approve",
  deny: "Deny…",
  hold: "Hold",
  resume: "Resume review",
  "mark-paid": "Mark paid",
};

const DECISION_KIND: Record<PayoutDecision, "success" | "danger" | "ghost" | "primary"> = {
  approve: "success",
  deny: "danger",
  hold: "ghost",
  resume: "ghost",
  "mark-paid": "primary",
};

function ReviewPane({
  item,
  pending,
  onDecide,
}: {
  item: PayoutQueueItem;
  pending: boolean;
  onDecide: (decision: PayoutDecision) => void;
}) {
  const actions = actionsFor(item.state);
  return (
    <div className="flex flex-col gap-3" style={{ fontSize: 12 }}>
      <div className="grid gap-x-6 gap-y-1.5 grid-cols-2 sm:grid-cols-4">
        <ContextStat label="Starting balance" value={fmtMoney(item.starting_balance)} />
        <ContextStat
          label="Current balance"
          value={fmtMoney(item.balance)}
          tone={item.balance - item.starting_balance >= 0 ? "bullish" : "bearish"}
        />
        <ContextStat
          label="Lifetime approved"
          value={fmtMoney(item.total_approved_payouts)}
        />
        <ContextStat
          label="Days funded"
          value={item.days_since_funded != null ? String(item.days_since_funded) : "—"}
        />
        <ContextStat label="Requested" value={fmtDateTime(item.requested_at)} />
        <ContextStat label="Decided" value={fmtDateTime(item.decided_at)} />
        <ContextStat
          label="Reviewer"
          value={item.reviewer_id != null ? `admin #${item.reviewer_id}` : "—"}
        />
        <ContextStat
          label="Reason code"
          value={item.reason_code ? item.reason_code.replace(/_/g, " ") : "—"}
        />
      </div>
      {item.note && (
        <div className="text-tiny text-fg-secondary">
          <span className="uppercase tracking-label-up text-fg-tertiary-2 mr-2" style={{ fontSize: 11 }}>
            Note
          </span>
          {item.note}
        </div>
      )}
      {actions.length > 0 && (
        <div className="flex gap-2 flex-wrap pt-1">
          {actions.map((d) => (
            <Btn
              key={d}
              kind={DECISION_KIND[d]}
              disabled={pending}
              onClick={(e) => {
                e.stopPropagation();
                onDecide(d);
              }}
            >
              {DECISION_LABEL[d]}
            </Btn>
          ))}
        </div>
      )}
    </div>
  );
}

function ContextStat({
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
        : "text-fg-primary";
  return (
    <div className="flex flex-col">
      <span
        className="uppercase tracking-label-up text-fg-tertiary-2"
        style={{ fontSize: 11 }}
      >
        {label}
      </span>
      <span className={`${NUM_CLS} ${cls}`}>{value}</span>
    </div>
  );
}

// -- deny modal ----------------------------------------------------------------

function DenyModal({
  target,
  pending,
  onClose,
  onDeny,
}: {
  target: PayoutQueueItem | null;
  pending: boolean;
  onClose: () => void;
  onDeny: (reasonCode: DenialReasonCode, note: string) => void;
}) {
  const [reasonCode, setReasonCode] = useState<DenialReasonCode | "">("");
  const [note, setNote] = useState("");
  // "other" is only meaningful with a note explaining it.
  const noteRequired = reasonCode === "other";
  const canDeny = reasonCode !== "" && (!noteRequired || note.trim().length > 0);

  const close = () => {
    setReasonCode("");
    setNote("");
    onClose();
  };

  return (
    <ActionModal
      open={target !== null}
      onClose={close}
      title={target ? `Deny payout #${target.id}` : "Deny payout"}
      description={
        target
          ? `${fmtMoney(target.amount)} returns to ${target.user_email}'s account balance. The trader sees the reason below.`
          : undefined
      }
      confirmLabel="Deny payout"
      confirmKind="danger"
      disabled={!canDeny}
      pending={pending}
      onConfirm={() => reasonCode && onDeny(reasonCode, note.trim())}
    >
      <Field label="Reason code (required)">
        <select
          value={reasonCode}
          onChange={(e) => setReasonCode(e.target.value as DenialReasonCode | "")}
          className={SELECT_CLS}
          style={{ fontSize: 12 }}
        >
          <option value="">Select a reason…</option>
          {DENIAL_REASON_OPTIONS.map((o) => (
            <option key={o.code} value={o.code}>
              {o.label}
            </option>
          ))}
        </select>
      </Field>
      <Field label={noteRequired ? "Reviewer note (required for Other)" : "Reviewer note (optional)"}>
        <textarea
          value={note}
          maxLength={300}
          onChange={(e) => setNote(e.target.value)}
          rows={3}
          placeholder="Specifics the audit trail should carry."
          className={TEXTAREA_CLS}
          style={{ fontSize: 12, minHeight: 64 }}
        />
      </Field>
    </ActionModal>
  );
}
