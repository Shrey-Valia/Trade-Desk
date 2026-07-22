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
// The empty-state TOOLS section can mount the multi-leg builder, which pulls
// the chain + the multi-leg open mutation — mock both so no provider/network
// is needed and the builder binds to whatever symbol the ticket threads in.
vi.mock("@/hooks/useChainTable", () => ({
  useChainTable: () => ({
    data: {
      atm_strike: 500,
      rows: [
        { strike: 495, call_price: 6.0, put_price: 0.5 },
        { strike: 500, call_price: 2.0, put_price: 1.8 },
        { strike: 505, call_price: 0.6, put_price: 4.9 },
      ],
    },
  }),
}));
vi.mock("@/hooks/useOpenZeroDteMultiLeg", () => ({
  useOpenZeroDteMultiLeg: () => ({
    mutate: vi.fn(),
    isPending: false,
    isError: false,
    error: null,
  }),
}));
// The builder's risk graph polls the multi-leg preview endpoint — stub it
// out so mounting the TOOLS tab needs no QueryClientProvider/network.
vi.mock("@/hooks/useMultiLegPreview", () => ({
  useMultiLegPreview: () => ({ data: undefined, isLoading: false }),
}));

import { TradeTicket } from "@/components/positions/TradeTicket";
import { useSelectedTicker } from "@/stores/selectedTicker";
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
    useSelectedTicker.setState({ symbol: "SPY" });
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

  describe("empty-state TOOLS (builder reachable without a chain selection)", () => {
    it("renders the tools tab bar collapsed by default when nothing is selected", () => {
      render(<TradeTicket />);
      expect(screen.getByRole("button", { name: "build" })).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "size" })).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "sim" })).toBeInTheDocument();
      // Collapsed: no tool panel mounted until a tab is clicked.
      expect(screen.queryByText("Strategy builder")).not.toBeInTheDocument();
    });

    it("opens the multi-leg builder bound to the CHARTED symbol", async () => {
      useSelectedTicker.setState({ symbol: "QQQ" });
      render(<TradeTicket />);
      await userEvent.click(screen.getByRole("button", { name: "build" }));
      expect(screen.getByText("Strategy builder")).toBeInTheDocument();
      expect(screen.getByText(/QQQ · ATM 500/)).toBeInTheDocument();
    });

    it("prefers the selection's symbol over the charted one when a leg IS selected", async () => {
      useSelectedTicker.setState({ symbol: "QQQ" });
      seedSelection(legSel); // SPY
      render(<TradeTicket />);
      await userEvent.click(screen.getByRole("button", { name: "build" }));
      expect(screen.getByText(/SPY · ATM 500/)).toBeInTheDocument();
    });

    it("hides the tools when no symbol is charted at all", () => {
      useSelectedTicker.setState({ symbol: null });
      render(<TradeTicket />);
      expect(
        screen.queryByRole("button", { name: "build" }),
      ).not.toBeInTheDocument();
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

  describe("fat-finger rails (arm → confirm)", () => {
    it("arms on a large-notional order and fires on the confirming press", async () => {
      // $30 premium × 100 × 1 = $3,000 > the $2,500 large-order rail.
      seedSelection({ ...legSel, price: 30.0 });
      render(<TradeTicket />);
      await userEvent.click(buyBtn());
      expect(legMutate).not.toHaveBeenCalled();
      expect(screen.getByText(/large order/)).toBeInTheDocument();
      // Button relabels to CONFIRM; the second press fires through.
      const confirm = screen.getByRole("button", { name: /CONFIRM \+/ });
      await userEvent.click(confirm);
      expect(legMutate).toHaveBeenCalledTimes(1);
    });

    it("arms when the identical order is re-fired within 10s", async () => {
      // The spy must settle the mutation, else the synchronous double-click
      // guard (submittingRef) blocks every fire after the first.
      legMutate.mockImplementation((_payload, opts) => opts?.onSettled?.());
      seedSelection(legSel); // $100 notional — no rails on the first fire
      render(<TradeTicket />);
      await userEvent.click(buyBtn());
      expect(legMutate).toHaveBeenCalledTimes(1);
      await userEvent.click(buyBtn());
      expect(legMutate).toHaveBeenCalledTimes(1); // armed, not fired
      expect(screen.getByText(/identical order fired/)).toBeInTheDocument();
      await userEvent.click(screen.getByRole("button", { name: /CONFIRM \+/ }));
      expect(legMutate).toHaveBeenCalledTimes(2);
    });

    it("arms when a limit trigger is far from the indicative price", async () => {
      seedSelection(legSel); // indicative $1.00
      useTradeTicket.setState({ orderType: "limit", limitPrice: 2.0 });
      render(<TradeTicket />);
      await userEvent.click(buyBtn());
      expect(legMutate).not.toHaveBeenCalled();
      expect(screen.getByText(/away from the market/)).toBeInTheDocument();
    });

    it("does not arm a clean small order — fires immediately", async () => {
      seedSelection(legSel);
      render(<TradeTicket />);
      await userEvent.click(sellBtn());
      expect(legMutate).toHaveBeenCalledTimes(1);
      expect(screen.queryByText(/press SELL again/)).not.toBeInTheDocument();
    });
  });
});
