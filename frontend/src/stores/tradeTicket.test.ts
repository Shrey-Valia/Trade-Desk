import { beforeEach, describe, expect, it } from "vitest";

import {
  useTradeTicket,
  type TicketSelection,
} from "@/stores/tradeTicket";

// The store is a module-level zustand singleton, so each test resets it to
// the documented initial state before running.
const INITIAL = useTradeTicket.getState();

function reset() {
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

const legSel: TicketSelection = {
  kind: "leg",
  symbol: "SPY",
  strike: 500,
  side: "call",
  price: 1.25,
  expiry: "2026-06-26",
};

describe("tradeTicket store", () => {
  beforeEach(reset);

  it("starts unselected with sensible defaults", () => {
    const s = useTradeTicket.getState();
    expect(s.selection).toBeNull();
    expect(s.contracts).toBe(1);
    expect(s.orderType).toBe("market");
    expect(s.timeInForce).toBe("gtc");
    expect(s.limitPrice).toBeNull();
    expect(s.stopPrice).toBeNull();
    expect(s.trailAmount).toBeNull();
    // Surface the initial snapshot is the documented one (guards the reset).
    expect(INITIAL.orderType).toBe("market");
  });

  describe("setSelection", () => {
    it("seeds limit + stop price to the contract's indicative price", () => {
      useTradeTicket.getState().setSelection(legSel);
      const s = useTradeTicket.getState();
      expect(s.selection).toEqual(legSel);
      // limit/stop default to the indicative price so a limit/stop order
      // starts at a sensible nudge value.
      expect(s.limitPrice).toBe(1.25);
      expect(s.stopPrice).toBe(1.25);
      // Trailing stop stays OFF until opted into.
      expect(s.trailAmount).toBeNull();
    });

    it("clears seeded prices when selection is set to null", () => {
      useTradeTicket.getState().setSelection(legSel);
      useTradeTicket.getState().setSelection(null);
      const s = useTradeTicket.getState();
      expect(s.selection).toBeNull();
      expect(s.limitPrice).toBeNull();
      expect(s.stopPrice).toBeNull();
    });

    it("re-seeds prices to the new selection's price on re-select", () => {
      useTradeTicket.getState().setSelection(legSel);
      useTradeTicket.getState().setSelection({ ...legSel, strike: 505, price: 0.4 });
      const s = useTradeTicket.getState();
      expect(s.limitPrice).toBe(0.4);
      expect(s.stopPrice).toBe(0.4);
    });
  });

  describe("setContracts clamp", () => {
    it("floors and clamps into [1, 100]", () => {
      const { setContracts } = useTradeTicket.getState();
      setContracts(3);
      expect(useTradeTicket.getState().contracts).toBe(3);

      setContracts(0);
      expect(useTradeTicket.getState().contracts).toBe(1);

      setContracts(-7);
      expect(useTradeTicket.getState().contracts).toBe(1);

      setContracts(150);
      expect(useTradeTicket.getState().contracts).toBe(100);

      setContracts(4.9);
      expect(useTradeTicket.getState().contracts).toBe(4);
    });
  });

  describe("order-type transitions", () => {
    it("moves between the four order types", () => {
      const { setOrderType } = useTradeTicket.getState();
      setOrderType("limit");
      expect(useTradeTicket.getState().orderType).toBe("limit");
      setOrderType("stop_limit");
      expect(useTradeTicket.getState().orderType).toBe("stop_limit");
      setOrderType("stop");
      expect(useTradeTicket.getState().orderType).toBe("stop");
      setOrderType("market");
      expect(useTradeTicket.getState().orderType).toBe("market");
    });

    it("lets limit/stop/trail/tif be edited independently", () => {
      const g = useTradeTicket.getState();
      g.setLimitPrice(2.5);
      g.setStopPrice(2.0);
      g.setTrailAmount(0.3);
      g.setTimeInForce("day");
      const s = useTradeTicket.getState();
      expect(s.limitPrice).toBe(2.5);
      expect(s.stopPrice).toBe(2.0);
      expect(s.trailAmount).toBe(0.3);
      expect(s.timeInForce).toBe("day");
    });
  });

  describe("clear", () => {
    it("resets order state but leaves contracts untouched", () => {
      const g = useTradeTicket.getState();
      g.setSelection(legSel);
      g.setOrderType("stop_limit");
      g.setTimeInForce("day");
      g.setTrailAmount(0.5);
      g.setContracts(5);

      useTradeTicket.getState().clear();
      const s = useTradeTicket.getState();
      expect(s.selection).toBeNull();
      expect(s.orderType).toBe("market");
      expect(s.limitPrice).toBeNull();
      expect(s.stopPrice).toBeNull();
      expect(s.trailAmount).toBeNull();
      expect(s.timeInForce).toBe("gtc");
      // clear() intentionally does NOT reset the quantity — the user's
      // chosen size carries to the next ticket.
      expect(s.contracts).toBe(5);
    });
  });
});
