import React from "react";

/**
 * PresetChips — round contract-quantity presets (1 / 3 / 5 / 10 / 15).
 * Circular 32px chips. Selected = amber border + amber text on tier-3;
 * idle = tier-2 fill, secondary text, lifts on hover.
 */
export function PresetChips({ presets = [1, 3, 5, 10, 15], value, onSelect, style, ...rest }) {
  return (
    <div style={{ display: "flex", gap: 4, ...style }} {...rest}>
      {presets.map((n) => {
        const active = value === n;
        return (
          <button
            key={n}
            type="button"
            aria-pressed={active}
            onClick={() => onSelect(n)}
            style={{
              width: 32,
              height: 32,
              borderRadius: "50%",
              fontSize: 12,
              fontWeight: 500,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              fontFamily: "var(--td-font-mono)",
              fontVariantNumeric: "tabular-nums",
              cursor: "pointer",
              transition: "var(--td-transition-colors)",
              background: active ? "var(--td-bg-3)" : "var(--td-bg-2)",
              border: `1px solid ${active ? "var(--td-amber)" : "var(--td-bg-3)"}`,
              color: active ? "var(--td-amber)" : "var(--td-fg-secondary)",
            }}
          >
            {n}
          </button>
        );
      })}
    </div>
  );
}
