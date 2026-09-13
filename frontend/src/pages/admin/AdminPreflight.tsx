import { useQuery } from "@tanstack/react-query";

import { adminKeys, fetchPreflight, type PreflightFinding } from "@/lib/adminApi";

import { Chip, Panel, type Tone } from "./adminUi";

/**
 * Configuration preflight — what this deployment's settings actually mean.
 *
 * Renders NOTHING when there is nothing to say: outside production the
 * backend returns an empty list by design, and a correctly configured
 * deployment returns one too. An always-present panel reading "all clear"
 * is the kind of chrome operators stop seeing, and this is meant to be
 * noticed exactly when it matters.
 *
 * The same findings are logged at boot, but `fly logs` scrolls away within
 * minutes of a deploy while the settings they describe do not — so they
 * live here too, where an operator is already looking.
 */

const LEVEL_TONE: Record<PreflightFinding["level"], Tone> = {
  refuse: "breach",
  warn: "warning",
};

export function AdminPreflight() {
  const preflight = useQuery({
    queryKey: adminKeys.preflight,
    queryFn: fetchPreflight,
    staleTime: 60_000,
  });

  // Silent on load, on error, and when clean — this panel is additive
  // context, never something that can break the page it sits on.
  if (!preflight.isSuccess) return null;
  const { findings, is_production: isProduction } = preflight.data;
  if (findings.length === 0) return null;

  const refusals = findings.filter((f) => f.level === "refuse").length;

  return (
    <Panel
      label={
        <>
          Configuration{" "}
          <span className="text-warning normal-case">
            · {findings.length} finding{findings.length === 1 ? "" : "s"}
            {refusals > 0 ? ` · ${refusals} blocking` : ""}
          </span>
        </>
      }
    >
      <div className="px-3 pt-2 pb-1 text-tiny text-fg-tertiary-2">
        {isProduction
          ? "Settings whose value means something different in a deployment than on a laptop. Each one is a deliberate choice — this is the list to confirm you made it."
          : "Not a production deployment; these are informational."}
      </div>
      <ul className="flex flex-col divide-y divide-hairline">
        {findings.map((f) => (
          <li key={`${f.level}-${f.key}`} className="px-3 py-2.5">
            <div className="flex items-center gap-2">
              <Chip tone={LEVEL_TONE[f.level]}>
                {f.level === "refuse" ? "Blocking" : "Warning"}
              </Chip>
              <span
                className="uppercase tracking-label-up text-fg-primary"
                style={{ fontSize: 12 }}
              >
                {f.key}
              </span>
            </div>
            <p className="mt-1 text-tiny text-fg-secondary">{f.problem}</p>
            <p className="mt-0.5 text-tiny text-fg-tertiary-2">
              <span className="uppercase tracking-label-up">Fix</span> · {f.fix}
            </p>
          </li>
        ))}
      </ul>
    </Panel>
  );
}
