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
    throw new Error(`Request failed: ${res.status} ${res.statusText}`);
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

export const fetchTradeAnalytics = (
  id: number,
  dteOverride?: number | null,
): Promise<TradeAnalytics> => {
  const q = dteOverride != null ? `?dte_override=${dteOverride}` : "";
  return request(`/api/journal/trades/${id}/analytics${q}`, TradeAnalyticsSchema);
};
