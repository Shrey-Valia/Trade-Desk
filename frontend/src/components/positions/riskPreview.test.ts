import { describe, expect, it } from "vitest";

import { riskPreviewFor } from "@/components/positions/TradeTicket";
import type { TicketSelection } from "@/stores/tradeTicket";

const callSel: TicketSelection = {
  kind: "leg",
  symbol: "SPY",
  side: "call",
  strike: 500,
  price: 2,
  expiry: "2026-06-29",
};

const putSel: TicketSelection = { ...callSel, side: "put" };

const straddleSel: TicketSelection = {
  kind: "straddle",
  symbol: "SPY",
  strike: 500,
  price: 4,
  expiry: "2026-06-29",
};

describe("riskPreviewFor (WS6 risk preview math)", () => {
  it("max loss is the full debit (price × 100 × contracts)", () => {
    expect(riskPreviewFor(callSel, 1).maxLoss).toBe(200);
    expect(riskPreviewFor(callSel, 3).maxLoss).toBe(600);
  });

  it("call breakeven is strike + premium; targets step by one R past BE", () => {
    const r = riskPreviewFor(callSel, 1);
    expect(r.breakevens).toBe("$502.00"); // 500 + 2
    expect(r.target1R).toBe(504); // BE 502 + price 2
    expect(r.target2R).toBe(506); // BE 502 + 2×2
  });

  it("put breakeven is strike − premium; targets step down past BE", () => {
    const r = riskPreviewFor(putSel, 1);
    expect(r.breakevens).toBe("$498.00"); // 500 - 2
    expect(r.target1R).toBe(496); // BE 498 - 2
    expect(r.target2R).toBe(494);
  });

  it("straddle shows a two-sided breakeven and no single directional target", () => {
    const r = riskPreviewFor(straddleSel, 1);
    expect(r.maxLoss).toBe(400);
    expect(r.breakevens).toBe("$496.00 ↔ $504.00"); // 500 ± 4
    expect(r.target1R).toBeNull();
    expect(r.target2R).toBeNull();
  });

  it("scales max loss by contract count", () => {
    expect(riskPreviewFor(straddleSel, 5).maxLoss).toBe(2000);
  });
});
