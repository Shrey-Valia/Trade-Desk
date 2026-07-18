import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  addPayoutMethod,
  fetchPayoutRequests,
  fetchVerificationStatus,
  payoutGateStep,
  payoutRequestsKey,
  removePayoutMethod,
  setDefaultPayoutMethod,
  submitKyc,
  submitTaxProfile,
} from "@/lib/verificationApi";

// Same approach as legalApi.test.ts: the fetch helpers are module-private,
// so we exercise them through the exported client functions with a stubbed
// fetch.

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

const STATUS = {
  kyc: { status: "unverified", reject_reason: null },
  tax: { submitted: false, form_type: null },
  payout_methods: [],
  requirements: { kyc: true, tax: true, method: true },
};

const METHOD = {
  id: 7,
  type: "ach",
  label: "Chase checking",
  is_default: true,
  created_at: "2026-07-15T12:00:00Z",
};

describe("verificationApi", () => {
  beforeEach(() => vi.unstubAllGlobals());
  afterEach(() => vi.unstubAllGlobals());

  describe("status", () => {
    it("parses the composite status payload", async () => {
      mockFetch({
        ok: true,
        status: 200,
        json: async () => ({
          ...STATUS,
          kyc: { status: "rejected", reject_reason: "blurry document" },
          payout_methods: [METHOD],
        }),
      });
      const status = await fetchVerificationStatus();
      expect(status.kyc.status).toBe("rejected");
      expect(status.kyc.reject_reason).toBe("blurry document");
      expect(status.payout_methods[0].label).toBe("Chase checking");
      expect(status.requirements.method).toBe(true);
      const [url, init] = lastCall();
      expect(url).toBe("/api/verification/status");
      expect(init.credentials).toBe("include");
    });
  });

  describe("kyc + tax submits", () => {
    it("POSTs the KYC payload and returns the decided status", async () => {
      mockFetch({
        ok: true,
        status: 200,
        json: async () => ({ status: "verified", reject_reason: null }),
      });
      const out = await submitKyc({
        legal_name: "Ada Lovelace",
        dob: "1990-12-10",
        country: "GB",
        document_type: "passport",
      });
      expect(out.status).toBe("verified");
      const [url, init] = lastCall();
      expect(url).toBe("/api/verification/kyc/submit");
      expect(init.method).toBe("POST");
      expect(JSON.parse(init.body as string)).toEqual({
        legal_name: "Ada Lovelace",
        dob: "1990-12-10",
        country: "GB",
        document_type: "passport",
      });
    });

    it("POSTs the tax profile with nested address and null tin", async () => {
      mockFetch({
        ok: true,
        status: 200,
        json: async () => ({ submitted: true, form_type: "W8BEN" }),
      });
      const out = await submitTaxProfile({
        form_type: "W8BEN",
        legal_name: "Ada Lovelace",
        country: "GB",
        address: {
          line1: "1 Analytical Way",
          city: "London",
          region: "London",
          postal: "EC1A",
          country: "GB",
        },
        tin_last4: null,
      });
      expect(out.form_type).toBe("W8BEN");
      const [url, init] = lastCall();
      expect(url).toBe("/api/verification/tax/submit");
      const body = JSON.parse(init.body as string);
      expect(body.address.line1).toBe("1 Analytical Way");
      expect(body.tin_last4).toBeNull();
    });
  });

  describe("payout methods", () => {
    it("adds a method with rail details", async () => {
      mockFetch({ ok: true, status: 201, json: async () => METHOD });
      const added = await addPayoutMethod({
        type: "ach",
        label: "Chase checking",
        details: { routing_number: "021000021", account_last4: "4321" },
      });
      expect(added.is_default).toBe(true);
      const [url, init] = lastCall();
      expect(url).toBe("/api/verification/methods");
      expect(JSON.parse(init.body as string).details.routing_number).toBe(
        "021000021",
      );
    });

    it("removes a method (204, no body)", async () => {
      mockFetch({
        ok: true,
        status: 204,
        json: async () => {
          throw new SyntaxError("no body");
        },
      });
      await expect(removePayoutMethod(7)).resolves.toBeUndefined();
      const [url, init] = lastCall();
      expect(url).toBe("/api/verification/methods/7");
      expect(init.method).toBe("DELETE");
    });

    it("set-default returns the refreshed masked list", async () => {
      mockFetch({
        ok: true,
        status: 200,
        json: async () => [METHOD, { ...METHOD, id: 8, is_default: false }],
      });
      const list = await setDefaultPayoutMethod(7);
      expect(list).toHaveLength(2);
      const [url, init] = lastCall();
      expect(url).toBe("/api/verification/methods/7/default");
      expect(init.method).toBe("POST");
    });
  });

  describe("payout requests", () => {
    it("parses the adjudication rows", async () => {
      mockFetch({
        ok: true,
        status: 200,
        json: async () => [
          {
            id: 3,
            amount: 500.0,
            state: "denied",
            reason_code: "insufficient_track",
            reason_label: "Insufficient track record",
            note: "Two more winning days needed.",
            requested_at: "2026-07-14T15:00:00Z",
            decided_at: "2026-07-15T09:00:00Z",
          },
        ],
      });
      const rows = await fetchPayoutRequests(12);
      expect(rows[0].state).toBe("denied");
      expect(rows[0].reason_label).toBe("Insufficient track record");
      const [url] = lastCall();
      expect(url).toBe("/api/combines/12/payout-requests");
    });

    it("keys under the combines prefix so payout mutations sweep it", () => {
      expect(payoutRequestsKey(12)).toEqual([
        "combines",
        12,
        "payout-requests",
      ]);
    });
  });

  describe("gate-error routing", () => {
    it("maps each 403 gate code to its readiness step", () => {
      expect(
        payoutGateStep(new Error("kyc_required: verify your identity first")),
      ).toBe("kyc");
      expect(
        payoutGateStep(new Error("tax_profile_required: submit a W-9")),
      ).toBe("tax");
      expect(
        payoutGateStep(new Error("payout_method_required: add a method")),
      ).toBe("method");
    });

    it("returns null for non-gate errors", () => {
      expect(payoutGateStep(new Error("minimum payout is $125"))).toBeNull();
      expect(
        payoutGateStep(new Error("account_suspended: contact support")),
      ).toBeNull();
      expect(payoutGateStep(undefined)).toBeNull();
    });

    it("surfaces the backend detail and carries the status on errors", async () => {
      mockFetch({
        ok: false,
        status: 403,
        statusText: "Forbidden",
        json: async () => ({
          detail: "kyc_required: verify your identity before requesting a payout",
        }),
      });
      const err = await fetchVerificationStatus().catch((e) => e);
      expect((err as Error & { status?: number }).status).toBe(403);
      expect(payoutGateStep(err)).toBe("kyc");
    });
  });
});
