import { beforeEach, describe, expect, it } from "vitest";

import { useOnboarding } from "@/stores/onboarding";
import { GLOSSARY } from "@/lib/glossary";

function reset() {
  useOnboarding.setState(
    { tourSeen: false, tourOpen: false, helpOpen: false },
    false,
  );
}

beforeEach(reset);

describe("onboarding store", () => {
  it("starts unseen, with both overlays closed", () => {
    const s = useOnboarding.getState();
    expect(s.tourSeen).toBe(false);
    expect(s.tourOpen).toBe(false);
    expect(s.helpOpen).toBe(false);
  });

  it("openTour shows the tour without marking it seen", () => {
    useOnboarding.getState().openTour();
    expect(useOnboarding.getState().tourOpen).toBe(true);
    expect(useOnboarding.getState().tourSeen).toBe(false);
  });

  it("markTourSeen persists the seen flag (gates the auto-launch)", () => {
    useOnboarding.getState().markTourSeen();
    expect(useOnboarding.getState().tourSeen).toBe(true);
  });

  it("toggleHelp flips the overlay both ways", () => {
    useOnboarding.getState().toggleHelp();
    expect(useOnboarding.getState().helpOpen).toBe(true);
    useOnboarding.getState().toggleHelp();
    expect(useOnboarding.getState().helpOpen).toBe(false);
  });

  it("setHelpOpen sets the overlay explicitly", () => {
    useOnboarding.getState().setHelpOpen(true);
    expect(useOnboarding.getState().helpOpen).toBe(true);
  });
});

describe("glossary content", () => {
  it("covers the key terms called out in the spec", () => {
    const terms = GLOSSARY.map((t) => t.term);
    expect(terms).toContain("MLL");
    expect(terms).toContain("DLL");
    expect(terms).toContain("Combine");
    expect(terms).toContain("0DTE");
    expect(terms).toContain("Greeks");
  });

  it("every entry has a non-empty definition", () => {
    for (const t of GLOSSARY) {
      expect(t.term.length).toBeGreaterThan(0);
      expect(t.definition.length).toBeGreaterThan(10);
    }
  });
});
