import React from "react";

/**
 * Badge — small outlined status chip. 2px radius, uppercase, 0.08em
 * tracking. Outlined (not solid-filled) per the terminal's market-
 * structure pill convention. Tones: breach/error (bearish),
 * advisory (warning), active (amber), neutral (cyan), muted.
 */
export function Badge({ tone = "muted", children, style, ...rest }) {
  const tones = {
    bearish: { color: "var(--td-bearish)", border: "var(--td-bearish)" },
    warning: { color: "var(--td-warning)", border: "var(--td-warning)" },
    amber: { color: "var(--td-amber)", border: "var(--td-amber)" },
    bullish: { color: "var(--td-bullish)", border: "var(--td-bullish)" },
    cyan: { color: "var(--td-cyan)", border: "var(--td-cyan)" },
    muted: { color: "var(--td-fg-tertiary-2)", border: "var(--td-border-strong)" },
  };
  const t = tones[tone] ?? tones.muted;
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        height: 16,
        padding: "0 5px",
        fontFamily: "var(--td-font-mono)",
        fontSize: 9,
        fontWeight: 500,
        textTransform: "uppercase",
        letterSpacing: "0.08em",
        color: t.color,
        border: `1px solid ${t.border}`,
        borderRadius: "var(--td-radius-pill)",
        background: "transparent",
        lineHeight: 1,
        whiteSpace: "nowrap",
        ...style,
      }}
      {...rest}
    >
      {children}
    </span>
  );
}
