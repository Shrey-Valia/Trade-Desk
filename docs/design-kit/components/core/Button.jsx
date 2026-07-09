import React from "react";

/**
 * Trade Desk button. Monospace, 4px radius, 100ms color transitions,
 * no shadow. Variants map to the terminal's real button chrome:
 *  - primary  : amber border + amber text on raised fill (active CTA)
 *  - secondary: hairline border, secondary text, lifts on hover
 *  - ghost    : no border, tertiary text, lifts to secondary on hover
 *  - danger   : bearish border + text (destructive / breach)
 */
export function Button({
  variant = "secondary",
  size = "md",
  active = false,
  disabled = false,
  type = "button",
  style,
  children,
  ...rest
}) {
  const pad = size === "sm" ? "0 8px" : size === "lg" ? "0 16px" : "0 12px";
  const height = size === "sm" ? 24 : size === "lg" ? 40 : 32;
  const fontSize = size === "sm" ? 11 : size === "lg" ? 14 : 12;

  const base = {
    display: "inline-flex",
    alignItems: "center",
    justifyContent: "center",
    gap: 6,
    fontFamily: "var(--td-font-mono)",
    fontSize,
    fontWeight: 500,
    lineHeight: 1,
    height,
    padding: pad,
    borderRadius: "var(--td-radius)",
    border: "1px solid transparent",
    background: "transparent",
    cursor: disabled ? "not-allowed" : "pointer",
    transition: "var(--td-transition-colors)",
    fontVariantNumeric: "tabular-nums",
    whiteSpace: "nowrap",
    userSelect: "none",
  };

  const variants = {
    primary: {
      background: "var(--td-bg-3)",
      borderColor: "var(--td-amber)",
      color: "var(--td-amber)",
    },
    secondary: {
      background: "var(--td-bg-2)",
      borderColor: "var(--td-bg-3)",
      color: active ? "var(--td-amber)" : "var(--td-fg-secondary)",
    },
    ghost: {
      background: "transparent",
      borderColor: "transparent",
      color: active ? "var(--td-amber)" : "var(--td-fg-tertiary-2)",
    },
    danger: {
      background: "var(--td-bg-2)",
      borderColor: "var(--td-bearish)",
      color: "var(--td-bearish)",
    },
  };

  const disabledStyle = disabled
    ? { background: "var(--td-bg-1)", borderColor: "var(--td-bg-2)", color: "var(--td-fg-disabled)" }
    : null;

  return (
    <button
      type={type}
      disabled={disabled}
      data-variant={variant}
      data-active={active || undefined}
      style={{ ...base, ...variants[variant], ...disabledStyle, ...style }}
      {...rest}
    >
      {children}
    </button>
  );
}
