import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { Trade } from "@/types/journal";

// The note/tag editors are the only mutating pieces; stub the hook so the
// modal renders without a react-query provider.
vi.mock("@/hooks/useTrades", () => ({
  useUpdateTrade: () => ({ mutate: vi.fn(), mutateAsync: vi.fn(), isPending: false }),
}));

import { DayModal } from "@/components/journal/DayModal";

function makeClosedTrade(overrides: Partial<Trade> = {}): Trade {
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
    entry_date: "2026-07-03T14:00:00Z",
    exit_date: "2026-07-03T18:00:00Z",
    entry_underlying_price: 500,
    exit_underlying_price: 503,
    net_debit_credit: 120,
    realized_pnl: 180,
    status: "closed",
    is_paper: true,
    tier: "50K",
    order_type: "limit",
    time_in_force: "gtc",
    tags: [],
    mistake_tags: [],
    screenshot_url: "https://example.test/shot.png",
    created_at: "2026-07-03T14:00:00Z",
    updated_at: "2026-07-03T18:00:00Z",
    ...overrides,
  } as Trade;
}

/**
 * The day-detail lightbox is nested INSIDE the ui/Modal day-review dialog,
 * which owns its own document-capture Escape handler. A naive listener here
 * would close the whole day modal instead of just the image, so the lightbox
 * listens on `window` in the capture phase (which fires first) and stops
 * propagation. These assert that ordering, not just that Escape "works".
 */
describe("DayModal screenshot lightbox — nested Escape", () => {
  it("Escape closes only the lightbox, leaving the day modal open", async () => {
    const onClose = vi.fn();
    render(
      <DayModal date="2026-07-03" trades={[makeClosedTrade()]} onClose={onClose} />,
    );
    await userEvent.click(
      screen.getByRole("button", { name: "View trade screenshot" }),
    );
    expect(screen.getByRole("dialog", { name: "Trade screenshot" })).toBeInTheDocument();

    await userEvent.keyboard("{Escape}");

    expect(
      screen.queryByRole("dialog", { name: "Trade screenshot" }),
    ).not.toBeInTheDocument();
    // The day-review modal must survive the inner dismissal.
    expect(onClose).not.toHaveBeenCalled();
    // …and still be on screen, with its own header ✕ intact.
    expect(screen.getByRole("button", { name: "Close" })).toBeInTheDocument();
  });

  it("a second Escape then closes the day modal itself", async () => {
    const onClose = vi.fn();
    render(
      <DayModal date="2026-07-03" trades={[makeClosedTrade()]} onClose={onClose} />,
    );
    await userEvent.click(
      screen.getByRole("button", { name: "View trade screenshot" }),
    );
    await userEvent.keyboard("{Escape}");
    expect(onClose).not.toHaveBeenCalled();

    await userEvent.keyboard("{Escape}");
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("the lightbox close button is distinctly named from the modal's own Close", async () => {
    render(
      <DayModal date="2026-07-03" trades={[makeClosedTrade()]} onClose={() => {}} />,
    );
    await userEvent.click(
      screen.getByRole("button", { name: "View trade screenshot" }),
    );
    // Both exist and are unambiguous — getByRole throws on duplicates.
    expect(screen.getByRole("button", { name: "Close screenshot" })).toHaveFocus();
    expect(screen.getByRole("button", { name: "Close" })).toBeInTheDocument();
  });
});
