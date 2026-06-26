import { renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// Mock the api module so the hooks exercise their query-key / invalidation
// wiring without touching fetch. Each export is a vi.fn we can assert on.
vi.mock("@/lib/api", () => ({
  fetchTrades: vi.fn(),
  createTrade: vi.fn(),
  deleteTrade: vi.fn(),
  updateTrade: vi.fn(),
  cancelOrder: vi.fn(),
  setBrackets: vi.fn(),
  uploadTradeScreenshot: vi.fn(),
}));

// Silence toast side-effects from mutation onError/onSuccess.
vi.mock("@/stores/toast", () => ({
  toast: { error: vi.fn(), info: vi.fn(), success: vi.fn(), warning: vi.fn() },
}));

import {
  cancelOrder,
  createTrade,
  deleteTrade,
  fetchTrades,
} from "@/lib/api";
import {
  useCancelOrder,
  useCreateTrade,
  useDeleteTrade,
  useTrades,
} from "@/hooks/useTrades";
import { makeQueryWrapper } from "@/test/queryWrapper";

const fetchTradesMock = vi.mocked(fetchTrades);
const createTradeMock = vi.mocked(createTrade);
const deleteTradeMock = vi.mocked(deleteTrade);
const cancelOrderMock = vi.mocked(cancelOrder);

const EMPTY = { trades: [] };

describe("useTrades", () => {
  beforeEach(() => {
    fetchTradesMock.mockResolvedValue(EMPTY);
  });
  afterEach(() => vi.clearAllMocks());

  it("calls fetchTrades with the passed filters", async () => {
    const { wrapper } = makeQueryWrapper();
    const filters = { status: "open" as const, isPaper: true };
    const { result } = renderHook(() => useTrades(filters), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(fetchTradesMock).toHaveBeenCalledWith(filters);
  });

  it("keys the cache on the filters so different filters fetch separately", async () => {
    const { client, wrapper } = makeQueryWrapper();
    const { result, rerender } = renderHook(
      ({ f }) => useTrades(f),
      { wrapper, initialProps: { f: { status: "open" as const } } },
    );
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(fetchTradesMock).toHaveBeenCalledWith({ status: "open" });

    rerender({ f: { status: "closed" as const } });
    await waitFor(() =>
      expect(fetchTradesMock).toHaveBeenCalledWith({ status: "closed" }),
    );

    // Two distinct cache entries under the shared ["journal","trades"] prefix.
    const keys = client
      .getQueryCache()
      .getAll()
      .map((q) => q.queryKey);
    expect(keys).toContainEqual(["journal", "trades", { status: "open" }]);
    expect(keys).toContainEqual(["journal", "trades", { status: "closed" }]);
  });
});

describe("useCreateTrade", () => {
  afterEach(() => vi.clearAllMocks());

  it("invalidates the trades list on success", async () => {
    fetchTradesMock.mockResolvedValue(EMPTY);
    createTradeMock.mockResolvedValue({ id: 1 } as never);
    const { client, wrapper } = makeQueryWrapper();

    // Prime a trades query so there's something to invalidate.
    renderHook(() => useTrades({}), { wrapper });
    const invalidateSpy = vi.spyOn(client, "invalidateQueries");

    const { result } = renderHook(() => useCreateTrade(), { wrapper });
    result.current.mutate({} as never);

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(createTradeMock).toHaveBeenCalled();
    expect(invalidateSpy).toHaveBeenCalledWith({
      queryKey: ["journal", "trades"],
    });
  });

  it("does NOT invalidate on error", async () => {
    createTradeMock.mockRejectedValue(new Error("nope"));
    const { client, wrapper } = makeQueryWrapper();
    const invalidateSpy = vi.spyOn(client, "invalidateQueries");

    const { result } = renderHook(() => useCreateTrade(), { wrapper });
    result.current.mutate({} as never);

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(invalidateSpy).not.toHaveBeenCalled();
  });
});

describe("useDeleteTrade", () => {
  afterEach(() => vi.clearAllMocks());

  it("invalidates the trades list on success", async () => {
    deleteTradeMock.mockResolvedValue(undefined);
    const { client, wrapper } = makeQueryWrapper();
    const invalidateSpy = vi.spyOn(client, "invalidateQueries");

    const { result } = renderHook(() => useDeleteTrade(), { wrapper });
    result.current.mutate(7);

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(deleteTradeMock).toHaveBeenCalledWith(7);
    expect(invalidateSpy).toHaveBeenCalledWith({
      queryKey: ["journal", "trades"],
    });
  });
});

describe("useCancelOrder", () => {
  afterEach(() => vi.clearAllMocks());

  it("invalidates the trades list on success", async () => {
    cancelOrderMock.mockResolvedValue({ id: 3 } as never);
    const { client, wrapper } = makeQueryWrapper();
    const invalidateSpy = vi.spyOn(client, "invalidateQueries");

    const { result } = renderHook(() => useCancelOrder(), { wrapper });
    result.current.mutate(3);

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(cancelOrderMock).toHaveBeenCalledWith(3);
    expect(invalidateSpy).toHaveBeenCalledWith({
      queryKey: ["journal", "trades"],
    });
  });
});
