import React from "react";

/**
 * MetricPill — the terminal's core "card". A labeled value box:
 * bg-tier-2 fill, 1px tier-3 border, 4px radius, ~110×44. Label
 * (10px uppercase) over value (15px medium). This is the entire
 * card vocabulary of the product — BAL / MLL / RP&L / UP&L / MKT.
 *
 * `tone` colors the value: signed maps +/− to bullish/bearish,
 * or pass an explicit tone. Numbers are tabular.
 */
export function MetricPill({
  label,
  value,
  tone = "default",
  signed,
  sub,
  width = 110,
  style,
  children,
  ...rest
}) {
  let color = "var(--td-fg-primary)";
  if (tone === "bullish") color = "var(--td-bullish)";
  else if (tone === "bearish") color = "var(--td-bearish)";
  else if (tone === "warning") color = "var(--td-warning)";
  else if (tone === "amber") color = "var(--td-amber)";
  else if (signed !== undefined) {
    color = signed > 0 ? "var(--td-bullish)" : signed < 0 ? "var(--td-bearish)" : "var(--td-fg-primary)";
  }

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        justifyContent: "center",
        lineHeight: 1.15,
        minWidth: width,
        height: 44,
        padding: "5px 10px",
        background: "var(--td-bg-2)",
        border: "1px solid var(--td-bg-3)",
        borderRadius: "var(--td-radius)",
        fontFamily: "var(--td-font-mono)",
        ...style,
      }}
      {...rest}
    >
      <span
        style={{
          fontSize: 10,
          textTransform: "uppercase",
          letterSpacing: "0.08em",
          color: "var(--td-fg-tertiary-2)",
        }}
      >
        {label}
      </span>
      <span
        style={{
          fontSize: 15,
          fontWeight: 500,
          marginTop: 2,
          color,
          fontVariantNumeric: "tabular-nums",
          display: "flex",
          alignItems: "baseline",
          gap: 4,
        }}
      >
        {value}
        {children}
        {sub && (
          <span style={{ fontSize: 10, color: "var(--td-fg-tertiary-2)" }}>{sub}</span>
        )}
      </span>
    </div>
  );
}
