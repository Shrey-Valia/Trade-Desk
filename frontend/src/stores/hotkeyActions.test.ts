import { beforeEach, describe, expect, it } from "vitest";

import { INTENT_TTL_MS, isIntentFresh, useHotkeyActions } from "@/stores/hotkeyActions";
import { useCommandPalette } from "@/stores/commandPalette";

beforeEach(() => {
  useHotkeyActions.setState({ intent: null, nonce: 0, ts: 0, consumers: {} });
  useCommandPalette.setState({ open: false });
});

describe("hotkeyActions bus", () => {
  it("request publishes an intent and bumps the nonce when a consumer is mounted", () => {
    useHotkeyActions.getState().register(["armBuy"]);
    useHotkeyActions.getState().request("armBuy");
    expect(useHotkeyActions.getState().intent).toBe("armBuy");
    expect(useHotkeyActions.getState().nonce).toBe(1);
  });

  it("each request bumps the nonce so repeats are distinguishable", () => {
    useHotkeyActions.getState().register(["closeActive"]);
    useHotkeyActions.getState().request("closeActive");
    useHotkeyActions.getState().request("closeActive");
    expect(useHotkeyActions.getState().nonce).toBe(2);
    expect(useHotkeyActions.getState().intent).toBe("closeActive");
  });

  it("request with NO mounted consumer publishes nothing (reason-toast path)", () => {
    useHotkeyActions.getState().request("flattenAll");
    expect(useHotkeyActions.getState().intent).toBeNull();
    expect(useHotkeyActions.getState().nonce).toBe(0);
  });

  it("unregister removes the consumer so later requests go nowhere", () => {
    const unregister = useHotkeyActions.getState().register(["cancelAllOrders"]);
    unregister();
    useHotkeyActions.getState().request("cancelAllOrders");
    expect(useHotkeyActions.getState().intent).toBeNull();
  });

  it("consume clears the pending intent", () => {
    useHotkeyActions.getState().register(["armSell"]);
    useHotkeyActions.getState().request("armSell");
    useHotkeyActions.getState().consume();
    expect(useHotkeyActions.getState().intent).toBeNull();
  });

  it("published intents are timestamped and age out of freshness", () => {
    useHotkeyActions.getState().register(["closeActive"]);
    useHotkeyActions.getState().request("closeActive");
    const ts = useHotkeyActions.getState().ts;
    expect(isIntentFresh(ts, ts)).toBe(true);
    expect(isIntentFresh(ts, ts + INTENT_TTL_MS)).toBe(true);
    expect(isIntentFresh(ts, ts + INTENT_TTL_MS + 1)).toBe(false);
  });
});

describe("commandPalette store", () => {
  it("toggle flips open state", () => {
    useCommandPalette.getState().toggle();
    expect(useCommandPalette.getState().open).toBe(true);
    useCommandPalette.getState().toggle();
    expect(useCommandPalette.getState().open).toBe(false);
  });

  it("setOpen sets explicitly", () => {
    useCommandPalette.getState().setOpen(true);
    expect(useCommandPalette.getState().open).toBe(true);
  });
});
