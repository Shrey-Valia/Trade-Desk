import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  MarketDataUnavailableError,
  fetchMarketStatus,
  fetchTrades,
  openZeroDteMultiLeg,
  updateWorkingOrder,
} from "@/lib/api";

// `request()` is module-private; we exercise it through fetchMarketStatus /
// fetchTrades (both go through it) and assert on the parse + error-mapping
// behavior. `fetch` is the only external dependency, so we stub it per test.

type FetchResponse = {
  ok: boolean;
  status: number;
  statusText?: string;
  headers?: Record<string, string>;
  json: () => Promise<unknown>;
};

function mockFetch(resp: FetchResponse) {
  const headers = new Headers(resp.headers ?? {});
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => ({
      ok: resp.ok,
      status: resp.status,
      statusText: resp.statusText ?? "",
      headers,
      json: resp.json,
    })),
  );
}

const OPEN_STATUS = {
  status: "open",
  label: "Open",
  next_open: null,
  next_close: null,
};

describe("api request()", () => {
  beforeEach(() => {
    vi.unstubAllGlobals();
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  describe("happy path", () => {
    it("parses a valid body through the Zod schema", async () => {
      mockFetch({ ok: true, status: 200, json: async () => OPEN_STATUS });
      const data = await fetchMarketStatus();
      expect(data.status).toBe("open");
    });

    it("sends session-cookie credentials", async () => {
      mockFetch({ ok: true, status: 200, json: async () => OPEN_STATUS });
      await fetchMarketStatus();
      expect(fetch).toHaveBeenCalledWith(
        "/api/market/status",
        expect.objectContaining({ credentials: "include" }),
      );
    });

    it("rejects when the body fails schema validation", async () => {
      // Missing the required `status` enum — Zod should throw on .parse().
      mockFetch({ ok: true, status: 200, json: async () => ({ wrong: 1 }) });
      await expect(fetchMarketStatus()).rejects.toThrow();
    });
  });

  describe("error mapping", () => {
    it("surfaces the backend `detail` as the error message", async () => {
      mockFetch({
        ok: false,
        status: 404,
        statusText: "Not Found",
        json: async () => ({ detail: "No 0DTE for SPY today" }),
      });
      await expect(fetchMarketStatus()).rejects.toThrow("No 0DTE for SPY today");
    });

    it("carries the HTTP status on the thrown error", async () => {
      mockFetch({
        ok: false,
        status: 409,
        statusText: "Conflict",
        json: async () => ({ detail: "conflict" }),
      });
      const err = await fetchMarketStatus().catch((e) => e);
      expect((err as Error & { status?: number }).status).toBe(409);
    });

    it("falls back to status + statusText when the body is non-JSON", async () => {
      mockFetch({
        ok: false,
        status: 500,
        statusText: "Internal Server Error",
        json: async () => {
          throw new SyntaxError("not json");
        },
      });
      const err = await fetchMarketStatus().catch((e) => e);
      expect((err as Error).message).toBe("500 Internal Server Error");
      expect((err as Error & { status?: number }).status).toBe(500);
    });
  });

  describe("MarketDataUnavailableError (503 degraded branch)", () => {
    it("throws the typed error with retry_after from the body", async () => {
      mockFetch({
        ok: false,
        status: 503,
        statusText: "Service Unavailable",
        json: async () => ({
          error: "market_data_unavailable",
          retry_after: 12,
          detail: "circuit open",
        }),
      });
      const err = await fetchMarketStatus().catch((e) => e);
      expect(err).toBeInstanceOf(MarketDataUnavailableError);
      expect((err as MarketDataUnavailableError).retryAfter).toBe(12);
      expect((err as Error).message).toBe("circuit open");
    });

    it("falls back to the Retry-After header when the body lacks retry_after", async () => {
      mockFetch({
        ok: false,
        status: 503,
        statusText: "Service Unavailable",
        headers: { "Retry-After": "45" },
        json: async () => ({
          error: "market_data_unavailable",
          detail: "degraded",
        }),
      });
      const err = await fetchMarketStatus().catch((e) => e);
      expect(err).toBeInstanceOf(MarketDataUnavailableError);
      expect((err as MarketDataUnavailableError).retryAfter).toBe(45);
    });

    it("treats an absent Retry-After header as 0 (Number(null) === 0, which is finite)", async () => {
      // Source detail: with no body retry_after and no header, headerRa is
      // Number(null) === 0, which IS finite — so retryAfter resolves to 0,
      // not the 30 default. The 30 fallback only fires when BOTH values are
      // non-finite (see next test).
      mockFetch({
        ok: false,
        status: 503,
        statusText: "Service Unavailable",
        json: async () => ({ error: "market_data_unavailable", detail: "x" }),
      });
      const err = await fetchMarketStatus().catch((e) => e);
      expect((err as MarketDataUnavailableError).retryAfter).toBe(0);
    });

    it("defaults retryAfter to 30 when the header is present but non-numeric", async () => {
      // Number("soon") is NaN (non-finite) — the only path that reaches the
      // 30 default.
      mockFetch({
        ok: false,
        status: 503,
        statusText: "Service Unavailable",
        headers: { "Retry-After": "soon" },
        json: async () => ({ error: "market_data_unavailable", detail: "x" }),
      });
      const err = await fetchMarketStatus().catch((e) => e);
      expect((err as MarketDataUnavailableError).retryAfter).toBe(30);
    });

    it("does NOT use the typed error for a plain 503 without the marker", async () => {
      // A generic 503 (no `error: market_data_unavailable`) is a normal
      // status-carrying error, not the degraded-data path.
      mockFetch({
        ok: false,
        status: 503,
        statusText: "Service Unavailable",
        json: async () => ({ detail: "upstream down" }),
      });
      const err = await fetchMarketStatus().catch((e) => e);
      expect(err).not.toBeInstanceOf(MarketDataUnavailableError);
      expect((err as Error & { status?: number }).status).toBe(503);
      expect((err as Error).message).toBe("upstream down");
    });
  });

  describe("fetchTrades filter → query string", () => {
    const empty = { trades: [] };

    it("omits the query string when no filters are passed", async () => {
      mockFetch({ ok: true, status: 200, json: async () => empty });
      await fetchTrades();
      expect(fetch).toHaveBeenCalledWith(
        "/api/journal/trades",
        expect.anything(),
      );
    });

    it("serializes status / is_paper / symbol filters", async () => {
      mockFetch({ ok: true, status: 200, json: async () => empty });
      await fetchTrades({ status: "open", isPaper: true, symbol: "SPY" });
      const url = (fetch as unknown as ReturnType<typeof vi.fn>).mock
        .calls[0][0] as string;
      expect(url).toContain("/api/journal/trades?");
      expect(url).toContain("status=open");
      expect(url).toContain("is_paper=true");
      expect(url).toContain("symbol=SPY");
    });

    it("includes is_paper=false (the falsy-but-defined filter)", async () => {
      mockFetch({ ok: true, status: 200, json: async () => empty });
      await fetchTrades({ isPaper: false });
      const url = (fetch as unknown as ReturnType<typeof vi.fn>).mock
        .calls[0][0] as string;
      expect(url).toContain("is_paper=false");
    });
  });

  describe("updateWorkingOrder (PATCH .../order)", () => {
    // Minimal-but-valid TradeOut body — defaults fill tier/order_type/tif/tags.
    const workingTrade = {
      id: 7,
      symbol: "SPY",
      strategy: "long_call",
      legs: [
        {
          side: "call",
          action: "buy",
          strike: 500,
          expiry: "2026-07-03",
          contracts: 1,
          entry_price: 1.2,
        },
      ],
      entry_date: "2026-07-03",
      entry_underlying_price: 500,
      net_debit_credit: 120,
      status: "working",
      is_paper: true,
      created_at: "2026-07-03T14:00:00Z",
      updated_at: "2026-07-03T14:00:00Z",
    };

    it("PATCHes the order endpoint with exactly the given patch body", async () => {
      mockFetch({ ok: true, status: 200, json: async () => workingTrade });
      await updateWorkingOrder(7, {
        limit_price: 1.35,
        time_in_force: "day",
      });
      const [url, init] = (fetch as unknown as ReturnType<typeof vi.fn>).mock
        .calls[0] as [string, RequestInit];
      expect(url).toBe("/api/journal/trades/7/order");
      expect(init.method).toBe("PATCH");
      expect(JSON.parse(init.body as string)).toEqual({
        limit_price: 1.35,
        time_in_force: "day",
      });
    });

    it("tolerates trades WITHOUT premium-mult fields and parses ones WITH them", async () => {
      mockFetch({ ok: true, status: 200, json: async () => workingTrade });
      const bare = await updateWorkingOrder(7, { limit_price: 1.5 });
      expect(bare.tp_premium_mult).toBeUndefined();
      mockFetch({
        ok: true,
        status: 200,
        json: async () => ({
          ...workingTrade,
          tp_premium_mult: 2,
          sl_premium_mult: 0.5,
        }),
      });
      const withMults = await updateWorkingOrder(7, { limit_price: 1.5 });
      expect(withMults.tp_premium_mult).toBe(2);
      expect(withMults.sl_premium_mult).toBe(0.5);
    });

    it("surfaces the 409 detail verbatim when the order is no longer working", async () => {
      mockFetch({
        ok: false,
        status: 409,
        statusText: "Conflict",
        json: async () => ({ detail: "Order is no longer working" }),
      });
      await expect(updateWorkingOrder(7, { limit_price: 1.5 })).rejects.toThrow(
        "Order is no longer working",
      );
    });
  });

  describe("openZeroDteMultiLeg net-limit passthrough", () => {
    it("serializes order_type + limit_price when present, untouched", async () => {
      mockFetch({
        ok: false,
        status: 400,
        statusText: "Bad Request",
        json: async () => ({ detail: "x" }),
      });
      await openZeroDteMultiLeg({
        symbol: "SPY",
        contracts: 1,
        legs: [{ side: "call", action: "buy", strike: 500, ratio: 1 }],
        strategy: "custom",
        order_type: "limit",
        limit_price: -0.55,
      }).catch(() => undefined);
      const [url, init] = (fetch as unknown as ReturnType<typeof vi.fn>).mock
        .calls[0] as [string, RequestInit];
      expect(url).toBe("/api/zerodte/open-multi");
      const body = JSON.parse(init.body as string);
      expect(body.order_type).toBe("limit");
      expect(body.limit_price).toBe(-0.55);
    });
  });
});
