import { useQuery } from "@tanstack/react-query";

import { fetchTickerBars, fetchTickerChart } from "@/lib/api";
import type { ChartTimeframe } from "@/types/chart";

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
