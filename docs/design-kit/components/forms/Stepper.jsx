import React from "react";

/**
 * Stepper — −/value/+ quantity control from the trade ticket.
 * Square 32px buttons (bg-2, tier-3 border), value box in the middle
 * (bg-2, tier-3 border, 60px). Controlled via value/onChange.
 */
export function Stepper({ value, onChange, min = 1, max = 999, style, ...rest }) {
  const btn = (content, onClick, disabled) => (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      style={{
        width: 32,
        height: 32,
        fontSize: 16,
        lineHeight: 1,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        borderRadius: "var(--td-radius)",
        fontFamily: "var(--td-font-mono)",
        background: disabled ? "var(--td-bg-1)" : "var(--td-bg-2)",
        border: `1px solid ${disabled ? "var(--td-bg-2)" : "var(--td-bg-3)"}`,
        color: disabled ? "var(--td-fg-disabled)" : "var(--td-fg-primary)",
        cursor: disabled ? "not-allowed" : "pointer",
        transition: "var(--td-transition-colors)",
      }}
    >
      {content}
    </button>
  );
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 4, ...style }} {...rest}>
      {btn("−", () => onChange(Math.max(min, value - 1)), value <= min)}
      <div
        aria-live="polite"
        style={{
          width: 60,
          height: 32,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          fontSize: 16,
          fontWeight: 500,
          fontVariantNumeric: "tabular-nums",
          background: "var(--td-bg-2)",
          border: "1px solid var(--td-bg-3)",
          borderRadius: "var(--td-radius)",
          color: "var(--td-fg-primary)",
          fontFamily: "var(--td-font-mono)",
        }}
      >
        {value}
      </div>
      {btn("+", () => onChange(Math.min(max, value + 1)), value >= max)}
    </div>
  );
}
