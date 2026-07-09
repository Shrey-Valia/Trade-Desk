import React from "react";

/**
 * ActionButton — the large BUY / SELL ticket button. Solid action-
 * affordance fill (NOT bullish/bearish — those are P&L colors),
 * white text, 4px radius, two-line label. ~56px tall in the ticket.
 */
export function ActionButton({ intent = "buy", label, sub, disabled = false, style, ...rest }) {
  const fills = {
    buy: {
      bg: "var(--td-action-buy)",
      hover: "var(--td-action-buy-hover)",
      active: "var(--td-action-buy-active)",
    },
    sell: {
      bg: "var(--td-action-sell)",
      hover: "var(--td-action-sell-hover)",
      active: "var(--td-action-sell-active)",
    },
  };
  const f = fills[intent] ?? fills.buy;
  const [state, setState] = React.useState("rest");
  const bg = disabled
    ? "var(--td-bg-1)"
    : state === "active"
      ? f.active
      : state === "hover"
        ? f.hover
        : f.bg;
  return (
    <button
      type="button"
      disabled={disabled}
      onMouseEnter={() => setState("hover")}
      onMouseLeave={() => setState("rest")}
      onMouseDown={() => setState("active")}
      onMouseUp={() => setState("hover")}
      style={{
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        height: 56,
        padding: "0 8px",
        lineHeight: 1.15,
        border: "none",
        borderRadius: "var(--td-radius)",
        background: bg,
        color: disabled ? "var(--td-fg-disabled)" : "#fff",
        cursor: disabled ? "not-allowed" : "pointer",
        transition: "var(--td-transition-colors)",
        fontFamily: "var(--td-font-mono)",
        ...style,
      }}
      {...rest}
    >
      <span style={{ fontSize: 14, fontWeight: 500, letterSpacing: "0.04em" }}>{label}</span>
      {sub && (
        <span
          style={{
            fontSize: 10,
            marginTop: 2,
            opacity: disabled ? 1 : 0.78,
            fontVariantNumeric: "tabular-nums",
          }}
        >
          {sub}
        </span>
      )}
    </button>
  );
}
