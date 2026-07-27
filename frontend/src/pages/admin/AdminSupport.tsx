import { useEffect, useState } from "react";
import {
  keepPreviousData,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";

import { relativeTime } from "@/components/positions/panelChrome";
import { LoadError } from "@/components/ui/LoadError";
import {
  ADMIN_TICKETS_PAGE_SIZE,
  adminKeys,
  errorMessage,
  fetchAdminTickets,
  updateAdminTicket,
  type AdminTicket,
  type TicketStatus,
} from "@/lib/adminApi";
import { toast } from "@/stores/toast";

import {
  Btn,
  Chip,
  Field,
  FilterChips,
  fmtDateTime,
  INPUT_CLS,
  NUM_CLS,
  Pager,
  Panel,
  SELECT_CLS,
  TEXTAREA_CLS,
  ticketStatusTone,
} from "./adminUi";

/**
 * Support — the admin ticket queue. Filter by status, expand a ticket to
 * read the body + auto-attached combine context, then reply (admin_note)
 * and/or move the status. Saving a non-empty note also notifies the
 * trader in-app server-side.
 */

type Filter = "all" | TicketStatus;

const FILTERS: { key: Filter; label: string }[] = [
  { key: "all", label: "All" },
  { key: "open", label: "Open" },
  { key: "replied", label: "Replied" },
  { key: "closed", label: "Closed" },
];

export function AdminSupport() {
  const [filter, setFilter] = useState<Filter>("open");
  const [input, setInput] = useState("");
  const [q, setQ] = useState("");
  const [page, setPage] = useState(1);
  const [expandedId, setExpandedId] = useState<number | null>(null);

  // Debounced search — typing shouldn't fire a request per keystroke.
  useEffect(() => {
    const t = setTimeout(() => {
      setQ(input.trim());
      setPage(1);
    }, 300);
    return () => clearTimeout(t);
  }, [input]);

  const status = filter === "all" ? undefined : filter;
  const tickets = useQuery({
    queryKey: adminKeys.tickets(status, q, page),
    queryFn: () => fetchAdminTickets(status, q, page),
    staleTime: 15_000,
    refetchInterval: 60_000,
    placeholderData: keepPreviousData,
  });

  return (
    <Panel
      label={
        <>
          Ticket queue{" "}
          {tickets.data && (
            <span className={`${NUM_CLS} text-fg-tertiary-2 normal-case`}>
              · {tickets.data.total}
            </span>
          )}
        </>
      }
      actions={
        <div className="flex items-center gap-2 flex-wrap justify-end">
          <input
            type="search"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Search subject or email…"
            className={`${INPUT_CLS} w-56 max-w-full`}
            style={{ fontSize: 12 }}
          />
          <FilterChips
            options={FILTERS}
            value={filter}
            onChange={(f) => {
              setFilter(f);
              setPage(1);
              setExpandedId(null);
            }}
          />
        </div>
      }
    >
      {tickets.isPending ? (
        <div className="px-3 py-4 text-tiny text-fg-tertiary-2">
          Loading tickets…
        </div>
      ) : tickets.isError ? (
        <LoadError subject="the ticket queue" onRetry={tickets.refetch} />
      ) : tickets.data.tickets.length === 0 ? (
        <div className="px-3 py-6 text-tiny text-fg-tertiary-2">
          {q
            ? `No tickets match “${q}”.`
            : filter === "open"
              ? "Inbox zero — no open tickets."
              : "No tickets here."}
        </div>
      ) : (
        <>
        <ul className="flex flex-col">
          {tickets.data.tickets.map((t) => (
            <li key={t.id} className="border-b border-hairline last:border-b-0">
              <button
                type="button"
                onClick={() => setExpandedId(expandedId === t.id ? null : t.id)}
                className={`w-full text-left px-3 py-2 flex items-center gap-2 flex-wrap ${
                  expandedId === t.id ? "bg-tier-2" : "hover:bg-tier-2"
                }`}
              >
                <Chip tone={ticketStatusTone(t.status)}>{t.status}</Chip>
                <Chip tone="muted">{t.category.replace("_", " ")}</Chip>
                <span className="text-tiny font-medium text-fg-primary truncate">
                  {t.subject}
                </span>
                <span className="text-tiny text-fg-tertiary-2 truncate">
                  {t.user_email}
                </span>
                <span
                  className={`ml-auto text-fg-tertiary-2 ${NUM_CLS} shrink-0`}
                  style={{ fontSize: 11 }}
                  title={fmtDateTime(t.created_at)}
                >
                  #{t.id} · {relativeTime(t.created_at)}
                </span>
              </button>
              {expandedId === t.id && <TicketWorkbench key={t.id} ticket={t} />}
            </li>
          ))}
        </ul>
        <Pager
          page={tickets.data.page}
          total={tickets.data.total}
          pageSize={ADMIN_TICKETS_PAGE_SIZE}
          onPage={(p) => {
            setPage(p);
            setExpandedId(null);
          }}
        />
        </>
      )}
    </Panel>
  );
}

// -- expanded ticket ------------------------------------------------------------

function TicketWorkbench({ ticket }: { ticket: AdminTicket }) {
  const qc = useQueryClient();
  const [note, setNote] = useState(ticket.admin_note ?? "");
  const [status, setStatus] = useState<TicketStatus>(
    (["open", "replied", "closed"] as const).includes(
      ticket.status as TicketStatus,
    )
      ? (ticket.status as TicketStatus)
      : "open",
  );

  const save = useMutation({
    mutationFn: () => {
      const payload: { status?: TicketStatus; admin_note?: string } = {};
      if (status !== ticket.status) payload.status = status;
      if (note !== (ticket.admin_note ?? "")) payload.admin_note = note;
      return updateAdminTicket(ticket.id, payload);
    },
    onSuccess: () => toast.success(`Ticket #${ticket.id} updated.`),
    onError: (e) => toast.error(errorMessage(e)),
    onSettled: () => {
      qc.invalidateQueries({ queryKey: adminKeys.ticketsPrefix });
      qc.invalidateQueries({ queryKey: adminKeys.metrics });
      qc.invalidateQueries({ queryKey: adminKeys.actionsPrefix });
    },
  });

  const dirty = status !== ticket.status || note !== (ticket.admin_note ?? "");
  const hasContext = Object.keys(ticket.context).length > 0;

  return (
    <div className="px-3 pb-3 pt-1 bg-tier-2 border-t border-hairline flex flex-col gap-3">
      <div className="text-tiny text-fg-secondary whitespace-pre-wrap leading-5 pt-2">
        {ticket.body}
      </div>
      {hasContext && (
        <div className="flex items-baseline gap-2 flex-wrap">
          <span
            className="uppercase tracking-label-up text-fg-tertiary-2"
            style={{ fontSize: 11 }}
          >
            Attached context
          </span>
          {Object.entries(ticket.context).map(([k, v]) => (
            <span key={k} className="text-tiny text-fg-secondary tabular-nums">
              {k}=<span className="text-fg-primary">{String(v)}</span>
            </span>
          ))}
        </div>
      )}
      <div className="grid gap-3 grid-cols-1 sm:grid-cols-[1fr_160px]">
        <Field label="Reply (admin note — the trader sees this)">
          <textarea
            value={note}
            maxLength={5000}
            onChange={(e) => setNote(e.target.value)}
            rows={3}
            placeholder="What we found and what happens next."
            className={TEXTAREA_CLS}
            style={{ fontSize: 12, minHeight: 72 }}
          />
        </Field>
        <Field label="Status">
          <select
            value={status}
            onChange={(e) => setStatus(e.target.value as TicketStatus)}
            className={SELECT_CLS}
            style={{ fontSize: 12 }}
          >
            <option value="open">open</option>
            <option value="replied">replied</option>
            <option value="closed">closed</option>
          </select>
        </Field>
      </div>
      <div className="flex justify-end">
        <Btn
          kind="primary"
          disabled={!dirty || save.isPending}
          onClick={() => save.mutate()}
        >
          {save.isPending ? "Saving…" : "Save reply"}
        </Btn>
      </div>
    </div>
  );
}
