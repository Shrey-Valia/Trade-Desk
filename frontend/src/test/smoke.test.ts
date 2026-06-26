import { describe, expect, it } from "vitest";

// Sanity check that the runner + jsdom env are wired up. If this fails the
// rest of the suite is moot, so it lives first.
describe("vitest setup", () => {
  it("runs in a jsdom environment", () => {
    expect(typeof window).toBe("object");
    expect(typeof document.createElement).toBe("function");
  });
});
