import { useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { relativeTime } from "@/components/positions/panelChrome";
import { LoadError } from "@/components/ui/LoadError";
import { adminKeys, fetchJobsHealth } from "@/lib/adminApi";

import {
  Chip,
  fmtDateTime,
  NUM_CLS,
  Panel,
  TABLE_CLS,
  TABLE_FONT,
  TD_CLS,
  TH_CLS,
} from "./adminUi";

/**
 * Jobs — scheduler health. One row per job (its latest JobRun): ok/error
 * status, the stale flag ("this job silently stopped running"), duration,
 * last run, and the error text (truncated, expandable). Auto-refreshes —
 * this page is what you stare at during an incident.
 */

const ERROR_TRUNCATE = 90;

export function AdminJobs() {
  const [expanded, setExpanded] = useState<string | null>(null);
  const jobs = useQuery({
    queryKey: adminKeys.jobs,
    queryFn: fetchJobsHealth,
    staleTime: 10_000,
    refetchInterval: 30_000,
  });

  return (
    <Panel
      label={
        <>
          Scheduled jobs{" "}
          {jobs.data && (
            <span className={`${NUM_CLS} text-fg-tertiary-2 normal-case`}>
              · {jobs.data.length}
            </span>
          )}
        </>
      }
    >
      {jobs.isPending ? (
        <div className="px-3 py-4 text-tiny text-fg-tertiary-2">
          Loading job health…
        </div>
      ) : jobs.isError ? (
        <LoadError subject="job health" onRetry={jobs.refetch} />
      ) : jobs.data.length === 0 ? (
        <div className="px-3 py-6 text-tiny text-fg-tertiary-2">
          No job runs recorded yet — the scheduler writes a JobRun per pass.
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className={TABLE_CLS} style={TABLE_FONT}>
            <thead>
              <tr>
                <th className={TH_CLS}>Job</th>
                <th className={TH_CLS}>Status</th>
                <th className={`${TH_CLS} text-right`}>Duration</th>
                <th className={TH_CLS}>Last run</th>
                <th className={`${TH_CLS} text-right`}>Cadence</th>
                <th className={TH_CLS}>Error</th>
              </tr>
            </thead>
            <tbody>
              {jobs.data.map((job) => {
                const isExpanded = expanded === job.name;
                const longError =
                  job.error != null && job.error.length > ERROR_TRUNCATE;
                return (
                  <tr
                    key={job.name}
                    className={job.stale ? "bg-tier-2" : "hover:bg-tier-2"}
                  >
                    <td className={`${TD_CLS} text-fg-primary`}>{job.name}</td>
                    <td className={TD_CLS}>
                      <span className="inline-flex gap-1">
                        <Chip tone={job.status === "ok" ? "bullish" : "bearish"}>
                          {job.status}
                        </Chip>
                        {job.stale && (
                          <Chip
                            tone="warning"
                            title="No run within 3× its cadence — the job may have silently died."
                          >
                            stale
                          </Chip>
                        )}
                      </span>
                    </td>
                    <td className={`${TD_CLS} ${NUM_CLS} text-right`}>
                      {job.duration_s.toFixed(2)}s
                    </td>
                    <td className={TD_CLS} title={fmtDateTime(job.started_at)}>
                      {relativeTime(job.started_at)}
                    </td>
                    <td className={`${TD_CLS} ${NUM_CLS} text-right`}>
                      {job.cadence_s != null ? fmtCadence(job.cadence_s) : "—"}
                    </td>
                    <td
                      className={`${TD_CLS} ${job.error ? "text-bearish" : "text-fg-tertiary-2"}`}
                      style={{ whiteSpace: "normal", maxWidth: 420 }}
                    >
                      {job.error == null ? (
                        "—"
                      ) : (
                        <>
                          <span className="break-words">
                            {isExpanded || !longError
                              ? job.error
                              : `${job.error.slice(0, ERROR_TRUNCATE)}…`}
                          </span>
                          {longError && (
                            <button
                              type="button"
                              onClick={() =>
                                setExpanded(isExpanded ? null : job.name)
                              }
                              className="ml-1 underline text-amber hover:opacity-80"
                              style={{ fontSize: 11 }}
                            >
                              {isExpanded ? "less" : "more"}
                            </button>
                          )}
                        </>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </Panel>
  );
}

function fmtCadence(seconds: number): string {
  if (seconds < 60) return `${seconds}s`;
  if (seconds < 3600) return `${Math.round(seconds / 60)}m`;
  if (seconds < 86_400) return `${Math.round(seconds / 3600)}h`;
  return `${Math.round(seconds / 86_400)}d`;
}
