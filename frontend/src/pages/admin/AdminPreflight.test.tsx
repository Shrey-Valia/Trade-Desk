import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AdminPreflight } from "./AdminPreflight";

/**
 * The panel's contract is mostly about when it says NOTHING.
 *
 * It sits at the top of the operator's landing tab, so a version that
 * renders chrome on a clean deployment (or an "all clear" box on a dev box)
 * trains people to scroll past it — and then it fails to be noticed on the
 * one deploy where it matters. These tests pin the silence as hard as they
 * pin the content.
 */

function renderPanel(payload: unknown, { ok = true } = {}) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => ({
      ok,
      status: ok ? 200 : 500,
      statusText: ok ? "OK" : "Server Error",
      json: async () => payload,
    })),
  );
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <AdminPreflight />
    </QueryClientProvider>,
  );
}

const WARNING = {
  level: "warn",
  key: "ADMIN_EMAILS",
  problem: "empty, so no account is auto-promoted at signin",
  fix: 'set ADMIN_EMAILS to a JSON array, e.g. ["you@example.com"]',
};
const BLOCKER = {
  level: "refuse",
  key: "FRONTEND_BASE_URL",
  problem: "links would point at http://localhost:5173",
  fix: "set FRONTEND_BASE_URL to the app's public origin",
};

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("AdminPreflight", () => {
  it("renders nothing when the deployment is clean", async () => {
    const { container } = renderPanel({
      environment: "production",
      is_production: true,
      findings: [],
    });
    await waitFor(() => expect(container).toBeEmptyDOMElement());
  });

  it("renders nothing on a development box", async () => {
    const { container } = renderPanel({
      environment: "development",
      is_production: false,
      findings: [],
    });
    await waitFor(() => expect(container).toBeEmptyDOMElement());
  });

  it("renders nothing while the query is still loading", () => {
    const { container } = renderPanel({
      environment: "production",
      is_production: true,
      findings: [WARNING],
    });
    // Synchronously, before the fetch resolves: no skeleton, no flash.
    expect(container).toBeEmptyDOMElement();
  });

  it("stays silent when the endpoint fails rather than breaking the page", async () => {
    const { container } = renderPanel({ detail: "boom" }, { ok: false });
    await waitFor(() => expect(container).toBeEmptyDOMElement());
    // and still nothing after the query settles
    expect(container).toBeEmptyDOMElement();
  });

  it("shows each finding with its setting, problem and fix", async () => {
    renderPanel({
      environment: "production",
      is_production: true,
      findings: [WARNING],
    });
    expect(await screen.findByText("ADMIN_EMAILS")).toBeInTheDocument();
    expect(screen.getByText(/no account is auto-promoted/)).toBeInTheDocument();
    expect(screen.getByText(/set ADMIN_EMAILS to a JSON array/)).toBeInTheDocument();
    expect(screen.getByText("Warning")).toBeInTheDocument();
  });

  it("distinguishes a blocking finding and counts it in the header", async () => {
    renderPanel({
      environment: "production",
      is_production: true,
      findings: [BLOCKER, WARNING],
    });
    expect(await screen.findByText("Blocking")).toBeInTheDocument();
    expect(screen.getByText("Warning")).toBeInTheDocument();
    expect(screen.getByText(/2 findings · 1 blocking/)).toBeInTheDocument();
  });

  it("does not claim a blocker when there are only warnings", async () => {
    renderPanel({
      environment: "production",
      is_production: true,
      findings: [WARNING],
    });
    expect(await screen.findByText(/1 finding/)).toBeInTheDocument();
    expect(screen.queryByText(/blocking/)).not.toBeInTheDocument();
  });

  it("labels findings as informational outside production", async () => {
    renderPanel({
      environment: "staging",
      is_production: false,
      findings: [WARNING],
    });
    expect(await screen.findByText(/informational/)).toBeInTheDocument();
  });
});
