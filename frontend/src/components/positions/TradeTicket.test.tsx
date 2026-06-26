import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { TicketSelection } from "@/stores/tradeTicket";

// ── Mock every hook the ticket consumes ─────────────────────────────────────
// The component's canFire/validation logic is the unit under test; the data
// hooks are mocked so we can drive market-open, the scaling cap, and the
// combine lock independently. The two open-mutation hooks return spies so we
// can assert what the ticket fires.

const legMutate = vi.fn();
const straddleMutate = vi.fn();

const accountStateRef = { current: undefined as unknown };
const tradesRef = { current: { trades: [] as unknown[] } };
const marketStatusRef = { current: { status: "open" } as { status: string } };
const combineStatusRef = {
  current: {
    passed: false,
    dayLocked: false,
    status: "active" as string,
    dll_used: 0,
  },
};

vi.mock("@/hooks/useAccountState", () => ({
  useAccountState: () => ({ data: accountStateRef.current }),
}));
vi.mock("@/hooks/useTrades", () => ({
  useTrades: () => ({ data: tradesRef.current }),
}));
vi.mock("@/hooks/useMarket", () => ({
  useMarketStatus: () => ({ data: marketStatusRef.current }),
}));
vi.mock("@/hooks/useCombineStatus", () => ({
  useCombineStatus: () => combineStatusRef.current,
}));
vi.mock("@/hooks/useOpenZeroDteLeg", () => ({
  useOpenZeroDteLeg: () => ({
    mutate: legMutate,
    isPending: false,
    isError: false,
    error: null,
  }),
}));
vi.mock("@/hooks/useOpenZeroDteStraddle", () => ({
  useOpenZeroDteStraddle: () => ({
    mutate: straddleMutate,
    isPending: false,
    isError: false,
    error: null,
  }),
}));

import { TradeTicket } from "@/components/positions/TradeTicket";
import { useTradeTicket } from "@/stores/tradeTicket";

const legSel: TicketSelection = {
  kind: "leg",
  symbol: "SPY",
  strike: 500,
  side: "call",
  price: 1.0,
  expiry: "2026-06-26",
};

function seedSelection(sel: TicketSelection) {
  useTradeTicket.getState().setSelection(sel);
}

function resetTicketStore() {
  useTradeTicket.setState(
    {
      selection: null,
      contracts: 1,
      orderType: "market",
      limitPrice: null,
      stopPrice: null,
      trailAmount: null,
      timeInForce: "gtc",
    },
    false,
  );
}

const buyBtn = () => screen.getByRole("button", { name: /BUY \+/ });
const sellBtn = () => screen.getByRole("button", { name: /SELL -/ });

describe("TradeTicket validation / canFire", () => {
  beforeEach(() => {
    resetTicketStore();
    accountStateRef.current = { max_contracts: 5, active_tier: "50K" };
    tradesRef.current = { trades: [] };
    marketStatusRef.current = { status: "open" };
    combineStatusRef.current = {
      passed: false,
      dayLocked: false,
      status: "active",
      dll_used: 0,
    };
  });
  afterEach(() => vi.clearAllMocks());

  it("renders the compact empty state with disabled buttons when nothing is selected", () => {
    render(<TradeTicket />);
    // Empty-state BUY/SELL have no +N / -N suffix and are disabled.
    const buy = screen.getByRole("button", { name: "BUY" });
    const sell = screen.getByRole("button", { name: "SELL" });
    expect(buy).toBeDisabled();
    expect(sell).toBeDisabled();
  });

  it("enables BUY/SELL once a strike is selected and the market is open", () => {
    seedSelection(legSel);
    render(<TradeTicket />);
    expect(buyBtn()).toBeEnabled();
    expect(sellBtn()).toBeEnabled();
  });

  it("fires a leg BUY mutation with the selection payload", async () => {
    seedSelection(legSel);
    render(<TradeTicket />);
    await userEvent.click(buyBtn());
    expect(legMutate).toHaveBeenCalledTimes(1);
    const [payload] = legMutate.mock.calls[0];
    expect(payload).toMatchObject({
      symbol: "SPY",
      side: "call",
      action: "buy",
      strike: 500,
      contracts: 1,
      order_type: "market",
    });
  });

  it("fires a SELL with action=sell", async () => {
    seedSelection(legSel);
    render(<TradeTicket />);
    await userEvent.click(sellBtn());
    expect(legMutate).toHaveBeenCalledWith(
      expect.objectContaining({ action: "sell" }),
      expect.anything(),
    );
  });

  describe("market-open gate", () => {
    it("disables firing when the market is closed", () => {
      marketStatusRef.current = { status: "closed" };
      seedSelection(legSel);
      render(<TradeTicket />);
      expect(buyBtn()).toBeDisabled();
      expect(sellBtn()).toBeDisabled();
    });
  });

  describe("scaling-cap gate", () => {
    it("blocks the BUY and shows the cap banner when at the scaling cap", () => {
      // max_contracts 5, already 5 open on the active tier → remaining 0.
      accountStateRef.current = { max_contracts: 5, active_tier: "50K" };
      tradesRef.current = {
        trades: [
          {
            status: "open",
            tier: "50K",
            legs: [{ contracts: 5 }],
          },
        ],
      };
      seedSelection(legSel);
      render(<TradeTicket />);
      expect(buyBtn()).toBeDisabled();
      expect(screen.getByText(/Scaling plan: 5\/5 contracts open/)).toBeInTheDocument();
    });

    it("allows firing when there is remaining capacity under the cap", () => {
      accountStateRef.current = { max_contracts: 5, active_tier: "50K" };
      tradesRef.current = {
        trades: [{ status: "open", tier: "50K", legs: [{ contracts: 2 }] }],
      };
      seedSelection(legSel);
      render(<TradeTicket />);
      // remaining = 5 - 2 = 3, contracts defaults to 1 → can fire.
      expect(buyBtn()).toBeEnabled();
    });
  });

  describe("stop-limit validation", () => {
    it("disables firing when stop-limit is selected but the arm price is cleared", async () => {
      seedSelection(legSel);
      render(<TradeTicket />);
      // Switch to stop-limit order type.
      await userEvent.click(screen.getByRole("button", { name: "stop lim" }));
      // Clear the arm (stop) price input → stopOk false → cannot fire.
      const armInput = screen.getByLabelText("Stop arm price (option premium)");
      await userEvent.clear(armInput);
      expect(buyBtn()).toBeDisabled();
    });

    it("re-enables firing once both stop and limit prices are valid", async () => {
      seedSelection(legSel);
      render(<TradeTicket />);
      await userEvent.click(screen.getByRole("button", { name: "stop lim" }));
      // setSelection seeded both limit and stop to the indicative price (1.0),
      // so the order is valid out of the box.
      expect(buyBtn()).toBeEnabled();
      await userEvent.click(buyBtn());
      const [payload] = legMutate.mock.calls[0];
      expect(payload).toMatchObject({
        order_type: "stop_limit",
        limit_price: 1.0,
        stop_price: 1.0,
      });
    });
  });

  describe("combine soft-gate", () => {
    it("blocks firing and shows the lock banner when day-locked", () => {
      combineStatusRef.current = {
        passed: false,
        dayLocked: true,
        status: "active",
        dll_used: 0,
      };
      seedSelection(legSel);
      render(<TradeTicket />);
      expect(buyBtn()).toBeDisabled();
      expect(screen.getByText(/DAY LOCK/)).toBeInTheDocument();
    });

    it("blocks firing when the account is FAILED", () => {
      combineStatusRef.current = {
        passed: false,
        dayLocked: false,
        status: "failed",
        dll_used: 0,
      };
      seedSelection(legSel);
      render(<TradeTicket />);
      expect(buyBtn()).toBeDisabled();
      expect(screen.getByText(/Account FAILED/)).toBeInTheDocument();
    });
  });
});
