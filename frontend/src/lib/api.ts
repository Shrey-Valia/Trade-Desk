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
  IndicatorsResponseSchema,
  type IndicatorsResponse,
} from "@/types/indicators";
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
  ExpirationsSchema,
  MonteCarloResultSchema,
  RollOutSchema,
  TermStructureSchema,
  ZeroDteChainSchema,
  type ChainTable,
  type ContractPreview,
  type ContractPreviewInput,
  type Expirations,
  type MonteCarloInput,
  type MonteCarloResult,
  type MultiLegSpec,
  type OpenMultiLegInput,
  type RollOut,
  type TermStructure,
  type ZeroDteChain,
} from "@/types/zerodte";
import {
  PortfolioGreeksSchema,
  TradeAnalyticsSchema,
  TradeOutSchema,
  TradesResponseSchema,
  type PortfolioGreeks,
  type Trade,
  type TradeAnalytics,
  type TradeInput,
  type TradeStatus,
  type TradeUpdateInput,
  type TradesResponse,
  type WorkingOrderPatch,
} from "@/types/journal";
import { NewsResponseSchema, type NewsResponse } from "@/types/news";
import { TickerDetailSchema, type TickerDetail } from "@/types/ticker";
import { WatchlistResponseSchema, type WatchlistResponse } from "@/types/watchlist";
import { AccountStateSchema, type AccountState } from "@/types/account";
import {
  SignupPolicySchema,
  UserOutSchema,
  type SigninInput,
  type SignupInput,
  type SignupPolicy,
  type UserOut,
} from "@/types/auth";
import {
  CombineEventSchema,
  CombineOutSchema,
  CombinesOutSchema,
  PaymentsHistorySchema,
  PayoutOutSchema,
  type CombineEvent,
  type CombineOut,
  type CombinesOut,
  type CopyConfigInput,
  type PaymentsHistory,
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
import {
  AlertSchema,
  AlertsResponseSchema,
  EvaluateResponseSchema,
  type Alert,
  type AlertInput,
  type AlertsResponse,
  type EvaluateResponse,
} from "@/types/alert";

const API_BASE = "";

// ── session expiry (mid-session 401) ─────────────────────────────────────────
// RailShell registers a handler that invalidates the me-query, so a 401 on
// any API call re-runs the session probe and RequireAuth bounces to /signin
// instead of stranding a signed-in-looking app in per-panel error states.
// /api/auth/* is excluded: its 401s are normal signed-out answers (a failed
// signin, the /me probe itself), and reacting to them would loop the probe.
let onUnauthorized: (() => void) | null = null;

export function registerUnauthorizedHandler(handler: (() => void) | null): void {
  onUnauthorized = handler;
}

function notifyUnauthorized(path: string, status: number): void {
  if (status === 401 && !path.startsWith("/api/auth/")) onUnauthorized?.();
}
// ── end session expiry ───────────────────────────────────────────────────────

// Render a FastAPI error `detail` into a readable string. A plain HTTPException
// detail is a string, but a pydantic 422 detail is a LIST of
// `{loc, msg, type}` objects — `String(detail)` on that yields the useless
// "[object Object]". Join the `msg`s (with the offending field) instead.
function detailToMessage(detail: unknown): string | null {
  if (detail == null) return null;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    const parts = detail
      .map((e) => {
        if (e && typeof e === "object" && "msg" in e) {
          const loc = Array.isArray((e as { loc?: unknown[] }).loc)
            ? (e as { loc: unknown[] }).loc.slice(1).join(".")
            : "";
          const msg = String((e as { msg: unknown }).msg);
          return loc ? `${loc}: ${msg}` : msg;
        }
        return typeof e === "string" ? e : null;
      })
      .filter(Boolean);
    return parts.length ? parts.join("; ") : null;
  }
  return null;
}

// ── WS3: market-data graceful-degrade ───────────────────────────────────────
// Typed error for the backend's 503 "market data unavailable" degraded
// response (circuit breaker open / Alpaca rate-limited). The chart UI keys
// on `instanceof MarketDataUnavailableError` to render an explicit
// "retrying" state with auto-retry instead of an infinite spinner.
export class MarketDataUnavailableError extends Error {
  /** Seconds the backend suggests waiting before retrying (Retry-After). */
  readonly retryAfter: number;
  constructor(message: string, retryAfter: number) {
    super(message);
    this.name = "MarketDataUnavailableError";
    this.retryAfter = retryAfter;
  }
}
// ── end WS3 ─────────────────────────────────────────────────────────────────

/** Thrown when a request exceeds its `timeoutMs` budget.
 *  Carried as a typed error so the UI can distinguish a slow/hung upstream
 *  from a real failure and show a "retrying" state instead of spinning
 *  forever (e.g. the option chain when the market-data feed is unresponsive). */
export class RequestTimeoutError extends Error {
  readonly timeout = true;
  constructor(path: string, timeoutMs: number) {
    super(`Request timed out after ${Math.round(timeoutMs / 1000)}s`);
    this.name = "RequestTimeoutError";
    void path;
  }
}

async function request<S extends z.ZodTypeAny>(
  path: string,
  schema: S,
  opts?: { timeoutMs?: number },
): Promise<z.infer<S>> {
  // credentials: session-cookie auth. Same-origin through the Vite
  // proxy in dev; "include" also covers direct-to-:8000 use.
  let res: Response;
  if (opts?.timeoutMs) {
    // Deadline via Promise.race, NOT bare fetch-abort. Without a deadline a
    // hung upstream (unresponsive options-data feed) leaves fetch pending
    // forever and the caller's react-query stays `isLoading`. We race the
    // fetch against a timeout that REJECTS with a typed error so react-query
    // treats it as a normal failure (→ `isError`, retry) — an aborted fetch,
    // by contrast, looks like a query cancellation and leaves the query idle
    // with no error state. We still abort the losing fetch to free the socket,
    // and swallow its abort rejection so it never surfaces as unhandled.
    const controller = new AbortController();
    const fetchP = fetch(`${API_BASE}${path}`, {
      credentials: "include",
      signal: controller.signal,
    });
    fetchP.catch(() => {}); // the abort rejection is expected once we time out
    let timer: ReturnType<typeof setTimeout> | undefined;
    const timeoutP = new Promise<never>((_, reject) => {
      timer = setTimeout(() => {
        // Settle the race with the typed timeout FIRST, then abort — aborting
        // first would reject the raced fetch synchronously and that rejection
        // ("aborted") would win the race instead of our typed error.
        reject(new RequestTimeoutError(path, opts.timeoutMs!));
        controller.abort();
      }, opts.timeoutMs);
    });
    try {
      res = await Promise.race([fetchP, timeoutP]);
    } finally {
      if (timer) clearTimeout(timer);
    }
  } else {
    res = await fetch(`${API_BASE}${path}`, { credentials: "include" });
  }
  if (!res.ok) {
    notifyUnauthorized(path, res.status);
    // Surface the backend's `detail` when present (FastAPI HTTPException
    // bodies look like `{"detail": "..."}`). UI components branch on
    // this text — e.g. ChainTable looks for "No 0DTE for" to render the
    // strict-0DTE empty state instead of a generic error.
    let detail = `${res.status} ${res.statusText}`;
    let body: unknown = null;
    try {
      body = await res.json();
      const msg = detailToMessage((body as { detail?: unknown })?.detail);
      if (msg) detail = msg;
    } catch {
      /* non-JSON body */
    }
    // ── WS3: detect the typed market-data-degraded 503 first ────────────────
    // Body shape: {"error": "market_data_unavailable", retry_after, detail}.
    // Throw the typed error so the chart can show a retrying state distinct
    // from a 404 ("no bars") or a generic failure.
    if (
      res.status === 503 &&
      (body as { error?: unknown })?.error === "market_data_unavailable"
    ) {
      const ra = Number((body as { retry_after?: unknown })?.retry_after);
      const headerRa = Number(res.headers.get("Retry-After"));
      const retryAfter = Number.isFinite(ra)
        ? ra
        : Number.isFinite(headerRa)
          ? headerRa
          : 30;
      throw new MarketDataUnavailableError(detail, retryAfter);
    }
    // ── end WS3 ─────────────────────────────────────────────────────────────
    // Carry the HTTP status on the error so the query layer can branch on it
    // (e.g. never retry a 4xx — the 0DTE 409, off-hours 404s, auth 401s are
    // terminal answers). Message is unchanged, so existing `.message` readers
    // (RightChain's "No 0DTE for" check, toast handlers) keep working.
    const err = new Error(detail) as Error & { status?: number };
    err.status = res.status;
    throw err;
  }
  const json = await res.json();
  return schema.parse(json);
}

export const fetchWatchlist = (): Promise<WatchlistResponse> =>
  request("/api/watchlist", WatchlistResponseSchema);

export const fetchTickerDetail = (symbol: string): Promise<TickerDetail> =>
  request(`/api/ticker/${encodeURIComponent(symbol)}/detail`, TickerDetailSchema);

/** Ticker-scoped headlines. Server caches per symbol (5min); a 503 here
 *  means the upstream feed errored/rate-limited (distinct from an empty
 *  but successful `items: []`) and surfaces as react-query `isError`. */
export const fetchTickerNews = (
  symbol: string,
  limit = 20,
): Promise<NewsResponse> =>
  request(
    `/api/news?symbol=${encodeURIComponent(symbol)}&limit=${limit}`,
    NewsResponseSchema,
  );

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

/**
 * Technical-indicator overlays. `set` is a comma-separated list of
 * `family:period` tokens (e.g. "sma:20,ema:50,vwap,rsi:14,atr:14"); the
 * backend returns per-bar arrays aligned to the same timestamps as /chart
 * and /bars. The period is part of the cache key on both sides, so changing
 * a window refetches just that series. Zod-validated like the other ticker
 * fetchers.
 */
export const fetchTickerIndicators = (
  symbol: string,
  timeframe: ChartTimeframe,
  set: string,
): Promise<IndicatorsResponse> =>
  request(
    `/api/ticker/${encodeURIComponent(symbol)}/indicators?timeframe=${timeframe}&set=${encodeURIComponent(set)}`,
    IndicatorsResponseSchema,
  );

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
    notifyUnauthorized(path, res.status);
    // Surface FastAPI's `detail` like request() does — the purchase
    // 5-cap 409 and auth errors carry their message there.
    let detail = `Request failed: ${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      const msg = detailToMessage(body?.detail);
      if (msg) detail = msg;
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
  /** Scope to one owned combine (null/undefined = all accounts). */
  combineId?: number | null;
  /** ISO date bounds on exit_date — same semantics as /api/analytics. */
  since?: string | null;
  until?: string | null;
}

export const fetchTrades = (filters: TradeListFilters = {}): Promise<TradesResponse> => {
  const params = new URLSearchParams();
  if (filters.status) params.set("status", filters.status);
  if (filters.isPaper !== undefined) params.set("is_paper", String(filters.isPaper));
  if (filters.symbol) params.set("symbol", filters.symbol);
  if (filters.combineId != null) params.set("combine_id", String(filters.combineId));
  if (filters.since) params.set("since", filters.since);
  if (filters.until) params.set("until", filters.until);
  const q = params.toString();
  return request(`/api/journal/trades${q ? `?${q}` : ""}`, TradesResponseSchema);
};

export const createTrade = (input: TradeInput): Promise<Trade> =>
  mutate("/api/journal/trades", TradeOutSchema, {
    method: "POST",
    body: JSON.stringify(input),
  });

/**
 * Attach a screenshot to an existing trade (multipart). The backend
 * validates size (≤5MB) + format (PNG/JPEG), stores the file, and returns
 * the refreshed trade with `screenshot_url` set. We do NOT set a
 * Content-Type header — the browser sets the multipart boundary itself.
 */
export const uploadTradeScreenshot = async (
  id: number,
  file: File,
): Promise<Trade> => {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(`${API_BASE}/api/journal/trades/${id}/screenshot`, {
    method: "POST",
    credentials: "include",
    body: form,
  });
  if (!res.ok) {
    notifyUnauthorized(`/api/journal/trades/${id}/screenshot`, res.status);
    let detail = `Upload failed: ${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      const msg = detailToMessage(body?.detail);
      if (msg) detail = msg;
    } catch {
      /* non-JSON body */
    }
    throw new Error(detail);
  }
  return TradeOutSchema.parse(await res.json());
};

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

/** Request a payout on a funded, activated account (simulated). `amount`
 *  omitted books the max eligible; the backend 409s (minimum, winning-day
 *  count, 24h spacing, MLL buffer) with a human-readable `detail`. */
export const requestPayout = (id: number, amount?: number): Promise<PayoutOut> =>
  mutate(`/api/combines/${id}/payout`, PayoutOutSchema, {
    method: "POST",
    body: JSON.stringify(amount != null ? { amount } : {}),
  });

/** Activate a funded combine (one unified flow — charges $149 on the
 *  activation path, $0 on no-activation); unlocks payouts. */
export const activateAccount = (id: number): Promise<CombineOut> =>
  mutate(`/api/combines/${id}/activate-account`, CombineOutSchema, { method: "POST" });

/** Cancel at period end: the combine stays tradeable until `paid_through`,
 *  then archives and the monthly charge stops. Returns the updated combine
 *  (cancel_at_period_end = true). */
export const cancelCombine = (id: number): Promise<CombineOut> =>
  mutate(`/api/combines/${id}/cancel`, CombineOutSchema, { method: "POST" });

/** Undo a pending cancel — the subscription renews at the period end. */
export const resumeCombine = (id: number): Promise<CombineOut> =>
  mutate(`/api/combines/${id}/resume`, CombineOutSchema, { method: "POST" });

/** Charge history for the billing tab (simulated payments — real pricing,
 *  no real card by design). */
export const fetchPaymentsHistory = (): Promise<PaymentsHistory> =>
  request("/api/payments/history", PaymentsHistorySchema);

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

// -- DLL overrides + disable flags (server-enforced) -------------------------

/** PDLL enforcement mode for a tier's daily-loss-limit override:
 *  - "alert"           — toast/event only; trading continues.
 *  - "liquidate"       — flattens open positions; re-opening allowed.
 *  - "liquidate_block" — flattens AND locks the day (until 5pm-PT reset). */
export const DLL_MODES = ["alert", "liquidate", "liquidate_block"] as const;
export type DllMode = (typeof DLL_MODES)[number];

const DllOverrideObjectSchema = z.object({
  amount: z.number(),
  mode: z.enum(DLL_MODES),
});
export type DllOverrideSetting = z.infer<typeof DllOverrideObjectSchema>;

/** An override value — the modern {amount, mode} object, or a legacy bare
 *  number (which means liquidate_block, the historical behavior). */
const DllOverrideValueSchema = z.union([z.number(), DllOverrideObjectSchema]);
export type DllOverrideValue = z.infer<typeof DllOverrideValueSchema>;

/** Daily profit target — lock=true means "flatten & end my day when hit". */
const ProfitTargetSchema = z.object({
  amount: z.number(),
  lock: z.boolean(),
});
export type ProfitTarget = z.infer<typeof ProfitTargetSchema>;

const DllOverridesSchema = z.object({
  overrides: z.record(DllOverrideValueSchema),
  // Tier keys with the DLL switched OFF (the DLL-off toggle). Defaulted so an
  // older backend response (no `disabled` key) still parses.
  disabled: z.array(z.string()).default([]),
  // nullable().optional() so the UI degrades gracefully while the backend
  // field is in flight; null = no profit target set.
  profit_target: ProfitTargetSchema.nullable().optional(),
});

/** The user's per-tier DLL overrides + disable flags + profit target. */
export interface DllOverridesConfig {
  overrides: Record<string, DllOverrideValue>;
  disabled: string[];
  profit_target?: ProfitTarget | null;
}

/** Normalize both override shapes to the object form for the UI — a legacy
 *  bare number means "liquidate & block" (the historical behavior). */
export function normalizeDllOverride(
  v: DllOverrideValue | null | undefined,
): DllOverrideSetting | null {
  if (v == null) return null;
  if (typeof v === "number") return { amount: v, mode: "liquidate_block" };
  return v;
}

export const fetchDllOverrides = (): Promise<DllOverridesConfig> =>
  request("/api/account/dll-overrides", DllOverridesSchema);

/** Replace the user's per-tier DLL overrides + disable flags + profit
 *  target. `disabled` / `profitTarget` omitted (undefined) leave the
 *  existing values untouched server-side; profitTarget null CLEARS it. */
export const updateDllOverrides = (
  overrides: Record<string, DllOverrideValue>,
  disabled?: string[],
  profitTarget?: ProfitTarget | null,
): Promise<DllOverridesConfig> =>
  mutate("/api/account/dll-overrides", DllOverridesSchema, {
    method: "PUT",
    body: JSON.stringify({
      overrides,
      ...(disabled === undefined ? {} : { disabled }),
      ...(profitTarget === undefined ? {} : { profit_target: profitTarget }),
    }),
  });

// -- auth --------------------------------------------------------------------

export const fetchMe = (): Promise<UserOut> =>
  request("/api/auth/me", UserOutSchema);

export const signup = (input: SignupInput): Promise<UserOut> =>
  mutate("/api/auth/signup", UserOutSchema, {
    method: "POST",
    body: JSON.stringify(input),
  });

/** Public + unauthenticated: does the signup form need an invite code? */
export const fetchSignupPolicy = (): Promise<SignupPolicy> =>
  request("/api/auth/signup-policy", SignupPolicySchema);

export const signin = (input: SigninInput): Promise<UserOut> =>
  mutate("/api/auth/signin", UserOutSchema, {
    method: "POST",
    body: JSON.stringify(input),
  });

export const signout = (): Promise<void> =>
  mutate("/api/auth/signout", z.void(), { method: "POST" });

export interface ChangePasswordInput {
  current_password: string;
  new_password: string;
}

/** Change the signed-in user's password. 204 on success (the backend revokes
 *  every OTHER session; this one stays signed in). A 403 (wrong current
 *  password) or 422 (policy) carries its `detail` verbatim as Error.message. */
export const changePassword = (input: ChangePasswordInput): Promise<void> =>
  mutate("/api/auth/change-password", z.void(), {
    method: "POST",
    body: JSON.stringify(input),
  });

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

/** Place (or replace) a resting CLOSE-LIMIT on an open position. The limit is
 *  the SIGNED net premium per 1× structure — positive = value to sell a
 *  net-debit position at; negative = buy-back cost for a net-credit position
 *  (-0.30 = pay at most 0.30). 422 when the sign doesn't match the position's
 *  direction or the limit is already marketable (use the market close then). */
export const setCloseOrder = (id: number, limitPrice: number): Promise<Trade> =>
  mutate(`/api/journal/trades/${id}/close-order`, TradeOutSchema, {
    method: "POST",
    body: JSON.stringify({ limit_price: limitPrice }),
  });

/** Pull the resting close-limit off an open position. */
export const clearCloseOrder = (id: number): Promise<Trade> =>
  mutate(`/api/journal/trades/${id}/close-order`, TradeOutSchema, {
    method: "DELETE",
  });

/** Close ONE leg of an open multi-leg position at the live mark (buy back
 *  the tested short, let the rest ride). qty omitted = the whole leg. The
 *  surviving legs keep riding; strategy label degrades to "custom" (or the
 *  single-leg name when one leg remains). 409 while copy-followers mirror
 *  the trade (per-leg closes don't cascade yet). */
export const closeLeg = (
  id: number,
  legIndex: number,
  qty?: number,
): Promise<Trade> =>
  mutate(`/api/journal/trades/${id}/close-leg`, TradeOutSchema, {
    method: "POST",
    body: JSON.stringify({ leg_index: legIndex, qty: qty ?? null }),
  });

/** Link 2–4 WORKING orders as an OCO group — when one fills, the monitor
 *  cancels the rest. 409 when any is no longer working. */
export const linkOcoOrders = (tradeIds: number[]): Promise<TradesResponse> =>
  mutate("/api/journal/orders/oco-link", TradesResponseSchema, {
    method: "POST",
    body: JSON.stringify({ trade_ids: tradeIds }),
  });

/** Dissolve the OCO pairing on the given orders. */
export const unlinkOcoOrders = (tradeIds: number[]): Promise<TradesResponse> =>
  mutate("/api/journal/orders/oco-unlink", TradesResponseSchema, {
    method: "POST",
    body: JSON.stringify({ trade_ids: tradeIds }),
  });

/** Modify a WORKING (unfilled) order in place — trigger price(s) and/or TIF.
 *  409 when the order is no longer working (filled/cancelled underneath the
 *  form); the backend's detail is surfaced verbatim on the thrown error. */
export const updateWorkingOrder = (
  id: number,
  patch: WorkingOrderPatch,
): Promise<Trade> =>
  mutate(`/api/journal/trades/${id}/order`, TradeOutSchema, {
    method: "PATCH",
    body: JSON.stringify(patch),
  });

/** Partial close (scale-out): book `qty` contracts of an OPEN position,
 *  leaving the rest open. `realized_pnl` is the booked P&L for the slice;
 *  the backend accumulates it and reduces every leg by qty. qty must be
 *  strictly fewer than the position holds (full close uses updateTrade). */
export const scaleOutTrade = (
  id: number,
  payload: { qty: number; realized_pnl: number; exit_underlying_price?: number | null },
): Promise<Trade> =>
  mutate(`/api/journal/trades/${id}/scale-out`, TradeOutSchema, {
    method: "POST",
    body: JSON.stringify(payload),
  });

export const deleteTrade = async (id: number): Promise<void> => {
  const res = await fetch(`${API_BASE}/api/journal/trades/${id}`, {
    method: "DELETE",
    credentials: "include",
  });
  if (!res.ok) {
    notifyUnauthorized(`/api/journal/trades/${id}`, res.status);
    throw new Error(`Delete failed: ${res.status} ${res.statusText}`);
  }
};

export interface AnalyticsParams {
  dteOverride?: number | null;
  /** 0DTE-only: hours since entry. Backend ignores this when the trade
   * is not 0DTE — safe to always pass when present. */
  elapsedHours?: number | null;
}

/** Net Greek exposure across every OPEN execution position on the active
 *  combine + SPY-beta-weighted delta. 503 while the quote feed is cold. */
export const fetchPortfolioGreeks = (): Promise<PortfolioGreeks> =>
  request("/api/journal/portfolio/greeks", PortfolioGreeksSchema);

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
 * with call+put prices (live quote or BS fallback) and open interest.
 * `expiry` (ISO date) browses a LATER expiration read-only; omitted =
 * today's 0DTE, else the nearest upcoming expiry. */
export const fetchChainTable = (
  symbol: string,
  strikes: number = 15,
  expiry?: string | null,
): Promise<ChainTable> =>
  request(
    `/api/zerodte/chain/table?symbol=${encodeURIComponent(symbol)}&strikes=${strikes}` +
      (expiry ? `&expiry=${encodeURIComponent(expiry)}` : ""),
    ChainTableSchema,
    // 8s deadline — deliberately BELOW useChainTable's 10s refetchInterval.
    // If the timeout exceeded the poll interval, the next poll would supersede
    // (and react-query would *cancel*, not error) the still-in-flight fetch,
    // leaving the query stuck `pending` forever with no error state. At 8s the
    // fetch errors cleanly before the next poll, so an unresponsive options
    // feed surfaces the retry state instead of a perpetual "Loading…" spinner.
    // Warm intraday loads return in well under 1s, so this only bites when the
    // feed is actually degraded (after-hours, rate-limited).
    { timeoutMs: 8_000 },
  );

/** Listed expirations (today or later) for the chain's expiry selector. */
export const fetchExpirations = (symbol: string): Promise<Expirations> =>
  request(
    `/api/zerodte/expirations?symbol=${encodeURIComponent(symbol)}`,
    ExpirationsSchema,
  );

/** ATM implied-vol term structure — one point per listed expiration. */
export const fetchTermStructure = (symbol: string): Promise<TermStructure> =>
  request(
    `/api/zerodte/term?symbol=${encodeURIComponent(symbol)}`,
    TermStructureSchema,
  );

/** Roll an open position: close at the live mark and reopen the same
 *  structure at shifted strikes as ONE action. Exactly one of strikeShift
 *  (signed points, whole structure moves together) or toAtm (re-center the
 *  anchor leg on the current ATM). A refused roll leaves the position
 *  untouched — every gate runs before the close books. */
export const rollTrade = (
  tradeId: number,
  opts: { strikeShift?: number; toAtm?: boolean },
): Promise<RollOut> =>
  mutate("/api/zerodte/roll", RollOutSchema, {
    method: "POST",
    body: JSON.stringify({
      trade_id: tradeId,
      strike_shift: opts.strikeShift ?? null,
      to_atm: opts.toAtm ?? false,
    }),
  });

/** Pre-trade payoff + greeks for the selected contract (detail panel). */
export const fetchContractPreview = (
  input: ContractPreviewInput,
): Promise<ContractPreview> =>
  mutate("/api/zerodte/preview", ContractPreviewSchema, {
    method: "POST",
    body: JSON.stringify(input),
  });

/** Pre-trade payoff/POP for an arbitrary 2–6 leg structure AS SUBMITTED
 *  (short legs negative) — the strategy builder's risk graph. */
export const fetchMultiLegPreview = (input: {
  symbol: string;
  contracts: number;
  legs: MultiLegSpec[];
}): Promise<ContractPreview> =>
  mutate("/api/zerodte/preview-multi", ContractPreviewSchema, {
    method: "POST",
    body: JSON.stringify(input),
  });

/** Open an ATM straddle paper Trade on `symbol` expiring today.
 *  action="buy" = long straddle (debit); action="sell" = short straddle
 *  (credit). Optional premium-exit multiples (tp/sl as multiples of the
 *  entry premium — fractions of the credit for a short) attach exits at
 *  open. Returns the created Trade — caller sets it as the active
 *  position. */
export const openZeroDteStraddle = (
  symbol: string,
  action: "buy" | "sell" = "buy",
  contracts: number = 1,
  premiumExits?: {
    tp_premium_mult?: number | null;
    sl_premium_mult?: number | null;
  },
  brackets?: {
    stop_loss?: number | null;
    take_profit?: number | null;
  },
): Promise<Trade> =>
  mutate("/api/zerodte/open", TradeOutSchema, {
    method: "POST",
    body: JSON.stringify({
      symbol,
      action,
      contracts,
      tp_premium_mult: premiumExits?.tp_premium_mult ?? null,
      sl_premium_mult: premiumExits?.sl_premium_mult ?? null,
      stop_loss: brackets?.stop_loss ?? null,
      take_profit: brackets?.take_profit ?? null,
    }),
  });

/** WS5: open a multi-leg 0DTE structure (vertical / condor / butterfly /
 *  custom) as a single Trade carrying all legs. */
export const openZeroDteMultiLeg = (input: OpenMultiLegInput): Promise<Trade> =>
  mutate("/api/zerodte/open-multi", TradeOutSchema, {
    method: "POST",
    body: JSON.stringify(input),
  });

/** WS5: run a terminal-value Monte-Carlo for an open position (trade_id) or
 *  a hypothetical structure (legs). Returns the P&L distribution + P(profit). */
export const runMonteCarlo = (input: MonteCarloInput): Promise<MonteCarloResult> =>
  mutate("/api/analytics/montecarlo", MonteCarloResultSchema, {
    method: "POST",
    body: JSON.stringify(input),
  });

export const fetchJournalCalendar = (
  month: string,
  isPaper?: boolean | null,
  combineId?: number | null,
): Promise<CalendarMonth> => {
  const p = new URLSearchParams();
  p.set("month", month);
  if (isPaper !== undefined && isPaper !== null) {
    p.set("is_paper", String(isPaper));
  }
  if (combineId != null) p.set("combine_id", String(combineId));
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

// -- Alerts (WS6) -----------------------------------------------------------

export const fetchAlerts = (): Promise<AlertsResponse> =>
  request("/api/alerts", AlertsResponseSchema);

export const createAlert = (input: AlertInput): Promise<Alert> =>
  mutate("/api/alerts", AlertSchema, {
    method: "POST",
    body: JSON.stringify(input),
  });

export const deleteAlert = async (id: number): Promise<void> => {
  const res = await fetch(`${API_BASE}/api/alerts/${id}`, {
    method: "DELETE",
    credentials: "include",
  });
  if (!res.ok) {
    notifyUnauthorized(`/api/alerts/${id}`, res.status);
    throw new Error(`Delete failed: ${res.status} ${res.statusText}`);
  }
};

export const rearmAlert = (id: number): Promise<Alert> =>
  mutate(`/api/alerts/${id}/rearm`, AlertSchema, { method: "POST" });

/** Server-side evaluation of active price alerts against live quotes. The
 *  frontend also evaluates client-side against its quote poll, but POSTs
 *  here so a trip persists (status → triggered) authoritatively. */
export const evaluateAlerts = (): Promise<EvaluateResponse> =>
  mutate("/api/alerts/evaluate", EvaluateResponseSchema, { method: "POST" });
