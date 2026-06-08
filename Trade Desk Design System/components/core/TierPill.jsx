import React from "react";

/**
 * TierPill — the combine-tier indicator / switcher from the header.
 * bg-tier-2 fill, tier-3 border (or bearish when breached), 4px
 * radius, 40px tall. Uppercase label + ▾ caret. Static display
 * component — wire `onClick` for the dropdown yourself.
 */
export function TierPill({ tier = "50K", breached = false, onClick, style, ...rest }) {
  return (
    <button
      type="button"
      onClick={onClick}
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 8,
        height: 40,
        padding: "0 12px",
        fontFamily: "var(--td-font-mono)",
        fontSize: 12,
        fontWeight: 500,
        textTransform: "uppercase",
        letterSpacing: "0.08em",
        fontVariantNumeric: "tabular-nums",
        background: "var(--td-bg-2)",
        border: `1px solid ${breached ? "var(--td-bearish)" : "var(--td-bg-3)"}`,
        color: breached ? "var(--td-bearish)" : "var(--td-fg-primary)",
        borderRadius: "var(--td-radius)",
        cursor: "pointer",
        transition: "var(--td-transition-colors)",
        ...style,
      }}
      {...rest}
    >
      <span>{tier} Combine</span>
      <span style={{ fontSize: 10, color: "var(--td-fg-tertiary-2)" }}>▾</span>
    </button>
  );
}
