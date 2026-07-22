import type { ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";

import { useTickerMetrics } from "@/hooks/useTickerMetrics";
import { fetchTermStructure } from "@/lib/api";
import { TOOLTIPS } from "@/lib/tooltips";

/**
 * Compact "vol regime" readout — surfaces the IV-rank / skew / VRP math
 * that the backend already computes in GET /metrics but that was barely
 * visible in the UI. Sits next to the chart so the trader can read the
 * volatility regime at a glance:
 *
 *   IVR    — IV rank %, color-graded (high = rich premium, premium-sell
 *            territory; low = cheap premium).
 *   SKEW   — sign signal: PUT skew (downside bid) vs CALL skew.
 *   VRP    — direction: RICH (IV > RV, structural sell edge) vs CHEAP.
 *
 * Read-only, consumes the same /metrics query (cache-shared) that the
 * bottom strip uses, so it adds no request volume.
 */
export function VolRegimeStrip({ symbol }: { symbol: string | null }) {
  const { data } = useTickerMetrics(symbol);
  // ATM IV term structure (audit wave 4) — structural, slow-moving; 60s poll
  // rides the cached chain snapshot server-side.
  const { data: term } = useQuery({
    queryKey: ["zerodte", "term", symbol],
    queryFn: () => fetchTermStructure(symbol as string),
    enabled: !!symbol,
    staleTime: 60_000,
    refetchInterval: 60_000,
    retry: 1,
  });

  if (!symbol) return null;

  const ivRank = data?.iv_rank ?? null;
  const skew = data?.skew_25d ?? null;
  const vrp = data?.vrp ?? null;
  const termTitle =
    term && term.points.length
      ? "ATM IV per expiration:\n" +
        term.points
          .map(
            (p) =>
              `${p.dte === 0 ? "0DTE" : `${p.dte}d`} · ${
                p.atm_iv == null ? "—" : `${(p.atm_iv * 100).toFixed(1)}%`
              }`,
          )
          .join("\n") +
        "\n\nContango (far > near) is the normal state; backwardation means the front is pricing an event/stress — selling it is picking up the rich leg."
      : "ATM IV per expiration — appears once at least two expirations carry usable quotes.";

  return (
    <div
      className="flex items-center gap-3 px-3 border-t border-hairline tabular-nums"
      style={{ height: 20, fontSize: 12 }}
      role="group"
      aria-label="Volatility regime"
    >
      <span className="uppercase tracking-label-up text-fg-tertiary-2">
        vol regime
      </span>

      <Cell label="IVR" title={TOOLTIPS.iv_rank}>
        {ivRank == null ? (
          <span className="text-fg-tertiary">—</span>
        ) : (
          <span className={ivRankClass(ivRank)}>{ivRank.toFixed(0)}</span>
        )}
      </Cell>

      <Cell label="SKEW" title={TOOLTIPS.skew_25d}>
        {skew == null ? (
          <span className="text-fg-tertiary">—</span>
        ) : (
          <span className={skew > 0 ? "text-bearish" : "text-bullish"}>
            {skew > 0 ? "PUT" : skew < 0 ? "CALL" : "FLAT"}
          </span>
        )}
      </Cell>

      <Cell label="VRP" title={TOOLTIPS.vrp}>
        {vrp == null ? (
          <span className="text-fg-tertiary">—</span>
        ) : (
          <span className={vrp > 0 ? "text-bullish" : "text-bearish"}>
            {vrp > 0 ? "RICH" : vrp < 0 ? "CHEAP" : "FAIR"}
          </span>
        )}
      </Cell>

      <Cell label="TERM" title={termTitle}>
        {term?.shape == null ? (
          <span className="text-fg-tertiary">—</span>
        ) : (
          <span
            className={
              term.shape === "backwardation" ? "text-bearish" : "text-fg-primary"
            }
          >
            {term.shape === "contango"
              ? "CNTG ⬀"
              : term.shape === "backwardation"
                ? "BWD ⬂"
                : "FLAT"}
          </span>
        )}
      </Cell>
    </div>
  );
}

function Cell({
  label,
  title,
  children,
}: {
  label: string;
  title?: string;
  children: ReactNode;
}) {
  return (
    <span className="inline-flex items-baseline gap-1" title={title}>
      <span className="text-fg-tertiary-2">{label}</span>
      {children}
    </span>
  );
}

// IV rank color grade: high (>70) = rich premium, amber/active; mid =
// neutral; low (<30) = cheap. Uses semantic price tokens for the bands.
function ivRankClass(v: number): string {
  if (v >= 70) return "text-amber";
  if (v <= 30) return "text-fg-secondary";
  return "text-fg-primary";
}
