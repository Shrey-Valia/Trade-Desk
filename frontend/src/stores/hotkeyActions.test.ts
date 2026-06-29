import { beforeEach, describe, expect, it } from "vitest";

import { useHotkeyActions } from "@/stores/hotkeyActions";
import { useCommandPalette } from "@/stores/commandPalette";

beforeEach(() => {
  useHotkeyActions.setState({ intent: null, nonce: 0 });
  useCommandPalette.setState({ open: false });
});

describe("hotkeyActions bus", () => {
  it("request publishes an intent and bumps the nonce", () => {
    useHotkeyActions.getState().request("armBuy");
    expect(useHotkeyActions.getState().intent).toBe("armBuy");
    expect(useHotkeyActions.getState().nonce).toBe(1);
  });

  it("each request bumps the nonce so repeats are distinguishable", () => {
    useHotkeyActions.getState().request("closeActive");
    useHotkeyActions.getState().request("closeActive");
    expect(useHotkeyActions.getState().nonce).toBe(2);
    expect(useHotkeyActions.getState().intent).toBe("closeActive");
  });

  it("consume clears the pending intent", () => {
    useHotkeyActions.getState().request("armSell");
    useHotkeyActions.getState().consume();
    expect(useHotkeyActions.getState().intent).toBeNull();
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
