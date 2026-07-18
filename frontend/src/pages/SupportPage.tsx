import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { PageHeader } from "@/components/layout/PageHeader";
import { LoadError } from "@/components/ui/LoadError";
import {
  createSupportTicket,
  fetchSupportTickets,
  SUPPORT_TICKETS_KEY,
  TICKET_CATEGORIES,
  TICKET_CATEGORY_LABELS,
  type SupportTicket,
  type TicketCategory,
} from "@/lib/legalApi";
import { toast } from "@/stores/toast";

const SUBJECT_MAX = 160;
const BODY_MAX = 5000;

/**
 * /support — contact form + the user's own ticket list. Ticket creation
 * auto-attaches the active combine's context server-side, so the form
 * stays three fields. Admin replies land as `admin_note` on the ticket
 * (and as a bell notification via workstream D3).
 */
export function SupportPage() {
  return (
    <div className="flex flex-col h-full min-h-0 bg-tier-0">
      <PageHeader
        title="Support"
        subtitle="Rule disputes, billing, payouts, bugs"
      />
      <main className="flex-1 min-h-0 overflow-y-auto border-t border-hairline">
        <div
          className="mx-auto w-full p-3.5 flex flex-col gap-3.5"
          style={{ maxWidth: 860 }}
        >
          <NewTicketForm />
          <TicketList />
        </div>
      </main>
    </div>
  );
}

// -- contact form ---------------------------------------------------------

function NewTicketForm() {
  const qc = useQueryClient();
  const [category, setCategory] = useState<TicketCategory>("other");
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");

  const create = useMutation({
    mutationFn: createSupportTicket,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: SUPPORT_TICKETS_KEY });
      setSubject("");
      setBody("");
      toast.success("Ticket filed — we'll reply here.");
    },
    onError: (e) =>
      toast.error((e as Error)?.message || "Couldn't file the ticket."),
  });

  const canSubmit =
    subject.trim().length > 0 && body.trim().length > 0 && !create.isPending;

  const onSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!canSubmit) return;
    create.mutate({ category, subject: subject.trim(), body: body.trim() });
  };

  return (
    <form
      onSubmit={onSubmit}
      className="border border-hairline-strong bg-tier-1 flex flex-col"
      style={{ borderRadius: 4 }}
    >
      <div className="px-3.5 py-2.5 border-b border-hairline">
        <span className="text-tiny uppercase tracking-label-up text-fg-secondary">
          Contact support
        </span>
      </div>
      <div className="px-3.5 py-3 flex flex-col gap-3">
        <div className="grid gap-3 grid-cols-1 sm:grid-cols-[200px_1fr]">
          <Field label="Category">
            <select
              value={category}
              onChange={(e) => setCategory(e.target.value as TicketCategory)}
              className="h-9 px-2 bg-tier-2 border border-tier-3 rounded-btn text-fg-primary focus:border-amber focus:outline-none"
              style={{ fontSize: 13 }}
            >
              {TICKET_CATEGORIES.map((c) => (
                <option key={c} value={c}>
                  {TICKET_CATEGORY_LABELS[c]}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Subject">
            <input
              type="text"
              value={subject}
              maxLength={SUBJECT_MAX}
              onChange={(e) => setSubject(e.target.value)}
              placeholder="One line — what's this about?"
              className="h-9 px-2.5 bg-tier-2 border border-tier-3 rounded-btn text-fg-primary placeholder:text-fg-tertiary focus:border-amber focus:outline-none"
              style={{ fontSize: 13 }}
            />
          </Field>
        </div>
        <Field label="Details">
          <textarea
            value={body}
            maxLength={BODY_MAX}
            onChange={(e) => setBody(e.target.value)}
            rows={5}
            placeholder="What happened, which account, and what you expected. Rule disputes: include the trade or event you're disputing."
            className="px-2.5 py-2 bg-tier-2 border border-tier-3 rounded-btn text-fg-primary placeholder:text-fg-tertiary focus:border-amber focus:outline-none resize-y"
            style={{ fontSize: 13, lineHeight: "18px", minHeight: 96 }}
          />
        </Field>
        <div className="flex items-center justify-between gap-3">
          <span className="text-tiny text-fg-tertiary">
            Your active combine's details attach automatically.
          </span>
          <button
            type="submit"
            disabled={!canSubmit}
            className="h-9 px-4 uppercase tracking-label-up border border-amber text-amber bg-tier-2 hover:bg-tier-3 disabled:opacity-50 disabled:cursor-not-allowed rounded-btn font-medium"
            style={{ fontSize: 12 }}
          >
            {create.isPending ? "Filing…" : "File ticket"}
          </button>
        </div>
      </div>
    </form>
  );
}

function Field({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <label className="flex flex-col gap-1">
      <span
        className="uppercase tracking-label-up text-fg-tertiary-2"
        style={{ fontSize: 11, letterSpacing: "0.08em" }}
      >
        {label}
      </span>
      {children}
    </label>
  );
}

// -- ticket list ------------------------------------------------------------

function TicketList() {
  const { data, isPending, isError, refetch } = useQuery({
    queryKey: SUPPORT_TICKETS_KEY,
    queryFn: fetchSupportTickets,
    staleTime: 15_000,
  });

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-baseline gap-2">
        <span className="text-tiny uppercase tracking-label-up text-fg-secondary">
          Your tickets
        </span>
        {data && (
          <span className="text-tiny text-fg-tertiary-2 tabular-nums">
            {data.length}
          </span>
        )}
      </div>
      {isPending ? (
        <div className="px-1 py-4 text-tiny text-fg-tertiary-2">
          Loading tickets…
        </div>
      ) : isError ? (
        <LoadError subject="your tickets" onRetry={refetch} />
      ) : data.length === 0 ? (
        <div className="px-1 py-4 text-tiny text-fg-tertiary-2">
          No tickets yet — file one above and it shows up here with its
          status and our reply.
        </div>
      ) : (
        <div className="flex flex-col gap-2">
          {data.map((t) => (
            <TicketCard key={t.id} ticket={t} />
          ))}
        </div>
      )}
    </div>
  );
}

function TicketCard({ ticket }: { ticket: SupportTicket }) {
  const label =
    TICKET_CATEGORY_LABELS[ticket.category as TicketCategory] ??
    ticket.category;
  return (
    <div
      className="border border-hairline-strong bg-tier-1"
      style={{ borderRadius: 4 }}
    >
      <div className="px-3 py-2 border-b border-hairline flex items-center gap-2 flex-wrap">
        <StatusChip status={ticket.status} />
        <span
          className="border border-hairline-strong text-fg-tertiary-2 px-1 uppercase tracking-label-up"
          style={{ fontSize: 11, borderRadius: 2 }}
        >
          {label}
        </span>
        <span className="text-tiny font-medium text-fg-primary truncate">
          {ticket.subject}
        </span>
        <span className="ml-auto text-fg-tertiary-2 tabular-nums shrink-0" style={{ fontSize: 11 }}>
          #{ticket.id} · {formatDate(ticket.created_at)}
        </span>
      </div>
      <div className="px-3 py-2.5 text-tiny text-fg-secondary whitespace-pre-wrap leading-5">
        {ticket.body}
      </div>
      {ticket.admin_note && (
        <div className="mx-3 mb-3 border border-hairline bg-tier-2 px-3 py-2.5" style={{ borderRadius: 4 }}>
          <div
            className="uppercase tracking-label-up text-amber mb-1"
            style={{ fontSize: 11 }}
          >
            Support reply
          </div>
          <div className="text-tiny text-fg-secondary whitespace-pre-wrap leading-5">
            {ticket.admin_note}
          </div>
        </div>
      )}
    </div>
  );
}

/** open = amber (being worked), replied = bullish (answer waiting for
 *  you), closed = muted — the same tone language the combine cards use. */
function StatusChip({ status }: { status: string }) {
  const cls =
    status === "open"
      ? "border-amber text-amber"
      : status === "replied"
        ? "border-bullish text-bullish"
        : "border-hairline-strong text-fg-tertiary-2";
  return (
    <span
      className={`border px-1 uppercase tracking-label-up ${cls}`}
      style={{ fontSize: 11, borderRadius: 2 }}
    >
      {status}
    </span>
  );
}

function formatDate(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}
