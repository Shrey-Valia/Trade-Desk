import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  fetchNotifications,
  isPayoutNotification,
  markNotificationsRead,
  type Notification,
} from "@/lib/notificationsApi";

// Same approach as legalApi.test.ts: stubbed fetch through the exported
// client functions.

type FetchResponse = {
  ok: boolean;
  status: number;
  statusText?: string;
  json: () => Promise<unknown>;
};

function mockFetch(resp: FetchResponse) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => ({
      ok: resp.ok,
      status: resp.status,
      statusText: resp.statusText ?? "",
      json: resp.json,
    })),
  );
}

function lastCall(): [string, RequestInit] {
  const calls = (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls;
  return calls[calls.length - 1] as [string, RequestInit];
}

const ITEM: Notification = {
  id: 1,
  kind: "payout_approved",
  title: "Payout approved — $500.00",
  body: "Your payout request on 50K COMBINE was approved.",
  read_at: null,
  created_at: "2026-07-15T12:00:00Z",
};

describe("notificationsApi", () => {
  beforeEach(() => vi.unstubAllGlobals());
  afterEach(() => vi.unstubAllGlobals());

  it("parses items + the total unread count", async () => {
    mockFetch({
      ok: true,
      status: 200,
      json: async () => ({ items: [ITEM], unread: 3 }),
    });
    const out = await fetchNotifications();
    expect(out.items[0].kind).toBe("payout_approved");
    expect(out.unread).toBe(3);
    const [url, init] = lastCall();
    expect(url).toBe("/api/notifications");
    expect(init.credentials).toBe("include");
  });

  it("marks specific ids read", async () => {
    mockFetch({
      ok: true,
      status: 204,
      json: async () => {
        throw new SyntaxError("no body");
      },
    });
    await expect(markNotificationsRead([1, 2])).resolves.toBeUndefined();
    const [url, init] = lastCall();
    expect(url).toBe("/api/notifications/read");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual({ ids: [1, 2] });
  });

  it("marks ALL read when ids are omitted (empty body object)", async () => {
    mockFetch({
      ok: true,
      status: 204,
      json: async () => {
        throw new SyntaxError("no body");
      },
    });
    await markNotificationsRead();
    const [, init] = lastCall();
    expect(JSON.parse(init.body as string)).toEqual({});
  });

  it("surfaces the backend detail on errors", async () => {
    mockFetch({
      ok: false,
      status: 401,
      statusText: "Unauthorized",
      json: async () => ({ detail: "not signed in" }),
    });
    const err = await fetchNotifications().catch((e) => e);
    expect((err as Error).message).toBe("not signed in");
    expect((err as Error & { status?: number }).status).toBe(401);
  });

  it("flags payout-lifecycle kinds for the /payouts deep link", () => {
    expect(isPayoutNotification(ITEM)).toBe(true);
    expect(
      isPayoutNotification({ ...ITEM, kind: "payout_denied" }),
    ).toBe(true);
    expect(isPayoutNotification({ ...ITEM, kind: "funded" })).toBe(false);
    expect(isPayoutNotification({ ...ITEM, kind: "renewal" })).toBe(false);
  });
});
