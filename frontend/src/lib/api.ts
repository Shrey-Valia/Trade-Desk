import { z } from "zod";
import { BsResponseSchema, type BsResponse, type StrategyType } from "@/types/bs";
import { CalendarResponseSchema, type CalendarResponse } from "@/types/calendar";
import { ChartResponseSchema, type ChartResponse, type ChartTimeframe } from "@/types/chart";
import {
  IndicesResponseSchema,
  LiquidUniverseSchema,
  MarketStatusSchema,
  type IndicesResponse,
  type LiquidUniverse,
  type MarketStatus,
} from "@/types/market";
import { McResponseSchema, type McResponse } from "@/types/mc";
import { MetricsResponseSchema, type MetricsResponse } from "@/types/metrics";
import { ModelSignalsResponseSchema, type ModelSignalsResponse } from "@/types/models";
import {
  AnalyticsResponseSchema,
  type AnalyticsResponse,
} from "@/types/analytics";
import {
  CalendarMonthSchema,
  type CalendarMonth,
} from "@/types/calendar_journal";
import {
  ChainTableSchema,
  ZeroDteChainSchema,
  ZeroDteMarkSchema,
  type ChainTable,
  type ZeroDteChain,
  type ZeroDteMark,
  type ZeroDtePosition,
} from "@/types/zerodte";
import {
  TradeAnalyticsSchema,
  TradeOutSchema,
  TradesResponseSchema,
  type Trade,
  type TradeAnalytics,
  type TradeInput,
  type TradeStatus,
  type TradeUpdateInput,
  type TradesResponse,
} from "@/types/journal";
import { SignalVerdictSchema, type SignalVerdict } from "@/types/signal";
import { TickerDetailSchema, type TickerDetail } from "@/types/ticker";
import { WatchlistResponseSchema, type WatchlistResponse } from "@/types/watchlist";

const API_BASE = "";

async function request<S extends z.ZodTypeAny>(
  path: string,
  schema: S,
): Promise<z.infer<S>> {
  const res = await fetch(`${API_BASE}${path}`);
  if (!res.ok) {
    // Surface the backend's `detail` when present (FastAPI HTTPException
    // bodies look like `{"detail": "..."}`). UI components branch on
    // this text — e.g. ChainTable looks for "No 0DTE for" to render the
    // strict-0DTE empty state instead of a generic error.
    let detail = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      if (body?.detail) detail = String(body.detail);
    } catch {
      /* non-JSON body */
    }
    throw new Error(detail);
  }
  const json = await res.json();
  return schema.parse(json);
}

export const fetchWatchlist = (): Promise<WatchlistResponse> =>
  request("/api/watchlist", WatchlistResponseSchema);

export const fetchTickerDetail = (symbol: string): Promise<TickerDetail> =>
  request(`/api/ticker/${encodeURIComponent(symbol)}/detail`, TickerDetailSchema);

export const fetchTickerChart = (
  symbol: string,
  timeframe: ChartTimeframe,
): Promise<ChartResponse> =>
  request(
    `/api/ticker/${encodeURIComponent(symbol)}/chart?timeframe=${timeframe}`,
    ChartResponseSchema,
  );

/** Fast-path bars-only fetch — bypasses the options-chain dependency. */
export const fetchTickerBars = (
  symbol: string,
  timeframe: ChartTimeframe,
): Promise<ChartResponse> =>
  request(
    `/api/ticker/${encodeURIComponent(symbol)}/bars?timeframe=${timeframe}`,
    ChartResponseSchema,
  );

export const fetchTickerMetrics = (symbol: string): Promise<MetricsResponse> =>
  request(`/api/ticker/${encodeURIComponent(symbol)}/metrics`, MetricsResponseSchema);

export const fetchCalendar = (): Promise<CalendarResponse> =>
  request("/api/calendar", CalendarResponseSchema);

export const fetchMonteCarlo = (symbol: string): Promise<McResponse> =>
  request(`/api/mc/${encodeURIComponent(symbol)}`, McResponseSchema);

export const fetchStrategyPayoff = (
  symbol: string,
  strategy: StrategyType,
): Promise<BsResponse> =>
  request(
    `/api/bs/strategy/${encodeURIComponent(symbol)}/${strategy}`,
    BsResponseSchema,
  );

export const fetchModelSignals = (symbol: string): Promise<ModelSignalsResponse> =>
  request(`/api/models/${encodeURIComponent(symbol)}`, ModelSignalsResponseSchema);

export const fetchMarketStatus = (): Promise<MarketStatus> =>
  request("/api/market/status", MarketStatusSchema);

export const fetchMarketIndices = (): Promise<IndicesResponse> =>
  request("/api/market/indices", IndicesResponseSchema);

export const fetchSignal = (symbol: string): Promise<SignalVerdict> =>
  request(`/api/signal/${encodeURIComponent(symbol)}`, SignalVerdictSchema);

export const fetchLiquidUniverse = (): Promise<LiquidUniverse> =>
  request("/api/market/liquid_universe", LiquidUniverseSchema);

/** 0DTE-eligible allowlist — drives the symbol search restriction. */
export const fetchZeroDteUniverse = (): Promise<LiquidUniverse> =>
  request("/api/market/zerodte_universe", LiquidUniverseSchema);

// -- Trade Desk journal -----------------------------------------------------

async function mutate<S extends z.ZodTypeAny>(
  path: string,
  schema: S,
  init: RequestInit,
): Promise<z.infer<S>> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    throw new Error(`Request failed: ${res.status} ${res.statusText}`);
  }
  const json = await res.json();
  return schema.parse(json);
}

export interface TradeListFilters {
  status?: TradeStatus;
  isPaper?: boolean;
  symbol?: string;
}

export const fetchTrades = (filters: TradeListFilters = {}): Promise<TradesResponse> => {
  const params = new URLSearchParams();
  if (filters.status) params.set("status", filters.status);
  if (filters.isPaper !== undefined) params.set("is_paper", String(filters.isPaper));
  if (filters.symbol) params.set("symbol", filters.symbol);
  const q = params.toString();
  return request(`/api/journal/trades${q ? `?${q}` : ""}`, TradesResponseSchema);
};

export const createTrade = (input: TradeInput): Promise<Trade> =>
  mutate("/api/journal/trades", TradeOutSchema, {
    method: "POST",
    body: JSON.stringify(input),
  });

export const updateTrade = (id: number, patch: TradeUpdateInput): Promise<Trade> =>
  mutate(`/api/journal/trades/${id}`, TradeOutSchema, {
    method: "PATCH",
    body: JSON.stringify(patch),
  });

export const deleteTrade = async (id: number): Promise<void> => {
  const res = await fetch(`${API_BASE}/api/journal/trades/${id}`, { method: "DELETE" });
  if (!res.ok) {
    throw new Error(`Delete failed: ${res.status} ${res.statusText}`);
  }
};

export interface AnalyticsParams {
  dteOverride?: number | null;
  /** 0DTE-only: hours since entry. Backend ignores this when the trade
   * is not 0DTE — safe to always pass when present. */
  elapsedHours?: number | null;
}

export const fetchTradeAnalytics = (
  id: number,
  params: AnalyticsParams = {},
): Promise<TradeAnalytics> => {
  const p = new URLSearchParams();
  if (params.dteOverride != null) p.set("dte_override", String(params.dteOverride));
  if (params.elapsedHours != null) p.set("elapsed_hours", String(params.elapsedHours));
  const q = p.toString();
  return request(
    `/api/journal/trades/${id}/analytics${q ? `?${q}` : ""}`,
    TradeAnalyticsSchema,
  );
};

export interface JournalAnalyticsFilters {
  paper?: boolean | null;
  strategy?: string | null;
  since?: string | null;     // ISO date
  until?: string | null;
}

// -- Zero-DTE ---------------------------------------------------------------

export const fetchZeroDteChain = (
  symbol: string = "SPY",
): Promise<ZeroDteChain> =>
  request(
    `/api/zerodte/chain?symbol=${encodeURIComponent(symbol)}`,
    ZeroDteChainSchema,
  );

/** Windowed chain table for the trading-ticket UI — strikes around ATM
 * with call+put prices (live quote or BS fallback) and open interest. */
export const fetchChainTable = (
  symbol: string,
  strikes: number = 15,
): Promise<ChainTable> =>
  request(
    `/api/zerodte/chain/table?symbol=${encodeURIComponent(symbol)}&strikes=${strikes}`,
    ChainTableSchema,
  );

/** Open an ATM straddle paper Trade on `symbol` expiring today.
 *  action="buy" = long straddle (debit); action="sell" = short straddle
 *  (credit). Returns the created Trade — caller sets it as the active
 *  position. */
export const openZeroDteStraddle = (
  symbol: string,
  action: "buy" | "sell" = "buy",
  contracts: number = 1,
): Promise<Trade> =>
  mutate("/api/zerodte/open", TradeOutSchema, {
    method: "POST",
    body: JSON.stringify({ symbol, action, contracts }),
  });

/** Legacy /mark endpoint — still used by the standalone ZeroDtePage
 * (now unlinked from the rail but kept on disk during the transition). */
export const fetchZeroDteMark = async (
  position: ZeroDtePosition,
  elapsedHoursOverride?: number | null,
): Promise<ZeroDteMark> => {
  const res = await fetch(`${API_BASE}/api/zerodte/mark`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      position,
      elapsed_hours_override: elapsedHoursOverride ?? null,
    }),
  });
  if (!res.ok) throw new Error(`mark failed: ${res.status} ${res.statusText}`);
  return ZeroDteMarkSchema.parse(await res.json());
};

export const fetchJournalCalendar = (
  month: string,
  isPaper?: boolean | null,
): Promise<CalendarMonth> => {
  const p = new URLSearchParams();
  p.set("month", month);
  if (isPaper !== undefined && isPaper !== null) {
    p.set("is_paper", String(isPaper));
  }
  return request(`/api/journal/calendar?${p.toString()}`, CalendarMonthSchema);
};

export const fetchJournalAnalytics = (
  filters: JournalAnalyticsFilters = {},
): Promise<AnalyticsResponse> => {
  const p = new URLSearchParams();
  if (filters.paper !== undefined && filters.paper !== null) {
    p.set("paper", String(filters.paper));
  }
  if (filters.strategy) p.set("strategy", filters.strategy);
  if (filters.since) p.set("since", filters.since);
  if (filters.until) p.set("until", filters.until);
  const q = p.toString();
  return request(`/api/analytics${q ? `?${q}` : ""}`, AnalyticsResponseSchema);
};
