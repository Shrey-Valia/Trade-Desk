import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Trade } from "@/types/journal";

// ── Mocks ────────────────────────────────────────────────────────────────────
// useTrades feeds the strip from a ref; useCancelOrder is a spy. The PATCH
// helper is mocked at the api boundary so the inline useMutation (real
// react-query, provider below) exercises the component's success/error wiring.

const tradesRef = { current: { trades: [] as Trade[] } };
const cancelMutate = vi.fn();

vi.mock("@/hooks/useTrades", () => ({
  useTrades: () => ({ data: tradesRef.current }),
  useCancelOrder: () => ({ mutate: cancelMutate, isPending: false }),
}));

const updateWorkingOrderMock = vi.fn();
vi.mock("@/lib/api", () => ({
  updateWorkingOrder: (...args: unknown[]) => updateWorkingOrderMock(...args),
}));

import {
  WorkingOrders,
  describePremiumMults,
  describeWorkingLegs,
} from "@/components/positions/WorkingOrders";

function makeTrade(overrides: Partial<Trade>): Trade {
  return {
    id: 1,
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
    tier: "50K",
    order_type: "limit",
    time_in_force: "gtc",
    limit_price: 1.2,
    tags: [],
    mistake_tags: [],
    created_at: "2026-07-03T14:00:00Z",
    updated_at: "2026-07-03T14:00:00Z",
    ...overrides,
  } as Trade;
}

function renderStrip() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <WorkingOrders />
    </QueryClientProvider>,
  );
}

describe("WorkingOrders edit affordance", () => {
  beforeEach(() => {
    tradesRef.current = { trades: [makeTrade({})] };
  });
  afterEach(() => vi.clearAllMocks());

  it("renders nothing when there are no working orders", () => {
    tradesRef.current = { trades: [] };
    const { container } = renderStrip();
    expect(container).toBeEmptyDOMElement();
  });

  it("toggles the edit form and PATCHes new price + TIF on save", async () => {
    updateWorkingOrderMock.mockResolvedValue(makeTrade({ limit_price: 1.35 }));
    renderStrip();
    await userEvent.click(screen.getByRole("button", { name: "Edit order" }));
    const limitInput = screen.getByLabelText("Edit limit price");
    await userEvent.clear(limitInput);
    await userEvent.type(limitInput, "1.35");
    await userEvent.click(screen.getByRole("button", { name: "day" }));
    await userEvent.click(screen.getByRole("button", { name: "save" }));
    await waitFor(() => expect(updateWorkingOrderMock).toHaveBeenCalledTimes(1));
    expect(updateWorkingOrderMock).toHaveBeenCalledWith(1, {
      limit_price: 1.35,
      time_in_force: "day",
    });
    // Success closes the form.
    await waitFor(() =>
      expect(screen.queryByLabelText("Edit limit price")).not.toBeInTheDocument(),
    );
  });

  it("shows the stop arm input only for stop_limit and includes it in the patch", async () => {
    tradesRef.current = {
      trades: [
        makeTrade({ order_type: "stop_limit", limit_price: 1.2, stop_price: 1.0 }),
      ],
    };
    updateWorkingOrderMock.mockResolvedValue(makeTrade({}));
    renderStrip();
    await userEvent.click(screen.getByRole("button", { name: "Edit order" }));
    const armInput = screen.getByLabelText("Edit stop arm price");
    await userEvent.clear(armInput);
    await userEvent.type(armInput, "1.10");
    await userEvent.click(screen.getByRole("button", { name: "save" }));
    await waitFor(() => expect(updateWorkingOrderMock).toHaveBeenCalledTimes(1));
    expect(updateWorkingOrderMock).toHaveBeenCalledWith(1, {
      limit_price: 1.2,
      stop_price: 1.1,
      time_in_force: "gtc",
    });
  });

  it("hides the arm input for a plain limit order", async () => {
    renderStrip();
    await userEvent.click(screen.getByRole("button", { name: "Edit order" }));
    expect(screen.queryByLabelText("Edit stop arm price")).not.toBeInTheDocument();
  });

  it("surfaces the 409 detail verbatim and keeps the form open", async () => {
    updateWorkingOrderMock.mockRejectedValue(
      new Error("Order is no longer working — it filled at 14:31 ET"),
    );
    renderStrip();
    await userEvent.click(screen.getByRole("button", { name: "Edit order" }));
    await userEvent.click(screen.getByRole("button", { name: "save" }));
    expect(
      await screen.findByText("Order is no longer working — it filled at 14:31 ET"),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Edit limit price")).toBeInTheDocument();
  });

  it("disables save when the single-leg premium is cleared (must be > 0)", async () => {
    renderStrip();
    await userEvent.click(screen.getByRole("button", { name: "Edit order" }));
    await userEvent.clear(screen.getByLabelText("Edit limit price"));
    expect(screen.getByRole("button", { name: "save" })).toBeDisabled();
  });
});

describe("WorkingOrders row display", () => {
  afterEach(() => vi.clearAllMocks());

  it("shows the premium TP/SL mults when present on the trade", () => {
    tradesRef.current = {
      trades: [makeTrade({ tp_premium_mult: 2, sl_premium_mult: 0.5 })],
    };
    renderStrip();
    expect(screen.getByText("tp 2× · sl 0.5×")).toBeInTheDocument();
  });

  it("renders a multi-leg working order with every leg and a net trigger", () => {
    tradesRef.current = {
      trades: [
        makeTrade({
          strategy: "iron_condor",
          order_type: "limit",
          limit_price: -0.55, // net credit
          legs: [
            { side: "put", action: "buy", strike: 490, expiry: "2026-07-03", contracts: 1, entry_price: 0.4 },
            { side: "put", action: "sell", strike: 495, expiry: "2026-07-03", contracts: 1, entry_price: 0.9 },
            { side: "call", action: "sell", strike: 505, expiry: "2026-07-03", contracts: 1, entry_price: 0.8 },
            { side: "call", action: "buy", strike: 510, expiry: "2026-07-03", contracts: 1, entry_price: 0.35 },
          ],
        }),
      ],
    };
    renderStrip();
    expect(screen.getByText("net limit")).toBeInTheDocument();
    expect(
      screen.getByText(/iron condor \+490P −495P −505C \+510C/),
    ).toBeInTheDocument();
    // Negative net limit reads as a credit, not a bare minus.
    expect(screen.getByText(/waiting @ \$0\.55 credit/)).toBeInTheDocument();
  });
});

/**
 * OCO select mode used to be mouse-only: the row <div> carried
 * role="checkbox" + aria-checked but no tabIndex and no onKeyDown, so rows
 * were neither reachable by Tab nor activatable by Space/Enter — and the
 * row's own edit/oco/cancel buttons were nested inside the checkbox role.
 * The checkbox is now the ☑/☐ indicator itself.
 */
describe("WorkingOrders OCO selection — keyboard", () => {
  beforeEach(() => {
    tradesRef.current = {
      trades: [
        makeTrade({ id: 1, symbol: "SPY" }),
        makeTrade({ id: 2, symbol: "QQQ" }),
      ],
    };
  });
  afterEach(() => vi.clearAllMocks());

  const enterSelectMode = () =>
    userEvent.click(screen.getByRole("button", { name: "link OCO" }));

  it("exposes one named checkbox per row once select mode is on", async () => {
    renderStrip();
    expect(screen.queryAllByRole("checkbox")).toHaveLength(0);
    await enterSelectMode();
    const boxes = screen.getAllByRole("checkbox");
    expect(boxes).toHaveLength(2);
    expect(
      screen.getByRole("checkbox", {
        name: "Select SPY limit order for OCO pairing",
      }),
    ).toBeInTheDocument();
    boxes.forEach((b) => expect(b).toHaveAttribute("aria-checked", "false"));
  });

  it("is reachable by Tab and togglable by Space", async () => {
    renderStrip();
    await enterSelectMode();
    const first = screen.getByRole("checkbox", {
      name: "Select SPY limit order for OCO pairing",
    });

    // Tab must land on the checkbox — it's a real focusable control now.
    first.focus();
    expect(first).toHaveFocus();

    await userEvent.keyboard(" ");
    expect(
      screen.getByRole("checkbox", {
        name: "Select SPY limit order for OCO pairing",
      }),
    ).toHaveAttribute("aria-checked", "true");

    // Space again unselects (toggle), keeping the mouse behaviour.
    await userEvent.keyboard(" ");
    expect(
      screen.getByRole("checkbox", {
        name: "Select SPY limit order for OCO pairing",
      }),
    ).toHaveAttribute("aria-checked", "false");
  });

  it("enables LINK once two rows are checked from the keyboard", async () => {
    renderStrip();
    await enterSelectMode();
    expect(screen.getByRole("button", { name: /link 0/ })).toBeDisabled();

    for (const sym of ["SPY", "QQQ"]) {
      const box = screen.getByRole("checkbox", {
        name: `Select ${sym} limit order for OCO pairing`,
      });
      box.focus();
      await userEvent.keyboard("{Enter}");
    }
    expect(screen.getByRole("button", { name: /link 2/ })).toBeEnabled();
  });

  it("does not nest the row's action buttons inside the checkbox", async () => {
    renderStrip();
    await enterSelectMode();
    const box = screen.getByRole("checkbox", {
      name: "Select SPY limit order for OCO pairing",
    });
    expect(box.querySelector("button")).toBeNull();
    expect(
      screen.getAllByRole("button", { name: "Edit order" })[0].closest("[role='checkbox']"),
    ).toBeNull();
  });
});

describe("display helpers", () => {
  it("describeWorkingLegs marks ratios and sides compactly", () => {
    expect(
      describeWorkingLegs([
        { side: "call", action: "buy", strike: 495, expiry: "e", contracts: 1, entry_price: 1 },
        { side: "call", action: "sell", strike: 500, expiry: "e", contracts: 2, entry_price: 1 },
        { side: "call", action: "buy", strike: 505, expiry: "e", contracts: 1, entry_price: 1 },
      ]),
    ).toBe("+495C −2×500C +505C");
  });

  it("describePremiumMults handles each presence combination", () => {
    expect(describePremiumMults({ tp_premium_mult: 2, sl_premium_mult: 0.5 })).toBe(
      "tp 2× · sl 0.5×",
    );
    expect(describePremiumMults({ tp_premium_mult: 1.5 })).toBe("tp 1.5×");
    expect(describePremiumMults({ sl_premium_mult: 0.25 })).toBe("sl 0.25×");
    expect(describePremiumMults({})).toBeNull();
  });
});
