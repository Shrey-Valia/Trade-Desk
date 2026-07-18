import { Fragment, useState } from "react";
import { keepPreviousData, useQuery } from "@tanstack/react-query";

import { relativeTime } from "@/components/positions/panelChrome";
import { LoadError } from "@/components/ui/LoadError";
import {
  ADMIN_ACTIONS_PAGE_SIZE,
  adminKeys,
  AUDIT_TARGET_TYPES,
  fetchAdminActions,
} from "@/lib/adminApi";

import {
  fmtDateTime,
  INPUT_CLS,
  NUM_CLS,
  Pager,
  Panel,
  SELECT_CLS,
  TABLE_CLS,
  TABLE_FONT,
  TD_CLS,
  TH_CLS,
} from "./adminUi";

/**
 * Audit — the append-only AdminAction log; how "who changed this account
 * and why" gets answered during a dispute. Filter by target, page through
 * newest-first, expand a row for the before → after JSON diff (two plain
 * <pre> blocks — deliberately simple).
 */
export function AdminAudit() {
  const [targetType, setTargetType] = useState("");
  const [targetIdInput, setTargetIdInput] = useState("");
  const [page, setPage] = useState(1);
  const [expandedId, setExpandedId] = useState<number | null>(null);

  const targetId = /^\d+$/.test(targetIdInput.trim())
    ? Number(targetIdInput.trim())
    : undefined;

  const actions = useQuery({
    queryKey: adminKeys.actions(targetType, targetIdInput.trim(), page),
    queryFn: () =>
      fetchAdminActions({
        targetType: targetType || undefined,
        targetId,
        page,
      }),
    staleTime: 15_000,
    placeholderData: keepPreviousData,
  });

  return (
    <Panel
      label={
        <>
          Admin actions{" "}
          {actions.data && (
            <span className={`${NUM_CLS} text-fg-tertiary-2 normal-case`}>
              · {actions.data.total}
            </span>
          )}
        </>
      }
      actions={
        <div className="flex items-center gap-2">
          <select
            value={targetType}
            onChange={(e) => {
              setTargetType(e.target.value);
              setPage(1);
            }}
            className={SELECT_CLS}
            style={{ fontSize: 12 }}
            aria-label="Filter by target type"
          >
            <option value="">All targets</option>
            {AUDIT_TARGET_TYPES.map((t) => (
              <option key={t} value={t}>
                {t.replace("_", " ")}
              </option>
            ))}
          </select>
          <input
            type="text"
            inputMode="numeric"
            value={targetIdInput}
            onChange={(e) => {
              setTargetIdInput(e.target.value);
              setPage(1);
            }}
            placeholder="Target id"
            className={`${INPUT_CLS} w-24 tabular-nums`}
            style={{ fontSize: 12 }}
            aria-label="Filter by target id"
          />
        </div>
      }
    >
      {actions.isPending ? (
        <div className="px-3 py-4 text-tiny text-fg-tertiary-2">
          Loading the audit log…
        </div>
      ) : actions.isError ? (
        <LoadError subject="the audit log" onRetry={actions.refetch} />
      ) : actions.data.items.length === 0 ? (
        <div className="px-3 py-6 text-tiny text-fg-tertiary-2">
          No admin actions match this filter.
        </div>
      ) : (
        <>
          <div className="overflow-x-auto">
            <table className={TABLE_CLS} style={TABLE_FONT}>
              <thead>
                <tr>
                  <th className={TH_CLS}>#</th>
                  <th className={TH_CLS}>When</th>
                  <th className={TH_CLS}>Actor</th>
                  <th className={TH_CLS}>Action</th>
                  <th className={TH_CLS}>Target</th>
                  <th className={TH_CLS}>Reason</th>
                </tr>
              </thead>
              <tbody>
                {actions.data.items.map((a) => (
                  <Fragment key={a.id}>
                    <tr
                      onClick={() =>
                        setExpandedId(expandedId === a.id ? null : a.id)
                      }
                      className={`cursor-pointer ${
                        expandedId === a.id ? "bg-tier-2" : "hover:bg-tier-2"
                      }`}
                    >
                      <td className={`${TD_CLS} ${NUM_CLS}`}>{a.id}</td>
                      <td className={TD_CLS} title={fmtDateTime(a.created_at)}>
                        {relativeTime(a.created_at)}
                      </td>
                      <td className={`${TD_CLS} ${NUM_CLS}`}>admin #{a.actor_id}</td>
                      <td className={`${TD_CLS} text-amber`}>{a.action}</td>
                      <td className={TD_CLS}>
                        {a.target_type.replace("_", " ")}
                        {a.target_id != null && (
                          <span className={NUM_CLS}> #{a.target_id}</span>
                        )}
                      </td>
                      <td
                        className={`${TD_CLS} ${a.reason ? "text-fg-secondary" : "text-fg-tertiary-2"}`}
                        style={{ whiteSpace: "normal", maxWidth: 360 }}
                      >
                        {a.reason ?? "—"}
                      </td>
                    </tr>
                    {expandedId === a.id && (
                      <tr className="bg-tier-2">
                        <td colSpan={6} className="border-b border-hairline px-3 py-3">
                          <div className="grid gap-3 grid-cols-1 sm:grid-cols-2">
                            <DiffBlock label="Before" value={a.before} />
                            <DiffBlock label="After" value={a.after} />
                          </div>
                        </td>
                      </tr>
                    )}
                  </Fragment>
                ))}
              </tbody>
            </table>
          </div>
          <Pager
            page={actions.data.page}
            total={actions.data.total}
            pageSize={ADMIN_ACTIONS_PAGE_SIZE}
            onPage={setPage}
          />
        </>
      )}
    </Panel>
  );
}

function DiffBlock({
  label,
  value,
}: {
  label: string;
  value: Record<string, unknown>;
}) {
  return (
    <div className="flex flex-col gap-1 min-w-0">
      <span
        className="uppercase tracking-label-up text-fg-tertiary-2"
        style={{ fontSize: 11 }}
      >
        {label}
      </span>
      <pre
        className="m-0 px-2.5 py-2 bg-tier-0 border border-hairline text-fg-secondary overflow-x-auto tabular-nums"
        style={{ fontSize: 11, lineHeight: "16px", borderRadius: 2 }}
      >
        {Object.keys(value).length === 0 ? "{}" : JSON.stringify(value, null, 2)}
      </pre>
    </div>
  );
}
