import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { Trade } from "@/types/journal";

// The inline close form is the only thing in TradeList that mutates; stub it
// so the list renders without a react-query provider.
vi.mock("@/hooks/useTrades", () => ({
  useUpdateTrade: () => ({ mutateAsync: vi.fn(), isPending: false }),
}));

import { TradeList } from "@/components/positions/journal/TradeList";

function makeTrade(overrides: Partial<Trade> = {}): Trade {
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
    status: "open",
    is_paper: true,
    tier: "50K",
    order_type: "limit",
    time_in_force: "gtc",
    tags: [],
    mistake_tags: [],
    created_at: "2026-07-03T14:00:00Z",
    updated_at: "2026-07-03T14:00:00Z",
    ...overrides,
  } as Trade;
}

function renderList(trades: Trade[]) {
  return render(
    <TradeList
      trades={trades}
      scope="all"
      onScopeChange={() => {}}
      selectedSymbol="SPY"
      onAddTrade={() => {}}
    />,
  );
}

/**
 * The screenshot lightbox used to be a keyboard TRAP: role="dialog" with no
 * Escape handler, no close button, and no focusable child — a keyboard user
 * who opened it could never dismiss it. These lock in both exits.
 */
describe("TradeList screenshot lightbox — keyboard dismissal", () => {
  const withShot = () =>
    makeTrade({ screenshot_url: "https://example.test/shot.png" });

  it("closes the lightbox on Escape", async () => {
    renderList([withShot()]);
    await userEvent.click(
      screen.getByRole("button", { name: "View trade screenshot" }),
    );
    expect(screen.getByRole("dialog", { name: "Trade screenshot" })).toBeInTheDocument();

    await userEvent.keyboard("{Escape}");
    expect(
      screen.queryByRole("dialog", { name: "Trade screenshot" }),
    ).not.toBeInTheDocument();
  });

  it("moves focus to a real close button and restores it on dismissal", async () => {
    renderList([withShot()]);
    const thumb = screen.getByRole("button", { name: "View trade screenshot" });
    await userEvent.click(thumb);

    const close = screen.getByRole("button", { name: "Close screenshot" });
    expect(close).toHaveFocus();

    await userEvent.keyboard("{Enter}");
    expect(
      screen.queryByRole("dialog", { name: "Trade screenshot" }),
    ).not.toBeInTheDocument();
    expect(thumb).toHaveFocus();
  });

  it("renders no lightbox at all for a trade without a screenshot", () => {
    renderList([makeTrade()]);
    expect(
      screen.queryByRole("button", { name: "View trade screenshot" }),
    ).not.toBeInTheDocument();
  });
});
