import { renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api", () => ({
  fetchJournalAnalytics: vi.fn(),
}));

import { fetchJournalAnalytics } from "@/lib/api";
import { useJournalAnalytics } from "@/hooks/useJournalAnalytics";
import { makeQueryWrapper } from "@/test/queryWrapper";

const fetchMock = vi.mocked(fetchJournalAnalytics);

const STUB = { totals: {} } as never;

describe("useJournalAnalytics", () => {
  beforeEach(() => fetchMock.mockResolvedValue(STUB));
  afterEach(() => vi.clearAllMocks());

  it("passes the filters straight through to fetchJournalAnalytics", async () => {
    const { wrapper } = makeQueryWrapper();
    const filters = { paper: true, strategy: "long_call", combineId: 4 };
    const { result } = renderHook(() => useJournalAnalytics(filters), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(fetchMock).toHaveBeenCalledWith(filters);
  });

  it("keys the cache on the filters (changing a filter refetches)", async () => {
    const { client, wrapper } = makeQueryWrapper();
    const { result, rerender } = renderHook(
      ({ f }) => useJournalAnalytics(f),
      { wrapper, initialProps: { f: { strategy: "long_call" } } },
    );
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(fetchMock).toHaveBeenCalledWith({ strategy: "long_call" });

    rerender({ f: { strategy: "long_put" } });
    // A new filter is a new query key → a fetch with the new filter fires.
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith({ strategy: "long_put" }),
    );

    // Both filters live as distinct cache entries under the shared prefix.
    const keys = client
      .getQueryCache()
      .getAll()
      .map((q) => q.queryKey);
    expect(keys).toContainEqual(["journal-analytics", { strategy: "long_call" }]);
    expect(keys).toContainEqual(["journal-analytics", { strategy: "long_put" }]);
  });

  it("defaults to an empty filter object", async () => {
    const { wrapper } = makeQueryWrapper();
    const { result } = renderHook(() => useJournalAnalytics(), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(fetchMock).toHaveBeenCalledWith({});
  });
});
