import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { IfLegalContact, LegalEmail, LegalEntityClause } from "./LegalContact";

/**
 * The rule these components exist to enforce: NEVER print a contact or a
 * legal clause the operator hasn't actually supplied.
 *
 * The pages previously hard-coded legal@ / privacy@ / billing@tradedesk.example
 * — addresses that bounce. A contact that silently fails is worse than no
 * contact: a user with a GDPR request follows the instruction, hears nothing,
 * and reasonably concludes they were ignored. So the unconfigured path is
 * tested at least as hard as the configured one.
 */

const UNCONFIGURED = {
  entity_name: "",
  jurisdiction: "",
  contact_email: "",
  contact_address: "",
  configured: false,
};
const CONFIGURED = {
  entity_name: "Example Trading LLC",
  jurisdiction: "Delaware, United States",
  contact_email: "legal@example.com",
  contact_address: "1 Main St, Dover DE 19901",
  configured: true,
};

function renderWith(identity: unknown, ui: React.ReactElement, { ok = true } = {}) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => ({
      ok,
      status: ok ? 200 : 500,
      statusText: ok ? "OK" : "Server Error",
      json: async () => identity,
    })),
  );
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>{ui}</MemoryRouter>
    </QueryClientProvider>,
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("IfLegalContact + LegalEmail", () => {
  const CLAUSE = (
    <IfLegalContact>
      {" "}
      or email <LegalEmail />
    </IfLegalContact>
  );

  it("renders nothing when no contact is configured", async () => {
    const { container } = renderWith(UNCONFIGURED, <>{CLAUSE}</>);
    await waitFor(() => expect(container).toBeEmptyDOMElement());
  });

  it("never renders an @example placeholder address", async () => {
    const { container } = renderWith(UNCONFIGURED, <>{CLAUSE}</>);
    await waitFor(() => expect(container.textContent).not.toMatch(/@/));
  });

  it("does not duplicate a Support link the page already renders", async () => {
    /**
     * The regression: an earlier version emitted its own "open a ticket on
     * the Support page" fallback, so every page read "…on the Support page or
     * open a ticket on the Support page." The clause must contribute NOTHING
     * when unconfigured — the caller owns the Support link.
     */
    const { container } = renderWith(
      UNCONFIGURED,
      <p>
        Questions: open a ticket on the Support page{CLAUSE}.
      </p>,
    );
    await waitFor(() =>
      expect(container.textContent).toBe(
        "Questions: open a ticket on the Support page.",
      ),
    );
    expect(container.textContent?.match(/Support page/g)).toHaveLength(1);
  });

  it("renders nothing while the query is still loading", () => {
    const { container } = renderWith(CONFIGURED, <>{CLAUSE}</>);
    // Synchronously: no flash of a half-formed "or email".
    expect(container).toBeEmptyDOMElement();
  });

  it("renders nothing when the endpoint fails", async () => {
    const { container } = renderWith({ detail: "boom" }, <>{CLAUSE}</>, {
      ok: false,
    });
    await waitFor(() => expect(container).toBeEmptyDOMElement());
  });

  it("renders the clause and a mailto link when configured", async () => {
    const { container } = renderWith(CONFIGURED, <>{CLAUSE}</>);
    const link = await screen.findByRole("link", { name: "legal@example.com" });
    expect(link).toHaveAttribute("href", "mailto:legal@example.com");
    expect(container.textContent).toBe(" or email legal@example.com");
  });
});

describe("LegalEntityClause", () => {
  it("renders nothing when unconfigured", async () => {
    const { container } = renderWith(UNCONFIGURED, <LegalEntityClause />);
    await waitFor(() => expect(container).toBeEmptyDOMElement());
  });

  it("names the operating entity and its jurisdiction", async () => {
    renderWith(CONFIGURED, <LegalEntityClause />);
    expect(await screen.findByText("Example Trading LLC")).toBeInTheDocument();
    expect(
      screen.getByText(/organised under the laws of Delaware, United States/),
    ).toBeInTheDocument();
    expect(screen.getByText(/1 Main St, Dover DE 19901/)).toBeInTheDocument();
  });

  it("states governing law and forum only when a jurisdiction is given", async () => {
    renderWith(CONFIGURED, <LegalEntityClause />);
    expect(
      await screen.findByText(/governed by the laws of Delaware, United States/),
    ).toBeInTheDocument();
    expect(screen.getByText(/exclusive jurisdiction/)).toBeInTheDocument();
  });

  it("omits the governing-law sentence when no jurisdiction is configured", async () => {
    renderWith(
      { ...CONFIGURED, jurisdiction: "", contact_address: "" },
      <LegalEntityClause />,
    );
    expect(await screen.findByText("Example Trading LLC")).toBeInTheDocument();
    expect(screen.queryByText(/governed by the laws of/)).not.toBeInTheDocument();
    expect(screen.queryByText(/organised under the laws of/)).not.toBeInTheDocument();
  });
});
