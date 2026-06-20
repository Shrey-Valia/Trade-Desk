import { z } from "zod";
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
import { MetricsResponseSchema, type MetricsResponse } from "@/types/metrics";
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
  ContractPreviewSchema,
  ZeroDteChainSchema,
  type ChainTable,
  type ContractPreview,
  type ContractPreviewInput,
  type ZeroDteChain,
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
import { TickerDetailSchema, type TickerDetail } from "@/types/ticker";
import { WatchlistResponseSchema, type WatchlistResponse } from "@/types/watchlist";
import { AccountStateSchema, type AccountState } from "@/types/account";
import {
  UserOutSchema,
  type SigninInput,
  type SignupInput,
  type UserOut,
} from "@/types/auth";
import {
  CombineEventSchema,
  CombineOutSchema,
  CombinesOutSchema,
  PayoutOutSchema,
  type CombineEvent,
  type CombineOut,
  type CombinesOut,
  type CopyConfigInput,
  type PayoutOut,
  type PurchaseInput,
} from "@/types/combine";
import {
  PopularResponseSchema,
  StarsResponseSchema,
  TickerSearchResponseSchema,
  type PopularResponse,
  type StarsResponse,
  type TickerSearchResponse,
} from "@/types/search";

const API_BASE = "";

async function request<S extends z.ZodTypeAny>(
  path: string,
  schema: S,
): Promise<z.infer<S>> {
  // credentials: session-cookie auth. Same-origin through the Vite
  // proxy in dev; "include" also covers direct-to-:8000 use.
  const res = await fetch(`${API_BASE}${path}`, { credentials: "include" });
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

export const fetchMarketStatus = (): Promise<MarketStatus> =>
  request("/api/market/status", MarketStatusSchema);

export const fetchMarketIndices = (): Promise<IndicesResponse> =>
  request("/api/market/indices", IndicesResponseSchema);

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
    credentials: "include",
    ...init,
  });
  if (!res.ok) {
    // Surface FastAPI's `detail` like request() does — the purchase
    // 5-cap 409 and auth errors carry their message there.
    let detail = `Request failed: ${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      if (body?.detail) detail = String(body.detail);
    } catch {
      /* non-JSON body */
    }
    throw new Error(detail);
  }
  // 204s have no body to parse.
  if (res.status === 204) {
    return schema.parse(undefined);
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

export const fetchAccountState = (): Promise<AccountState> =>
  request("/api/account/state", AccountStateSchema);

export const searchTickers = (q: string): Promise<TickerSearchResponse> =>
  request(
    `/api/ticker/search?q=${encodeURIComponent(q)}`,
    TickerSearchResponseSchema,
  );

export const fetchPopularTickers = (): Promise<PopularResponse> =>
  request("/api/ticker/popular", PopularResponseSchema);

export const fetchStars = (): Promise<StarsResponse> =>
  request("/api/user/stars", StarsResponseSchema);

export const addStar = (symbol: string): Promise<StarsResponse> =>
  mutate(`/api/user/stars/${encodeURIComponent(symbol)}`, StarsResponseSchema, {
    method: "POST",
  });

export const removeStar = (symbol: string): Promise<StarsResponse> =>
  mutate(`/api/user/stars/${encodeURIComponent(symbol)}`, StarsResponseSchema, {
    method: "DELETE",
  });

export const logTickerSelection = async (symbol: string): Promise<void> => {
  // Fire-and-forget — server returns 204. Errors are swallowed so a
  // logging failure doesn't surface as a UI error after the user
  // already moved on to the new ticker.
  try {
    await fetch(`${API_BASE}/api/ticker/selection`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      body: JSON.stringify({ symbol }),
    });
  } catch {
    /* selection logging is best-effort */
  }
};

// -- combines ----------------------------------------------------------------

export const fetchCombines = (): Promise<CombinesOut> =>
  request("/api/combines", CombinesOutSchema);

export const purchaseCombine = (input: PurchaseInput): Promise<CombineOut> =>
  mutate("/api/combines/purchase", CombineOutSchema, {
    method: "POST",
    body: JSON.stringify(input),
  });

export const renameCombine = (id: number, name: string): Promise<CombineOut> =>
  mutate(`/api/combines/${id}`, CombineOutSchema, {
    method: "PATCH",
    body: JSON.stringify({ name }),
  });

export const archiveCombine = (id: number): Promise<CombineOut> =>
  mutate(`/api/combines/${id}/archive`, CombineOutSchema, { method: "POST" });

/** Returns the full account-state payload for direct cache swap. */
export const activateCombine = (id: number): Promise<AccountState> =>
  mutate(`/api/combines/${id}/activate`, AccountStateSchema, { method: "POST" });

/** Restart a failed evaluation (keeps trade history). */
export const resetCombine = (id: number): Promise<CombineOut> =>
  mutate(`/api/combines/${id}/reset`, CombineOutSchema, { method: "POST" });

/** Request a payout on a funded, activated account (simulated). */
export const requestPayout = (id: number): Promise<PayoutOut> =>
  mutate(`/api/combines/${id}/payout`, PayoutOutSchema, { method: "POST" });

/** Activate a funded combine (one unified flow — charges $149 on the
 *  activation path, $0 on no-activation); unlocks payouts. */
export const activateAccount = (id: number): Promise<CombineOut> =>
  mutate(`/api/combines/${id}/activate-account`, CombineOutSchema, { method: "POST" });

/** Recent lifecycle events across the user's combines (newest first). */
export const fetchCombineEvents = (): Promise<CombineEvent[]> =>
  request("/api/combines/events", z.array(CombineEventSchema));

/** Set copy trading: the lead combine + which combines follow it. Returns
 *  the refreshed combines payload. */
export const updateCopyConfig = (input: CopyConfigInput): Promise<CombinesOut> =>
  mutate("/api/combines/copy-config", CombinesOutSchema, {
    method: "PUT",
    body: JSON.stringify(input),
  });

// -- DLL overrides (server-enforced) -----------------------------------------

const DllOverridesSchema = z.object({ overrides: z.record(z.number()) });

/** The user's per-tier DLL overrides ({tier: dollars}). */
export const fetchDllOverrides = (): Promise<Record<string, number>> =>
  request("/api/account/dll-overrides", DllOverridesSchema).then((r) => r.overrides);

/** Replace the user's per-tier DLL overrides (server clamps to the band). */
export const updateDllOverrides = (
  overrides: Record<string, number>,
): Promise<Record<string, number>> =>
  mutate("/api/account/dll-overrides", DllOverridesSchema, {
    method: "PUT",
    body: JSON.stringify({ overrides }),
  }).then((r) => r.overrides);

// -- auth --------------------------------------------------------------------

export const fetchMe = (): Promise<UserOut> =>
  request("/api/auth/me", UserOutSchema);

export const signup = (input: SignupInput): Promise<UserOut> =>
  mutate("/api/auth/signup", UserOutSchema, {
    method: "POST",
    body: JSON.stringify(input),
  });

export const signin = (input: SigninInput): Promise<UserOut> =>
  mutate("/api/auth/signin", UserOutSchema, {
    method: "POST",
    body: JSON.stringify(input),
  });

export const signout = (): Promise<void> =>
  mutate("/api/auth/signout", z.void(), { method: "POST" });

export const updateTrade = (id: number, patch: TradeUpdateInput): Promise<Trade> =>
  mutate(`/api/journal/trades/${id}`, TradeOutSchema, {
    method: "PATCH",
    body: JSON.stringify(patch),
  });

/** Set/clear SL/TP brackets (underlying price levels). PUT semantics: send
 *  both each time — a null side clears that bracket. */
export const setBrackets = (
  id: number,
  brackets: { stop_loss: number | null; take_profit: number | null },
): Promise<Trade> =>
  mutate(`/api/journal/trades/${id}/brackets`, TradeOutSchema, {
    method: "PUT",
    body: JSON.stringify(brackets),
  });

/** Cancel a working (unfilled) limit/stop order. */
export const cancelOrder = (id: number): Promise<Trade> =>
  mutate(`/api/journal/trades/${id}/cancel`, TradeOutSchema, { method: "POST" });

export const deleteTrade = async (id: number): Promise<void> => {
  const res = await fetch(`${API_BASE}/api/journal/trades/${id}`, {
    method: "DELETE",
    credentials: "include",
  });
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
  /** Active tier's MLL trailing distance — enables the days-near-MLL
   *  count in the risk panel. */
  trail?: number | null;
  /** Scope to one owned combine (dashboard uses the active one). */
  combineId?: number | null;
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

/** Pre-trade payoff + greeks for the selected contract (detail panel). */
export const fetchContractPreview = (
  input: ContractPreviewInput,
): Promise<ContractPreview> =>
  mutate("/api/zerodte/preview", ContractPreviewSchema, {
    method: "POST",
    body: JSON.stringify(input),
  });

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
  if (filters.trail != null) p.set("trail", String(filters.trail));
  if (filters.combineId != null) p.set("combine_id", String(filters.combineId));
  const q = p.toString();
  return request(`/api/analytics${q ? `?${q}` : ""}`, AnalyticsResponseSchema);
};
