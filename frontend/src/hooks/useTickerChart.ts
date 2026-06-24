import { useQuery } from "@tanstack/react-query";

import { MarketDataUnavailableError, fetchTickerBars, fetchTickerChart } from "@/lib/api";
import type { ChartTimeframe } from "@/types/chart";

// ── WS3: auto-retry the market-data-degraded (503) state ─────────────────────
// When the feed is circuit-open the backend returns a typed 503. Keep
// retrying indefinitely so the chart recovers on its own once the breaker
// closes, but back off using the server's suggested Retry-After (clamped)
// so we don't hammer an already-throttled key. Non-degraded errors fall
// back to a small fixed retry count.
const MAX_RETRY_DELAY_MS = 30_000;

function chartRetry(failureCount: number, error: unknown): boolean {
  if (error instanceof MarketDataUnavailableError) return true;
  return failureCount < 2;
}

function chartRetryDelay(attempt: number, error: unknown): number {
  if (error instanceof MarketDataUnavailableError) {
    const suggested = (error.retryAfter || 5) * 1000;
    return Math.min(suggested, MAX_RETRY_DELAY_MS);
  }
  return Math.min(1000 * 2 ** attempt, MAX_RETRY_DELAY_MS);
}
// ── end WS3 ──────────────────────────────────────────────────────────────────

/**
 * Fast-path bars query — only fetches candles, no options-chain dependency.
 *
 * Used by AnnotatedChart so the candle render isn't blocked behind the
 * 1–3s chain fetch that drives the EM / max-pain / walls annotations.
 * Annotations come in as a second parallel query (see useTickerAnnotations
 * below) and overlay onto the chart as they arrive.
 *
 * staleTime: 60s so a ticker revisit within a minute is instant.
 * placeholderData: keeps the previous symbol's bars on screen during a
 * symbol switch — the chart is never blank between two non-empty states.
 * refetchInterval: 60s — bars change minute-scale at fastest.
 */
export function useTickerChart(symbol: string | null, timeframe: ChartTimeframe) {
  return useQuery({
    queryKey: ["ticker", "bars", symbol, timeframe],
    queryFn: () => fetchTickerBars(symbol as string, timeframe),
    enabled: !!symbol,
    staleTime: 60_000,
    refetchInterval: 60_000,
    placeholderData: (prev) => prev,
    // WS3: keep retrying the degraded (503) state until the breaker closes.
    retry: chartRetry,
    retryDelay: chartRetryDelay,
  });
}

/**
 * Annotations — the slow side. Pulls the full /chart payload (which
 * includes bars too, but the chart component reads bars from the fast
 * query above; we just want `annotations` and `oi_source` from this one).
 *
 * Longer staleTime since the chain-derived levels don't move minute-to-
 * minute. If this query is still pending when the bars arrive, the
 * chart renders without overlay lines and they appear later.
 */
export function useTickerAnnotations(symbol: string | null, timeframe: ChartTimeframe) {
  return useQuery({
    queryKey: ["ticker", "chart-annotations", symbol, timeframe],
    queryFn: () => fetchTickerChart(symbol as string, timeframe),
    enabled: !!symbol,
    staleTime: 5 * 60_000, // 5min — chain-derived levels move slowly
    refetchInterval: 5 * 60_000,
    placeholderData: (prev) => prev,
  });
}
