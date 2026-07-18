import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  acceptDocuments,
  createSupportTicket,
  errorCode,
  errorMessage,
  fetchLegalStatus,
  fetchSupportTickets,
  forgotPassword,
  needsPurchaseConsent,
  resetPassword,
  signFundedAgreement,
  type LegalStatus,
} from "@/lib/legalApi";

// Same approach as api.test.ts: the fetch helpers are module-private, so we
// exercise them through the exported client functions with a stubbed fetch.

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

const CURRENT = { accepted_version: 1, current_version: 1, current: true };
const STALE = { accepted_version: null, current_version: 1, current: false };
const FULL_STATUS = {
  tos: CURRENT,
  privacy: CURRENT,
  refund: CURRENT,
  risk: CURRENT,
  funded_agreement: STALE,
};

describe("legalApi", () => {
  beforeEach(() => vi.unstubAllGlobals());
  afterEach(() => vi.unstubAllGlobals());

  describe("legal status + acceptance", () => {
    it("parses the {doc_key: status} map", async () => {
      mockFetch({ ok: true, status: 200, json: async () => FULL_STATUS });
      const status = await fetchLegalStatus();
      expect(status.tos.current).toBe(true);
      expect(status.funded_agreement.accepted_version).toBeNull();
    });

    it("POSTs doc_keys on accept and sends cookies", async () => {
      mockFetch({ ok: true, status: 200, json: async () => FULL_STATUS });
      await acceptDocuments(["tos", "risk"]);
      const [url, init] = (fetch as unknown as ReturnType<typeof vi.fn>).mock
        .calls[0] as [string, RequestInit];
      expect(url).toBe("/api/legal/accept");
      expect(init.method).toBe("POST");
      expect(init.credentials).toBe("include");
      expect(JSON.parse(init.body as string)).toEqual({
        doc_keys: ["tos", "risk"],
      });
    });

    it("POSTs typed_name on the funded-agreement sign", async () => {
      mockFetch({ ok: true, status: 200, json: async () => FULL_STATUS });
      await signFundedAgreement("Ada Lovelace");
      const [url, init] = (fetch as unknown as ReturnType<typeof vi.fn>).mock
        .calls[0] as [string, RequestInit];
      expect(url).toBe("/api/legal/sign-funded-agreement");
      expect(JSON.parse(init.body as string)).toEqual({
        typed_name: "Ada Lovelace",
      });
    });

    it("needsPurchaseConsent keys on tos + risk currency", () => {
      expect(needsPurchaseConsent(FULL_STATUS as LegalStatus)).toBe(false);
      expect(
        needsPurchaseConsent({ ...FULL_STATUS, risk: STALE } as LegalStatus),
      ).toBe(true);
      expect(
        needsPurchaseConsent({ ...FULL_STATUS, tos: STALE } as LegalStatus),
      ).toBe(true);
      // Unknown yet → don't block; the server-side 403 is the net.
      expect(needsPurchaseConsent(undefined)).toBe(false);
    });
  });

  describe("gate-error helpers", () => {
    it("extracts the snake_case code prefix", () => {
      expect(errorCode(new Error("consent_required: accept the ToS"))).toBe(
        "consent_required",
      );
      expect(errorCode(new Error("agreement_required: sign it"))).toBe(
        "agreement_required",
      );
      expect(errorCode(new Error("invalid_token: expired"))).toBe(
        "invalid_token",
      );
    });

    it("returns null for non-gate errors", () => {
      expect(errorCode(new Error("Something went wrong"))).toBeNull();
      expect(errorCode(new Error("409 Conflict"))).toBeNull();
      expect(errorCode(undefined)).toBeNull();
    });

    it("errorMessage strips the code prefix but keeps plain messages", () => {
      expect(
        errorMessage(new Error("invalid_token: this reset link is invalid")),
      ).toBe("this reset link is invalid");
      expect(errorMessage(new Error("plain failure"))).toBe("plain failure");
    });
  });

  describe("error mapping (mirrors api.ts conventions)", () => {
    it("surfaces the backend detail and carries the status", async () => {
      mockFetch({
        ok: false,
        status: 403,
        statusText: "Forbidden",
        json: async () => ({
          detail: "consent_required: accept the Terms of Service",
        }),
      });
      const err = await fetchLegalStatus().catch((e) => e);
      expect((err as Error).message).toBe(
        "consent_required: accept the Terms of Service",
      );
      expect((err as Error & { status?: number }).status).toBe(403);
      expect(errorCode(err)).toBe("consent_required");
    });

    it("falls back to status + statusText on a non-JSON body", async () => {
      mockFetch({
        ok: false,
        status: 500,
        statusText: "Internal Server Error",
        json: async () => {
          throw new SyntaxError("not json");
        },
      });
      const err = await fetchLegalStatus().catch((e) => e);
      expect((err as Error).message).toBe("500 Internal Server Error");
    });
  });

  describe("account recovery (204 endpoints)", () => {
    it("forgotPassword resolves on 204 with the email body", async () => {
      mockFetch({
        ok: true,
        status: 204,
        json: async () => {
          throw new SyntaxError("no body");
        },
      });
      await expect(forgotPassword("a@b.co")).resolves.toBeUndefined();
      const [url, init] = (fetch as unknown as ReturnType<typeof vi.fn>).mock
        .calls[0] as [string, RequestInit];
      expect(url).toBe("/api/auth/forgot");
      expect(JSON.parse(init.body as string)).toEqual({ email: "a@b.co" });
    });

    it("resetPassword maps token + new_password and surfaces the 400", async () => {
      mockFetch({
        ok: true,
        status: 204,
        json: async () => {
          throw new SyntaxError("no body");
        },
      });
      await resetPassword("tok123456", "hunter22");
      const [url, init] = (fetch as unknown as ReturnType<typeof vi.fn>).mock
        .calls[0] as [string, RequestInit];
      expect(url).toBe("/api/auth/reset");
      expect(JSON.parse(init.body as string)).toEqual({
        token: "tok123456",
        new_password: "hunter22",
      });

      mockFetch({
        ok: false,
        status: 400,
        statusText: "Bad Request",
        json: async () => ({
          detail: "invalid_token: this reset link is invalid or expired",
        }),
      });
      const err = await resetPassword("tok123456", "hunter22").catch((e) => e);
      expect(errorCode(err)).toBe("invalid_token");
    });
  });

  describe("support tickets", () => {
    const ticket = {
      id: 1,
      category: "billing",
      subject: "Double charge",
      body: "Charged twice this month.",
      context: { combine_id: 4, tier: "100K", status: "active" },
      status: "open",
      admin_note: null,
      created_at: "2026-07-14T12:00:00Z",
      updated_at: "2026-07-14T12:00:00Z",
    };

    it("creates a ticket with category/subject/body", async () => {
      mockFetch({ ok: true, status: 201, json: async () => ticket });
      const created = await createSupportTicket({
        category: "billing",
        subject: "Double charge",
        body: "Charged twice this month.",
      });
      expect(created.id).toBe(1);
      const [url, init] = (fetch as unknown as ReturnType<typeof vi.fn>).mock
        .calls[0] as [string, RequestInit];
      expect(url).toBe("/api/support/tickets");
      expect(JSON.parse(init.body as string).category).toBe("billing");
    });

    it("unwraps the tickets list envelope", async () => {
      mockFetch({
        ok: true,
        status: 200,
        json: async () => ({
          tickets: [{ ...ticket, status: "replied", admin_note: "On it." }],
        }),
      });
      const tickets = await fetchSupportTickets();
      expect(tickets).toHaveLength(1);
      expect(tickets[0].admin_note).toBe("On it.");
    });
  });
});
