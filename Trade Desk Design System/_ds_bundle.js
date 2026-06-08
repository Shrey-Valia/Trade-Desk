/* @ds-bundle: {"format":3,"namespace":"TradeDeskDesignSystem_29ab83","components":[{"name":"Badge","sourcePath":"components/core/Badge.jsx"},{"name":"Button","sourcePath":"components/core/Button.jsx"},{"name":"MetricPill","sourcePath":"components/core/MetricPill.jsx"},{"name":"TierPill","sourcePath":"components/core/TierPill.jsx"},{"name":"ChainRow","sourcePath":"components/data/ChainRow.jsx"},{"name":"Icon","sourcePath":"components/data/Icon.jsx"},{"name":"ActionButton","sourcePath":"components/forms/ActionButton.jsx"},{"name":"PresetChips","sourcePath":"components/forms/PresetChips.jsx"},{"name":"Stepper","sourcePath":"components/forms/Stepper.jsx"}],"sourceHashes":{"components/core/Badge.jsx":"ef583d3dc0a7","components/core/Button.jsx":"cdb0f368ef8f","components/core/MetricPill.jsx":"74514b10a9a5","components/core/TierPill.jsx":"d4d8cdfe0747","components/data/ChainRow.jsx":"dae6566c4cbe","components/data/Icon.jsx":"478bc60409d0","components/forms/ActionButton.jsx":"65d2b50cfc08","components/forms/PresetChips.jsx":"f4498c7d25be","components/forms/Stepper.jsx":"9f1f1d048eac","ui_kits/combine/Combine.jsx":"3c3db7c53da5","ui_kits/data/trades.js":"ebe58e7956ef","ui_kits/funded/Funded.jsx":"872884408800","ui_kits/terminal/BottomRow.jsx":"b97976140a34","ui_kits/terminal/Chart.jsx":"3be5dd4e1768","ui_kits/terminal/Panels.jsx":"7384900d9acd","ui_kits/terminal/data.js":"733651eea2d7"},"inlinedExternals":[],"unexposedExports":[]} */

(() => {

const __ds_ns = (window.TradeDeskDesignSystem_29ab83 = window.TradeDeskDesignSystem_29ab83 || {});

const __ds_scope = {};

(__ds_ns.__errors = __ds_ns.__errors || []);

// components/core/Badge.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
/**
 * Badge — small outlined status chip. 2px radius, uppercase, 0.08em
 * tracking. Outlined (not solid-filled) per the terminal's market-
 * structure pill convention. Tones: breach/error (bearish),
 * advisory (warning), active (amber), neutral (cyan), muted.
 */
function Badge({
  tone = "muted",
  children,
  style,
  ...rest
}) {
  const tones = {
    bearish: {
      color: "var(--td-bearish)",
      border: "var(--td-bearish)"
    },
    warning: {
      color: "var(--td-warning)",
      border: "var(--td-warning)"
    },
    amber: {
      color: "var(--td-amber)",
      border: "var(--td-amber)"
    },
    bullish: {
      color: "var(--td-bullish)",
      border: "var(--td-bullish)"
    },
    cyan: {
      color: "var(--td-cyan)",
      border: "var(--td-cyan)"
    },
    muted: {
      color: "var(--td-fg-tertiary-2)",
      border: "var(--td-border-strong)"
    }
  };
  const t = tones[tone] ?? tones.muted;
  return /*#__PURE__*/React.createElement("span", _extends({
    style: {
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
      ...style
    }
  }, rest), children);
}
Object.assign(__ds_scope, { Badge });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/core/Badge.jsx", error: String((e && e.message) || e) }); }

// components/core/Button.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
/**
 * Trade Desk button. Monospace, 4px radius, 100ms color transitions,
 * no shadow. Variants map to the terminal's real button chrome:
 *  - primary  : amber border + amber text on raised fill (active CTA)
 *  - secondary: hairline border, secondary text, lifts on hover
 *  - ghost    : no border, tertiary text, lifts to secondary on hover
 *  - danger   : bearish border + text (destructive / breach)
 */
function Button({
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
    userSelect: "none"
  };
  const variants = {
    primary: {
      background: "var(--td-bg-3)",
      borderColor: "var(--td-amber)",
      color: "var(--td-amber)"
    },
    secondary: {
      background: "var(--td-bg-2)",
      borderColor: "var(--td-bg-3)",
      color: active ? "var(--td-amber)" : "var(--td-fg-secondary)"
    },
    ghost: {
      background: "transparent",
      borderColor: "transparent",
      color: active ? "var(--td-amber)" : "var(--td-fg-tertiary-2)"
    },
    danger: {
      background: "var(--td-bg-2)",
      borderColor: "var(--td-bearish)",
      color: "var(--td-bearish)"
    }
  };
  const disabledStyle = disabled ? {
    background: "var(--td-bg-1)",
    borderColor: "var(--td-bg-2)",
    color: "var(--td-fg-disabled)"
  } : null;
  return /*#__PURE__*/React.createElement("button", _extends({
    type: type,
    disabled: disabled,
    "data-variant": variant,
    "data-active": active || undefined,
    style: {
      ...base,
      ...variants[variant],
      ...disabledStyle,
      ...style
    }
  }, rest), children);
}
Object.assign(__ds_scope, { Button });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/core/Button.jsx", error: String((e && e.message) || e) }); }

// components/core/MetricPill.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
/**
 * MetricPill — the terminal's core "card". A labeled value box:
 * bg-tier-2 fill, 1px tier-3 border, 4px radius, ~110×44. Label
 * (10px uppercase) over value (15px medium). This is the entire
 * card vocabulary of the product — BAL / MLL / RP&L / UP&L / MKT.
 *
 * `tone` colors the value: signed maps +/− to bullish/bearish,
 * or pass an explicit tone. Numbers are tabular.
 */
function MetricPill({
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
  if (tone === "bullish") color = "var(--td-bullish)";else if (tone === "bearish") color = "var(--td-bearish)";else if (tone === "warning") color = "var(--td-warning)";else if (tone === "amber") color = "var(--td-amber)";else if (signed !== undefined) {
    color = signed > 0 ? "var(--td-bullish)" : signed < 0 ? "var(--td-bearish)" : "var(--td-fg-primary)";
  }
  return /*#__PURE__*/React.createElement("div", _extends({
    style: {
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
      ...style
    }
  }, rest), /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 10,
      textTransform: "uppercase",
      letterSpacing: "0.08em",
      color: "var(--td-fg-tertiary-2)"
    }
  }, label), /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 15,
      fontWeight: 500,
      marginTop: 2,
      color,
      fontVariantNumeric: "tabular-nums",
      display: "flex",
      alignItems: "baseline",
      gap: 4
    }
  }, value, children, sub && /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 10,
      color: "var(--td-fg-tertiary-2)"
    }
  }, sub)));
}
Object.assign(__ds_scope, { MetricPill });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/core/MetricPill.jsx", error: String((e && e.message) || e) }); }

// components/core/TierPill.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
/**
 * TierPill — the combine-tier indicator / switcher from the header.
 * bg-tier-2 fill, tier-3 border (or bearish when breached), 4px
 * radius, 40px tall. Uppercase label + ▾ caret. Static display
 * component — wire `onClick` for the dropdown yourself.
 */
function TierPill({
  tier = "50K",
  breached = false,
  onClick,
  style,
  ...rest
}) {
  return /*#__PURE__*/React.createElement("button", _extends({
    type: "button",
    onClick: onClick,
    style: {
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
      ...style
    }
  }, rest), /*#__PURE__*/React.createElement("span", null, tier, " Combine"), /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 10,
      color: "var(--td-fg-tertiary-2)"
    }
  }, "\u25BE"));
}
Object.assign(__ds_scope, { TierPill });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/core/TierPill.jsx", error: String((e && e.message) || e) }); }

// components/data/ChainRow.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
/**
 * ChainRow — one strike row of the option chain: CALL │ STRIKE │ PUT.
 * Three centered columns (84 / 64 / 84) so calls/puts hug the strike.
 * 18px tall, 11px tabular. ATM row = amber left-border + lifted fill +
 * amber strike. Clicking a price fires onCall/onPut; the strike fires
 * onStrike (straddle when ATM). Prices tagged `·m` are model-priced.
 */
function ChainRow({
  strike,
  call,
  put,
  isAtm = false,
  callSource = "quote",
  putSource = "quote",
  onCall,
  onPut,
  onStrike,
  disabled = false,
  style,
  ...rest
}) {
  const grid = "84px 64px 84px";
  const cell = (price, source, align, onClick) => {
    const dim = source === "bs";
    const dead = disabled || price <= 0;
    return /*#__PURE__*/React.createElement("button", {
      type: "button",
      onClick: onClick,
      disabled: dead,
      style: {
        height: "100%",
        padding: "0 8px",
        textAlign: align,
        fontSize: 11,
        fontVariantNumeric: "tabular-nums",
        fontFamily: "var(--td-font-mono)",
        background: "transparent",
        border: "none",
        color: dim ? "var(--td-fg-secondary)" : "var(--td-fg-primary)",
        opacity: dead ? 0.3 : 1,
        cursor: dead ? "not-allowed" : "pointer",
        transition: "var(--td-transition-colors)"
      }
    }, price.toFixed(2), source === "bs" && /*#__PURE__*/React.createElement("span", {
      style: {
        color: "var(--td-fg-tertiary)",
        marginLeft: 2,
        fontSize: 8
      }
    }, "\xB7m"));
  };
  return /*#__PURE__*/React.createElement("div", _extends({
    "data-strike": strike,
    "data-atm": isAtm || undefined,
    style: {
      display: "grid",
      gridTemplateColumns: grid,
      alignItems: "center",
      height: 18,
      fontSize: 11,
      fontVariantNumeric: "tabular-nums",
      borderBottom: "1px solid var(--td-border)",
      borderLeft: `2px solid ${isAtm ? "var(--td-amber)" : "transparent"}`,
      background: isAtm ? "var(--td-bg-1)" : "transparent",
      ...style
    }
  }, rest), cell(call, callSource, "right", onCall), /*#__PURE__*/React.createElement("button", {
    type: "button",
    onClick: onStrike,
    disabled: disabled,
    style: {
      height: "100%",
      textAlign: "center",
      fontFamily: "var(--td-font-mono)",
      fontSize: 11,
      fontWeight: isAtm ? 500 : 400,
      borderLeft: "1px solid var(--td-border)",
      borderRight: "1px solid var(--td-border)",
      borderTop: "none",
      borderBottom: "none",
      background: "transparent",
      color: isAtm ? "var(--td-amber)" : "var(--td-fg-primary)",
      cursor: disabled ? "not-allowed" : "pointer",
      transition: "var(--td-transition-colors)"
    }
  }, strike), cell(put, putSource, "left", onPut));
}
Object.assign(__ds_scope, { ChainRow });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/data/ChainRow.jsx", error: String((e && e.message) || e) }); }

// components/data/Icon.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
/**
 * Icon — the terminal's custom monoline set. 20×20, stroke 1.5,
 * currentColor (inherits the parent's color, e.g. amber when active).
 * Names mirror the left-rail glyphs.
 */
const PATHS = {
  chart: /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement("line", {
    x1: "6",
    y1: "3",
    x2: "6",
    y2: "17"
  }), /*#__PURE__*/React.createElement("rect", {
    x: "4",
    y: "6",
    width: "4",
    height: "7",
    fill: "currentColor"
  }), /*#__PURE__*/React.createElement("line", {
    x1: "14",
    y1: "3",
    x2: "14",
    y2: "17"
  }), /*#__PURE__*/React.createElement("rect", {
    x: "12",
    y: "8",
    width: "4",
    height: "5"
  })),
  journal: /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement("path", {
    d: "M4 4h9a2 2 0 0 1 2 2v11H6a2 2 0 0 1-2-2V4z"
  }), /*#__PURE__*/React.createElement("line", {
    x1: "7",
    y1: "8",
    x2: "12",
    y2: "8"
  }), /*#__PURE__*/React.createElement("line", {
    x1: "7",
    y1: "11",
    x2: "12",
    y2: "11"
  }), /*#__PURE__*/React.createElement("line", {
    x1: "7",
    y1: "14",
    x2: "10",
    y2: "14"
  })),
  analytics: /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement("line", {
    x1: "3",
    y1: "17",
    x2: "17",
    y2: "17"
  }), /*#__PURE__*/React.createElement("rect", {
    x: "4",
    y: "11",
    width: "3",
    height: "6"
  }), /*#__PURE__*/React.createElement("rect", {
    x: "9",
    y: "7",
    width: "3",
    height: "10"
  }), /*#__PURE__*/React.createElement("rect", {
    x: "14",
    y: "4",
    width: "3",
    height: "13"
  })),
  watchlist: /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement("circle", {
    cx: "4.5",
    cy: "5.5",
    r: "1",
    fill: "currentColor",
    stroke: "none"
  }), /*#__PURE__*/React.createElement("line", {
    x1: "8",
    y1: "5.5",
    x2: "17",
    y2: "5.5"
  }), /*#__PURE__*/React.createElement("circle", {
    cx: "4.5",
    cy: "10",
    r: "1",
    fill: "currentColor",
    stroke: "none"
  }), /*#__PURE__*/React.createElement("line", {
    x1: "8",
    y1: "10",
    x2: "17",
    y2: "10"
  }), /*#__PURE__*/React.createElement("circle", {
    cx: "4.5",
    cy: "14.5",
    r: "1",
    fill: "currentColor",
    stroke: "none"
  }), /*#__PURE__*/React.createElement("line", {
    x1: "8",
    y1: "14.5",
    x2: "17",
    y2: "14.5"
  })),
  zerodte: /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement("line", {
    x1: "4",
    y1: "3",
    x2: "16",
    y2: "3"
  }), /*#__PURE__*/React.createElement("line", {
    x1: "4",
    y1: "17",
    x2: "16",
    y2: "17"
  }), /*#__PURE__*/React.createElement("path", {
    d: "M5 3v3l5 4-5 4v3M15 3v3l-5 4 5 4v3"
  })),
  settings: /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement("circle", {
    cx: "10",
    cy: "10",
    r: "2.5"
  }), /*#__PURE__*/React.createElement("path", {
    d: "M10 2.5v2M10 15.5v2M2.5 10h2M15.5 10h2M4.7 4.7l1.4 1.4M13.9 13.9l1.4 1.4M4.7 15.3l1.4-1.4M13.9 6.1l1.4-1.4"
  }))
};
function Icon({
  name,
  size = 20,
  style,
  ...rest
}) {
  return /*#__PURE__*/React.createElement("svg", _extends({
    width: size,
    height: size,
    viewBox: "0 0 20 20",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 1.5,
    strokeLinecap: "round",
    strokeLinejoin: "round",
    style: style
  }, rest), PATHS[name] ?? null);
}
Object.assign(__ds_scope, { Icon });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/data/Icon.jsx", error: String((e && e.message) || e) }); }

// components/forms/ActionButton.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
/**
 * ActionButton — the large BUY / SELL ticket button. Solid action-
 * affordance fill (NOT bullish/bearish — those are P&L colors),
 * white text, 4px radius, two-line label. ~56px tall in the ticket.
 */
function ActionButton({
  intent = "buy",
  label,
  sub,
  disabled = false,
  style,
  ...rest
}) {
  const fills = {
    buy: {
      bg: "var(--td-action-buy)",
      hover: "var(--td-action-buy-hover)",
      active: "var(--td-action-buy-active)"
    },
    sell: {
      bg: "var(--td-action-sell)",
      hover: "var(--td-action-sell-hover)",
      active: "var(--td-action-sell-active)"
    }
  };
  const f = fills[intent] ?? fills.buy;
  const [state, setState] = React.useState("rest");
  const bg = disabled ? "var(--td-bg-1)" : state === "active" ? f.active : state === "hover" ? f.hover : f.bg;
  return /*#__PURE__*/React.createElement("button", _extends({
    type: "button",
    disabled: disabled,
    onMouseEnter: () => setState("hover"),
    onMouseLeave: () => setState("rest"),
    onMouseDown: () => setState("active"),
    onMouseUp: () => setState("hover"),
    style: {
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
      ...style
    }
  }, rest), /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 14,
      fontWeight: 500,
      letterSpacing: "0.04em"
    }
  }, label), sub && /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 10,
      marginTop: 2,
      opacity: disabled ? 1 : 0.78,
      fontVariantNumeric: "tabular-nums"
    }
  }, sub));
}
Object.assign(__ds_scope, { ActionButton });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/forms/ActionButton.jsx", error: String((e && e.message) || e) }); }

// components/forms/PresetChips.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
/**
 * PresetChips — round contract-quantity presets (1 / 3 / 5 / 10 / 15).
 * Circular 32px chips. Selected = amber border + amber text on tier-3;
 * idle = tier-2 fill, secondary text, lifts on hover.
 */
function PresetChips({
  presets = [1, 3, 5, 10, 15],
  value,
  onSelect,
  style,
  ...rest
}) {
  return /*#__PURE__*/React.createElement("div", _extends({
    style: {
      display: "flex",
      gap: 4,
      ...style
    }
  }, rest), presets.map(n => {
    const active = value === n;
    return /*#__PURE__*/React.createElement("button", {
      key: n,
      type: "button",
      "aria-pressed": active,
      onClick: () => onSelect(n),
      style: {
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
        color: active ? "var(--td-amber)" : "var(--td-fg-secondary)"
      }
    }, n);
  }));
}
Object.assign(__ds_scope, { PresetChips });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/forms/PresetChips.jsx", error: String((e && e.message) || e) }); }

// components/forms/Stepper.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
/**
 * Stepper — −/value/+ quantity control from the trade ticket.
 * Square 32px buttons (bg-2, tier-3 border), value box in the middle
 * (bg-2, tier-3 border, 60px). Controlled via value/onChange.
 */
function Stepper({
  value,
  onChange,
  min = 1,
  max = 999,
  style,
  ...rest
}) {
  const btn = (content, onClick, disabled) => /*#__PURE__*/React.createElement("button", {
    type: "button",
    onClick: onClick,
    disabled: disabled,
    style: {
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
      transition: "var(--td-transition-colors)"
    }
  }, content);
  return /*#__PURE__*/React.createElement("div", _extends({
    style: {
      display: "flex",
      alignItems: "center",
      gap: 4,
      ...style
    }
  }, rest), btn("−", () => onChange(Math.max(min, value - 1)), value <= min), /*#__PURE__*/React.createElement("div", {
    "aria-live": "polite",
    style: {
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
      fontFamily: "var(--td-font-mono)"
    }
  }, value), btn("+", () => onChange(Math.min(max, value + 1)), value >= max));
}
Object.assign(__ds_scope, { Stepper });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/forms/Stepper.jsx", error: String((e && e.message) || e) }); }

// ui_kits/combine/Combine.jsx
try { (() => {
/* Combine Evaluation Dashboard — risk-first: the MLL/drawdown hero
   dominates. Three account states (ACTIVE / PASSED / FAILED) and three
   tiers (50K / 100K / 150K), deterministic mock data. */

const TIERS = {
  "50K": {
    start: 50000,
    target: 3000,
    trail: 2000,
    k: 1
  },
  "100K": {
    start: 100000,
    target: 6000,
    trail: 4000,
    k: 2
  },
  "150K": {
    start: 150000,
    target: 9000,
    trail: 4500,
    k: 3
  }
};
const MIN_DAYS = 2;
const fmt = (v, signed) => {
  if (!isFinite(v)) return "—";
  const s = signed ? v > 0 ? "+" : v < 0 ? "−" : "" : v < 0 ? "−" : "";
  return s + "$" + Math.abs(v).toLocaleString("en-US", {
    maximumFractionDigits: 0
  });
};
const fmt2 = (v, signed) => {
  const s = signed ? v > 0 ? "+" : v < 0 ? "−" : "" : v < 0 ? "−" : "";
  return s + "$" + Math.abs(v).toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2
  });
};

/* Base per-50K day ledgers per state; scaled by tier k. */
const SCENARIOS = {
  ACTIVE: {
    days: [480, 460, 300],
    todayIdx: 2
  },
  PASSED: {
    days: [900, 850, 780, 670],
    todayIdx: 3
  },
  FAILED: {
    days: [480, 460, 300, -1880],
    todayIdx: 3
  }
};
const DAY_DATES = ["Mon Jun 1", "Tue Jun 2", "Wed Jun 3", "Thu Jun 4"];
function buildModel(tierKey, state) {
  const t = TIERS[tierKey];
  const sc = SCENARIOS[state];
  const days = sc.days.map(d => d * t.k);
  const profit = days.reduce((a, b) => a + b, 0);
  const balance = t.start + profit;

  // High-water mark drives the trailing floor.
  // ACTIVE/FAILED: account peaked +trail above start intraday (floor lifted to start).
  // PASSED: at a new high.
  let highWater;
  if (state === "PASSED") highWater = balance;else highWater = t.start + t.trail; // peaked exactly one trail-distance up
  const floor = highWater - t.trail;
  const distance = balance - floor; // <0 means breached
  const ratio = distance / t.trail;

  // consistency: best day's share of total positive profit
  const grossProfit = days.filter(d => d > 0).reduce((a, b) => a + b, 0);
  const bestDay = Math.max(...days);
  const bestShare = grossProfit > 0 ? bestDay / grossProfit : 0;
  const daysTraded = days.length;
  const checks = {
    profit: profit >= t.target,
    minDays: daysTraded >= MIN_DAYS,
    consistency: bestShare < 0.5 || profit <= 0,
    aboveFloor: distance > 0
  };
  // derived state (FAILED forced when breached)
  let derived = state;
  if (!checks.aboveFloor) derived = "FAILED";else if (checks.profit && checks.minDays && checks.consistency) derived = "PASSED";else derived = "ACTIVE";
  return {
    t,
    tierKey,
    stateKey: state,
    state: derived,
    days,
    profit,
    balance,
    highWater,
    floor,
    distance,
    ratio,
    grossProfit,
    bestDay,
    bestShare,
    daysTraded,
    checks
  };
}
function tone(ratio) {
  if (ratio < 0.10) return "red";
  if (ratio < 0.25) return "amber";
  return "green";
}

/* ---------- gauge ---------- */
function Gauge({
  m
}) {
  const min = m.t.start - m.t.trail; // original floor at combine open
  const passLine = m.t.start + m.t.target; // the pass line
  const max = Math.max(passLine, m.highWater, m.balance) + m.t.trail * 0.18;
  const span = max - min;
  const pos = v => Math.max(0, Math.min(100, (v - min) / span * 100));
  const origFloorP = pos(m.t.start - m.t.trail); // = 0
  const floorP = pos(m.floor);
  const youP = pos(m.balance);
  const hwP = pos(m.highWater);
  const targetP = pos(passLine);
  const breached = m.distance <= 0;
  const cushionWarn = m.ratio < 0.25 && m.ratio >= 0;
  return /*#__PURE__*/React.createElement("div", {
    className: "cb-gauge"
  }, /*#__PURE__*/React.createElement("div", {
    className: "cb-gauge-track"
  }, /*#__PURE__*/React.createElement("div", {
    className: "cb-seg danger",
    style: {
      left: 0,
      width: floorP + "%"
    }
  }), breached ? /*#__PURE__*/React.createElement("div", {
    className: "cb-seg breach",
    style: {
      left: youP + "%",
      width: floorP - youP + "%"
    }
  }) : /*#__PURE__*/React.createElement("div", {
    className: "cb-seg cushion" + (cushionWarn ? " warn" : ""),
    style: {
      left: floorP + "%",
      width: youP - floorP + "%"
    }
  }), /*#__PURE__*/React.createElement("div", {
    className: "cb-seg toward",
    style: {
      left: youP + "%",
      width: Math.max(0, targetP - youP) + "%"
    }
  })), floorP > origFloorP + 1 && /*#__PURE__*/React.createElement("div", {
    className: "cb-trail",
    style: {
      left: origFloorP + "%",
      width: floorP - origFloorP + "%"
    }
  }, /*#__PURE__*/React.createElement("span", {
    className: "tl"
  }, "floor trailed up"), /*#__PURE__*/React.createElement("span", {
    className: "line"
  }), /*#__PURE__*/React.createElement("span", {
    className: "arr"
  }, "\u25B8")), /*#__PURE__*/React.createElement("div", {
    className: "cb-mark floor",
    style: {
      left: floorP + "%"
    }
  }, /*#__PURE__*/React.createElement("span", {
    className: "lab"
  }, "FLOOR ", fmt(m.floor)), /*#__PURE__*/React.createElement("span", {
    className: "stem"
  })), /*#__PURE__*/React.createElement("div", {
    className: "cb-mark you " + (breached ? "bear" : "bull"),
    style: {
      left: youP + "%"
    }
  }, /*#__PURE__*/React.createElement("span", {
    className: "lab"
  }, "YOU ", fmt(m.balance)), /*#__PURE__*/React.createElement("span", {
    className: "stem"
  })), /*#__PURE__*/React.createElement("div", {
    className: "cb-mark hw",
    style: {
      left: hwP + "%"
    }
  }, /*#__PURE__*/React.createElement("span", {
    className: "lab"
  }, "HWM ", fmt(m.highWater)), /*#__PURE__*/React.createElement("span", {
    className: "stem"
  })), /*#__PURE__*/React.createElement("div", {
    className: "cb-mark target",
    style: {
      left: targetP + "%"
    }
  }, /*#__PURE__*/React.createElement("span", {
    className: "lab",
    style: {
      transform: "translateX(-50%)"
    }
  }, "PASS ", fmt(passLine)), /*#__PURE__*/React.createElement("span", {
    className: "stem"
  })));
}

/* ---------- hero ---------- */
function Hero({
  m
}) {
  const breached = m.distance <= 0;
  const tn = breached ? "red" : tone(m.ratio);
  const trailedFrom = m.t.start - m.t.trail;
  return /*#__PURE__*/React.createElement("div", {
    className: "cb-hero"
  }, /*#__PURE__*/React.createElement("div", {
    className: "cb-hero-head"
  }, /*#__PURE__*/React.createElement("span", {
    className: "k"
  }, "Maximum Loss Limit \xB7 Trailing Drawdown"), /*#__PURE__*/React.createElement("span", {
    className: "sub"
  }, breached ? "Account breached" : "Distance to the floor")), /*#__PURE__*/React.createElement("div", {
    className: "cb-hero-body"
  }, /*#__PURE__*/React.createElement("div", {
    className: "cb-hero-top"
  }, /*#__PURE__*/React.createElement("div", {
    className: "cb-distance " + tn
  }, /*#__PURE__*/React.createElement("span", {
    className: "big"
  }, fmt(Math.abs(m.distance))), /*#__PURE__*/React.createElement("span", {
    className: "cap"
  }, breached ? "below floor — account failed" : "above floor")), /*#__PURE__*/React.createElement("div", {
    className: "cb-hero-stats"
  }, /*#__PURE__*/React.createElement("div", {
    className: "cb-hstat"
  }, /*#__PURE__*/React.createElement("span", {
    className: "l"
  }, "MLL Floor"), /*#__PURE__*/React.createElement("span", {
    className: "v pos"
  }, fmt(m.floor))), /*#__PURE__*/React.createElement("div", {
    className: "cb-hstat"
  }, /*#__PURE__*/React.createElement("span", {
    className: "l"
  }, "Trail dist."), /*#__PURE__*/React.createElement("span", {
    className: "v"
  }, fmt(m.t.trail))), /*#__PURE__*/React.createElement("div", {
    className: "cb-hstat"
  }, /*#__PURE__*/React.createElement("span", {
    className: "l"
  }, "High-water"), /*#__PURE__*/React.createElement("span", {
    className: "v bull"
  }, fmt(m.highWater))))), /*#__PURE__*/React.createElement(Gauge, {
    m: m
  }), /*#__PURE__*/React.createElement("div", {
    className: "cb-hero-foot"
  }, breached ? /*#__PURE__*/React.createElement("span", null, "Balance fell ", /*#__PURE__*/React.createElement("b", null, fmt(Math.abs(m.distance))), " below the trailing floor. The combine is over.") : /*#__PURE__*/React.createElement("span", null, "Floor has trailed up ", /*#__PURE__*/React.createElement("b", null, fmt(m.floor - trailedFrom)), " from its ", fmt(trailedFrom), " open \u2014 lose ", /*#__PURE__*/React.createElement("b", null, fmt(m.distance)), " more and you're out."))));
}

/* ---------- profit target ---------- */
function ProfitTarget({
  m
}) {
  const pct = Math.max(0, Math.min(100, m.profit / m.t.target * 100));
  const done = m.checks.profit;
  return /*#__PURE__*/React.createElement("div", {
    className: "cb-panel"
  }, /*#__PURE__*/React.createElement("div", {
    className: "cb-phead"
  }, /*#__PURE__*/React.createElement("span", {
    className: "k"
  }, "Profit Target \xB7 6%"), /*#__PURE__*/React.createElement("span", {
    className: "r"
  }, "how to pass")), /*#__PURE__*/React.createElement("div", {
    className: "cb-pt-body"
  }, /*#__PURE__*/React.createElement("div", {
    className: "cb-pt-nums"
  }, /*#__PURE__*/React.createElement("span", {
    className: "cur"
  }, fmt(Math.max(0, m.profit))), /*#__PURE__*/React.createElement("span", {
    className: "tot"
  }, "/ ", fmt(m.t.target)), /*#__PURE__*/React.createElement("span", {
    className: "pct" + (done ? " done" : "")
  }, pct.toFixed(0), "%")), /*#__PURE__*/React.createElement("div", {
    className: "cb-bar"
  }, /*#__PURE__*/React.createElement("div", {
    className: "cb-bar fill" + (done ? " done" : "") + (m.profit < 0 ? " neg" : ""),
    style: {
      width: (m.profit < 0 ? 100 : pct) + "%",
      position: "absolute",
      border: "none"
    }
  })), /*#__PURE__*/React.createElement("span", {
    className: "cb-pt-cap"
  }, done ? "Target reached" : fmt(m.t.target - m.profit) + " to go · no time limit")));
}

/* ---------- checklist ---------- */
function Checklist({
  m
}) {
  const rows = [{
    pass: m.checks.profit,
    t: "Profit target reached",
    d: `${fmt(Math.max(0, m.profit))} of ${fmt(m.t.target)}`
  }, {
    pass: m.checks.minDays,
    t: `Minimum ${MIN_DAYS} trading days`,
    d: `${m.daysTraded} of ${MIN_DAYS} days traded`
  }, {
    pass: m.checks.consistency,
    t: "Consistency rule (≤50%)",
    d: `best day is ${(m.bestShare * 100).toFixed(0)}% of total profit`,
    bad: !m.checks.consistency
  }, {
    pass: m.checks.aboveFloor,
    t: "Above MLL floor",
    d: m.distance > 0 ? `${fmt(m.distance)} of cushion remaining` : `breached by ${fmt(Math.abs(m.distance))}`,
    bad: !m.checks.aboveFloor
  }];
  const remaining = rows.filter(r => !r.pass).length;
  return /*#__PURE__*/React.createElement("div", {
    className: "cb-panel"
  }, /*#__PURE__*/React.createElement("div", {
    className: "cb-phead"
  }, /*#__PURE__*/React.createElement("span", {
    className: "k"
  }, "Evaluation Checklist"), /*#__PURE__*/React.createElement("span", {
    className: "r"
  }, remaining === 0 ? "all clear" : remaining + " remaining")), /*#__PURE__*/React.createElement("div", {
    className: "cb-check"
  }, rows.map((r, i) => /*#__PURE__*/React.createElement("div", {
    className: "cb-check-row",
    key: i
  }, /*#__PURE__*/React.createElement("span", {
    className: "cb-check-mark " + (r.pass ? "pass" : r.bad ? "fail" : "pending")
  }, r.pass ? "✓" : r.bad ? "✗" : "○"), /*#__PURE__*/React.createElement("span", {
    className: "cb-check-txt"
  }, /*#__PURE__*/React.createElement("span", {
    className: "t"
  }, r.t), /*#__PURE__*/React.createElement("span", {
    className: "d" + (r.pass ? " bull" : r.bad ? " bear" : "")
  }, r.d))))));
}

/* ---------- daily breakdown ---------- */
function DailyBreakdown({
  m
}) {
  const maxAbs = Math.max(...m.days.map(d => Math.abs(d)), 1);
  return /*#__PURE__*/React.createElement("div", {
    className: "cb-panel"
  }, /*#__PURE__*/React.createElement("div", {
    className: "cb-phead"
  }, /*#__PURE__*/React.createElement("span", {
    className: "k"
  }, "Daily Breakdown"), /*#__PURE__*/React.createElement("span", {
    className: "r"
  }, "consistency input")), /*#__PURE__*/React.createElement("div", {
    className: "cb-days"
  }, m.days.map((d, i) => {
    const isBest = d === m.bestDay && d > 0;
    const share = m.grossProfit > 0 && d > 0 ? d / m.grossProfit : 0;
    const flag = share >= 0.5;
    const w = Math.abs(d) / maxAbs * 50;
    const isToday = i === SCENARIOS[m.stateKey].todayIdx;
    return /*#__PURE__*/React.createElement("div", {
      className: "cb-day-row" + (isBest ? " best" : ""),
      key: i
    }, /*#__PURE__*/React.createElement("span", {
      className: "cb-day-date"
    }, DAY_DATES[i], isToday ? /*#__PURE__*/React.createElement("span", {
      className: "today"
    }, "today") : null), /*#__PURE__*/React.createElement("span", {
      className: "cb-day-meter"
    }, /*#__PURE__*/React.createElement("span", {
      className: "mid"
    }), d >= 0 ? /*#__PURE__*/React.createElement("span", {
      className: "f bull",
      style: {
        width: w + "%"
      }
    }) : /*#__PURE__*/React.createElement("span", {
      className: "f bear",
      style: {
        width: w + "%"
      }
    })), /*#__PURE__*/React.createElement("span", {
      className: "cb-day-pnl " + (d >= 0 ? "bull" : "bear")
    }, fmt2(d, true)), /*#__PURE__*/React.createElement("span", {
      className: "cb-day-share" + (flag ? " flag" : "")
    }, d > 0 ? (share * 100).toFixed(0) + "%" : "—"));
  })), /*#__PURE__*/React.createElement("div", {
    className: "cb-days-foot"
  }, /*#__PURE__*/React.createElement("span", null, "Best day vs total"), /*#__PURE__*/React.createElement("span", {
    className: "best-share" + (m.bestShare >= 0.5 ? " flag" : "")
  }, fmt2(m.bestDay, true), " \xB7 ", (m.bestShare * 100).toFixed(0), "% ", m.bestShare >= 0.5 ? "· over 50% ✗" : "· under 50% ✓")));
}
window.CombineParts = {
  buildModel,
  Hero,
  ProfitTarget,
  Checklist,
  DailyBreakdown,
  fmt,
  TIERS
};
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/combine/Combine.jsx", error: String((e && e.message) || e) }); }

// ui_kits/data/trades.js
try { (() => {
/* Shared closed-trade ledger for the Journal + Analytics screens.
   Deterministic mock: 14 0DTE trades, ~50% win rate, avg win slightly
   over avg loss, net modestly positive, with a visible mid-record
   drawdown. Both screens derive everything from TRADES + aggregations,
   so the journal and analytics never disagree. */
(function () {
  // [date, dow, entryTime, exitTime, symbol, strategy, structure,
  //  entry$, exit$, qty, note, tags]
  const SPEC = [["May 19", "Tue", "09:38", "10:12", "SPY", "long call", "756C", 0.85, 1.55, 4, "", []], ["May 19", "Tue", "11:05", "13:20", "NVDA", "long call", "880C", 1.10, 2.15, 4, "", []], ["May 20", "Wed", "09:45", "10:30", "QQQ", "long put", "478P", 1.20, 0.60, 4, "", []], ["May 21", "Thu", "10:10", "11:45", "SPY", "straddle", "754C / 754P", 2.30, 3.00, 5, "Planned vol expansion into the morning range break. Sized right, took profit at target.", ["planned", "good setup"]], ["May 22", "Fri", "13:00", "14:15", "IWM", "put spread", "224P / 220P", 1.20, 0.60, 3, "", []], ["May 26", "Tue", "09:50", "10:20", "SPY", "call spread", "755C / 758C", 1.00, 1.95, 2, "", []], ["May 27", "Wed", "09:40", "11:10", "QQQ", "long call", "480C", 1.40, 0.70, 5, "Chased the open after missing the first move. No setup, just FOMO. Should have waited.", ["FOMO", "broke rules"]], ["May 27", "Wed", "12:30", "14:00", "SPY", "long put", "753P", 1.30, 0.65, 4, "", []], ["May 28", "Thu", "10:00", "13:30", "NVDA", "iron condor", "860P/865P · 895C/900C", 1.50, 0.75, 4, "Held too long into the afternoon trying to make it back. Theta chewed the wings. Revenge.", ["revenge trade", "broke rules"]], ["May 29", "Fri", "09:35", "11:20", "AAPL", "long call", "232C", 1.20, 2.90, 3, "A+ trend day, clean setup off the open. Let it run, trailed the stop.", ["planned", "good setup"]], ["Jun 2", "Tue", "10:15", "11:00", "SPY", "long call", "757C", 1.00, 0.525, 4, "", []], ["Jun 3", "Wed", "09:55", "12:40", "QQQ", "straddle", "477C / 477P", 2.40, 3.00, 4, "", []], ["Jun 4", "Thu", "13:10", "14:30", "SPY", "put spread", "754P / 751P", 1.05, 0.50, 4, "Decent thesis, market chopped sideways. Clean loss, within plan.", ["planned"]], ["Jun 5", "Fri", "09:42", "11:15", "NVDA", "long call", "885C", 1.10, 2.20, 3, "", []]];
  const greeksFor = (i, win) => ({
    delta: (0.42 + i % 4 * 0.07).toFixed(2),
    theta: "−" + (38 + i % 5 * 9).toFixed(0),
    gamma: (0.9 + i % 3 * 0.4).toFixed(2),
    vega: (11 + i % 4 * 2).toFixed(0)
  });
  const toMin = t => {
    const [h, m] = t.split(":").map(Number);
    return h * 60 + m;
  };
  const TRADES = SPEC.map((s, i) => {
    const [date, dow, tin, tout, sym, strat, struct, entry, exit, qty, note, tags] = s;
    const pnl = Math.round((exit - entry) * 100 * qty);
    const win = pnl >= 0;
    const risk = entry * 100 * qty; // debit at risk for these structures
    const retPct = (exit - entry) / entry * 100;
    const rMultiple = (exit - entry) / entry; // R relative to debit risk
    const hold = toMin(tout) - toMin(tin);
    const hour = Number(tin.split(":")[0]);
    const bucket = hour < 10 || hour === 10 && toMin(tin) < 630 ? "Open" : hour < 13 ? "Midday" : "Power hour";
    return {
      id: i + 1,
      date,
      dow,
      tin,
      tout,
      sym,
      strat,
      struct,
      entry,
      exit,
      qty,
      pnl,
      win,
      risk,
      retPct,
      rMultiple,
      hold,
      hour,
      bucket,
      greeks: greeksFor(i, win),
      note,
      tags
    };
  });

  // ---- date-range membership (relative to "today" = Jun 5 in the mock) ----
  const WEEK = new Set(["Jun 2", "Jun 3", "Jun 4", "Jun 5"]);
  function inRange(t, range) {
    if (range === "All" || range === "Month") return true; // record started this month
    if (range === "Week") return WEEK.has(t.date);
    if (range === "Today") return t.date === "Jun 5";
    return true;
  }

  // ---- aggregations ----
  function summarize(trades) {
    const n = trades.length;
    const wins = trades.filter(t => t.win);
    const losses = trades.filter(t => !t.win);
    const net = trades.reduce((a, t) => a + t.pnl, 0);
    const grossWin = wins.reduce((a, t) => a + t.pnl, 0);
    const grossLoss = Math.abs(losses.reduce((a, t) => a + t.pnl, 0));
    const winRate = n ? wins.length / n * 100 : 0;
    const avgWin = wins.length ? grossWin / wins.length : 0;
    const avgLoss = losses.length ? grossLoss / losses.length : 0;
    const profitFactor = grossLoss ? grossWin / grossLoss : grossWin ? Infinity : 0;
    const expectancy = n ? net / n : 0;
    const avgHoldWin = wins.length ? Math.round(wins.reduce((a, t) => a + t.hold, 0) / wins.length) : 0;
    const avgHoldLoss = losses.length ? Math.round(losses.reduce((a, t) => a + t.hold, 0) / losses.length) : 0;
    return {
      n,
      wins: wins.length,
      losses: losses.length,
      net,
      grossWin,
      grossLoss,
      winRate,
      avgWin,
      avgLoss,
      profitFactor,
      expectancy,
      avgHoldWin,
      avgHoldLoss
    };
  }

  // cumulative equity points (in trade order), plus drawdown stats
  function equity(trades) {
    let cum = 0,
      peak = 0,
      maxDD = 0,
      ddStart = null,
      ddTrough = null;
    const pts = trades.map((t, i) => {
      cum += t.pnl;
      if (cum > peak) peak = cum;
      const dd = peak - cum;
      if (dd > maxDD) {
        maxDD = dd;
        ddTrough = i;
      }
      return {
        i,
        cum,
        peak,
        dd
      };
    });
    return {
      pts,
      maxDD
    };
  }
  function groupBy(trades, keyFn) {
    const map = new Map();
    trades.forEach(t => {
      const k = keyFn(t);
      if (!map.has(k)) map.set(k, []);
      map.get(k).push(t);
    });
    return [...map.entries()].map(([k, ts]) => {
      const net = ts.reduce((a, t) => a + t.pnl, 0);
      const w = ts.filter(t => t.win).length;
      return {
        key: k,
        net,
        n: ts.length,
        wins: w,
        winRate: w / ts.length * 100
      };
    });
  }
  function streaks(trades) {
    let best = 0,
      worst = 0,
      cur = 0;
    trades.forEach(t => {
      if (t.win) cur = cur > 0 ? cur + 1 : 1;else cur = cur < 0 ? cur - 1 : -1;
      best = Math.max(best, cur);
      worst = Math.min(worst, cur);
    });
    // current streak from the tail
    let tail = 0;
    for (let i = trades.length - 1; i >= 0; i--) {
      if (i === trades.length - 1) tail = trades[i].win ? 1 : -1;else if (trades[i].win && tail > 0 || !trades[i].win && tail < 0) tail += trades[i].win ? 1 : -1;else break;
    }
    return {
      best,
      worst,
      current: tail
    };
  }
  const fmt = (v, signed) => {
    const s = signed ? v > 0 ? "+" : v < 0 ? "−" : "" : v < 0 ? "−" : "";
    return s + "$" + Math.abs(Math.round(v)).toLocaleString("en-US");
  };
  const fmtHold = m => m >= 60 ? Math.floor(m / 60) + "h " + m % 60 + "m" : m + "m";
  window.TDJournal = {
    TRADES,
    inRange,
    summarize,
    equity,
    groupBy,
    streaks,
    fmt,
    fmtHold,
    MLL_TRAIL: 2000,
    // 50K combine trail distance (risk-panel reference)
    TIER: "50K"
  };
})();
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/data/trades.js", error: String((e && e.message) || e) }); }

// ui_kits/funded/Funded.jsx
try { (() => {
/* Funded Account view — risk-first (MLL hero) + funded-specific payout
   eligibility, 50/50 split breakdown, withdrawal history.
   Deterministic mock; ELIGIBLE / LOCKED payout states; 50K/100K/150K. */

const FN_TIERS = {
  "50K": {
    start: 50000,
    trail: 2000
  },
  "100K": {
    start: 100000,
    trail: 4000
  },
  "150K": {
    start: 150000,
    trail: 4500
  }
};
const SPLIT = 0.5; // 50/50
const GREEN_MIN = 150; // each green day must clear >$150
const GREEN_NEED = 3; // 3 cumulative qualifying green days
const CONSISTENCY = 0.40; // no green day > 40% of cycle profit

const fmtN = (v, signed) => {
  const s = signed ? v > 0 ? "+" : v < 0 ? "−" : "" : v < 0 ? "−" : "";
  return s + "$" + Math.abs(Math.round(v)).toLocaleString("en-US");
};

/* Cycle-since-last-payout ledgers. Day P&L is FIXED across tiers (a
   trader's recent week is what it is); only start + trail scale by tier.
   LOCKED: 2 qualifying green days. ELIGIBLE: 3 (and 31% best-day share). */
const FN_CYCLES = {
  LOCKED: [["Mon Jun 1", 300], ["Tue Jun 2", 140], ["Wed Jun 3", -70], ["Thu Jun 4", 300], ["Fri Jun 5", 120]],
  ELIGIBLE: [["Mon Jun 1", 300], ["Tue Jun 2", 140], ["Wed Jun 3", -70], ["Thu Jun 4", 300], ["Fri Jun 5", 290]]
};
// prior payout (fixed) — drives history + lifetime numbers
const PRIOR_PAYOUT = {
  date: "May 27",
  gross: 1400,
  daysAgo: 9
};
function fundedModel(tierKey, payoutState) {
  const t = FN_TIERS[tierKey];
  const cycle = FN_CYCLES[payoutState];
  const days = cycle.map(([d, p]) => ({
    date: d,
    pnl: p
  }));
  const profitCycle = days.reduce((a, b) => a + b.pnl, 0);
  const grossPositive = days.filter(d => d.pnl > 0).reduce((a, b) => a + b.pnl, 0);
  const qualifying = days.filter(d => d.pnl > GREEN_MIN).length;
  const bestGreen = Math.max(...days.map(d => d.pnl));
  const bestShare = grossPositive > 0 ? bestGreen / grossPositive : 0;
  const balance = t.start + profitCycle;
  const floor = t.start; // funded floor locks at funded capital
  const distance = balance - floor; // = profitCycle
  const ratio = distance / t.trail;
  const checks = {
    greenDays: qualifying >= GREEN_NEED,
    overMin: days.filter(d => d.pnl > 0).every(d => d.pnl > GREEN_MIN) || qualifying >= GREEN_NEED,
    consistency: bestShare <= CONSISTENCY,
    weekly: PRIOR_PAYOUT.daysAgo >= 7
  };
  const eligible = checks.greenDays && checks.consistency && checks.weekly;

  // split math (since last payout)
  const yourShare = profitCycle > 0 ? profitCycle * SPLIT : 0;
  const firmShare = profitCycle > 0 ? profitCycle * SPLIT : 0;
  const withdrawable = eligible ? yourShare : 0;

  // lifetime since funding
  const lifetimeGross = PRIOR_PAYOUT.gross + Math.max(0, profitCycle);
  const lifetimePaidToYou = PRIOR_PAYOUT.gross * SPLIT;
  return {
    t,
    tierKey,
    payoutState,
    days,
    profitCycle,
    grossPositive,
    qualifying,
    bestGreen,
    bestShare,
    balance,
    floor,
    distance,
    ratio,
    checks,
    eligible,
    yourShare,
    firmShare,
    withdrawable,
    lifetimeGross,
    lifetimePaidToYou
  };
}
function fnTone(ratio, breached) {
  if (breached || ratio < 0.10) return "red";
  if (ratio < 0.25) return "amber";
  return "green";
}

/* gauge — funded floor locked at start; still shows trail history */
function FnGauge({
  m
}) {
  const min = m.t.start - m.t.trail;
  const max = m.t.start + m.t.trail * 1.1;
  const span = max - min;
  const pos = v => Math.max(0, Math.min(100, (v - min) / span * 100));
  const floorP = pos(m.floor);
  const youP = pos(m.balance);
  const breached = m.distance <= 0;
  const warn = m.ratio < 0.25 && m.ratio >= 0;
  return /*#__PURE__*/React.createElement("div", {
    className: "cb-gauge"
  }, /*#__PURE__*/React.createElement("div", {
    className: "cb-gauge-track"
  }, /*#__PURE__*/React.createElement("div", {
    className: "cb-seg danger",
    style: {
      left: 0,
      width: floorP + "%"
    }
  }), breached ? /*#__PURE__*/React.createElement("div", {
    className: "cb-seg breach",
    style: {
      left: youP + "%",
      width: floorP - youP + "%"
    }
  }) : /*#__PURE__*/React.createElement("div", {
    className: "cb-seg cushion" + (warn ? " warn" : ""),
    style: {
      left: floorP + "%",
      width: youP - floorP + "%"
    }
  })), /*#__PURE__*/React.createElement("div", {
    className: "cb-trail",
    style: {
      left: "0%",
      width: floorP + "%"
    }
  }, /*#__PURE__*/React.createElement("span", {
    className: "tl"
  }, "floor locked at funded capital"), /*#__PURE__*/React.createElement("span", {
    className: "line"
  }), /*#__PURE__*/React.createElement("span", {
    className: "arr"
  }, "\u25B8")), /*#__PURE__*/React.createElement("div", {
    className: "cb-mark floor",
    style: {
      left: floorP + "%"
    }
  }, /*#__PURE__*/React.createElement("span", {
    className: "lab"
  }, "FLOOR ", fmtN(m.floor)), /*#__PURE__*/React.createElement("span", {
    className: "stem"
  })), /*#__PURE__*/React.createElement("div", {
    className: "cb-mark you " + (breached ? "bear" : "bull"),
    style: {
      left: youP + "%"
    }
  }, /*#__PURE__*/React.createElement("span", {
    className: "lab"
  }, "YOU ", fmtN(m.balance)), /*#__PURE__*/React.createElement("span", {
    className: "stem"
  })));
}
function FnHero({
  m
}) {
  const breached = m.distance <= 0;
  const tn = fnTone(m.ratio, breached);
  return /*#__PURE__*/React.createElement("div", {
    className: "cb-hero"
  }, /*#__PURE__*/React.createElement("div", {
    className: "cb-hero-head"
  }, /*#__PURE__*/React.createElement("span", {
    className: "k"
  }, "Maximum Loss Limit \xB7 Trailing Drawdown \xB7 Real Capital"), /*#__PURE__*/React.createElement("span", {
    className: "sub"
  }, breached ? "Account breached" : "Distance to the floor")), /*#__PURE__*/React.createElement("div", {
    className: "cb-hero-body"
  }, /*#__PURE__*/React.createElement("div", {
    className: "cb-hero-top"
  }, /*#__PURE__*/React.createElement("div", {
    className: "cb-distance " + tn
  }, /*#__PURE__*/React.createElement("span", {
    className: "big"
  }, fmtN(Math.abs(m.distance))), /*#__PURE__*/React.createElement("span", {
    className: "cap"
  }, breached ? "below floor — funded account lost" : "above floor")), /*#__PURE__*/React.createElement("div", {
    className: "cb-hero-stats"
  }, /*#__PURE__*/React.createElement("div", {
    className: "cb-hstat"
  }, /*#__PURE__*/React.createElement("span", {
    className: "l"
  }, "MLL Floor"), /*#__PURE__*/React.createElement("span", {
    className: "v pos"
  }, fmtN(m.floor))), /*#__PURE__*/React.createElement("div", {
    className: "cb-hstat"
  }, /*#__PURE__*/React.createElement("span", {
    className: "l"
  }, "Trail dist."), /*#__PURE__*/React.createElement("span", {
    className: "v"
  }, fmtN(m.t.trail))), /*#__PURE__*/React.createElement("div", {
    className: "cb-hstat"
  }, /*#__PURE__*/React.createElement("span", {
    className: "l"
  }, "Balance"), /*#__PURE__*/React.createElement("span", {
    className: "v bull"
  }, fmtN(m.balance))))), /*#__PURE__*/React.createElement(FnGauge, {
    m: m
  }), /*#__PURE__*/React.createElement("div", {
    className: "cb-hero-foot"
  }, /*#__PURE__*/React.createElement("span", null, "This is firm capital. Lose ", /*#__PURE__*/React.createElement("b", null, fmtN(m.distance)), " more and the funded account is gone \u2014 getting paid is secondary to not blowing up."))));
}
function Eligibility({
  m,
  onRequest
}) {
  const rows = [{
    pass: m.checks.greenDays,
    t: `${GREEN_NEED} cumulative green days`,
    d: `${m.qualifying} of ${GREEN_NEED} days over ${fmtN(GREEN_MIN)}`
  }, {
    pass: m.checks.overMin,
    t: `Each green day over ${fmtN(GREEN_MIN)}`,
    d: m.qualifying >= GREEN_NEED ? "all qualifying days clear it" : `${m.qualifying} qualifying so far`
  }, {
    pass: m.checks.consistency,
    t: `Consistency rule (≤${CONSISTENCY * 100 | 0}%)`,
    d: `best green day is ${(m.bestShare * 100).toFixed(0)}% of cycle profit`,
    bad: !m.checks.consistency
  }, {
    pass: m.checks.weekly,
    t: "One request per week",
    d: `last payout ${PRIOR_PAYOUT.daysAgo} days ago`,
    bad: !m.checks.weekly
  }];
  return /*#__PURE__*/React.createElement("div", {
    className: "cb-panel"
  }, /*#__PURE__*/React.createElement("div", {
    className: "cb-phead"
  }, /*#__PURE__*/React.createElement("span", {
    className: "k"
  }, "Payout Eligibility"), /*#__PURE__*/React.createElement("span", {
    className: "r"
  }, m.eligible ? "ready" : GREEN_NEED - m.qualifying + " green day to go")), /*#__PURE__*/React.createElement("div", {
    className: "fn-elig-status " + (m.eligible ? "ready" : "locked")
  }, /*#__PURE__*/React.createElement("span", {
    className: "ic"
  }, m.eligible ? "✓" : "⏳"), /*#__PURE__*/React.createElement("span", {
    className: "txt"
  }, /*#__PURE__*/React.createElement("span", {
    className: "big"
  }, m.eligible ? "You can request a payout" : "Payout locked"), /*#__PURE__*/React.createElement("span", {
    className: "sm"
  }, m.eligible ? "All requirements met since your last payout" : "Keep trading green to unlock — you're almost there"))), /*#__PURE__*/React.createElement("div", {
    className: "fn-greendays"
  }, Array.from({
    length: GREEN_NEED
  }).map((_, i) => /*#__PURE__*/React.createElement("span", {
    key: i,
    className: "pip" + (i < m.qualifying ? " on" : "")
  }, i < m.qualifying ? "✓" : i + 1)), /*#__PURE__*/React.createElement("span", {
    className: "lab"
  }, /*#__PURE__*/React.createElement("b", null, m.qualifying), " of ", GREEN_NEED, " qualifying green days")), /*#__PURE__*/React.createElement("div", {
    className: "cb-check"
  }, rows.map((r, i) => /*#__PURE__*/React.createElement("div", {
    className: "cb-check-row",
    key: i
  }, /*#__PURE__*/React.createElement("span", {
    className: "cb-check-mark " + (r.pass ? "pass" : r.bad ? "fail" : "pending")
  }, r.pass ? "✓" : r.bad ? "✗" : "○"), /*#__PURE__*/React.createElement("span", {
    className: "cb-check-txt"
  }, /*#__PURE__*/React.createElement("span", {
    className: "t"
  }, r.t), /*#__PURE__*/React.createElement("span", {
    className: "d" + (r.pass ? " bull" : r.bad ? " bear" : "")
  }, r.d))))), m.eligible ? /*#__PURE__*/React.createElement("a", {
    className: "fn-req-btn on",
    href: "../payout/index.html"
  }, "REQUEST PAYOUT \xB7 ", fmtN(m.withdrawable), " \u2192") : /*#__PURE__*/React.createElement("button", {
    className: "fn-req-btn off",
    disabled: true
  }, "REQUEST PAYOUT \u2014 locked"));
}
function SplitBreakdown({
  m
}) {
  return /*#__PURE__*/React.createElement("div", {
    className: "cb-panel"
  }, /*#__PURE__*/React.createElement("div", {
    className: "cb-phead"
  }, /*#__PURE__*/React.createElement("span", {
    className: "k"
  }, "Profit & Split \xB7 50 / 50"), /*#__PURE__*/React.createElement("span", {
    className: "r"
  }, "since last payout")), /*#__PURE__*/React.createElement("div", {
    className: "fn-money"
  }, /*#__PURE__*/React.createElement("div", {
    className: "fn-money-row"
  }, /*#__PURE__*/React.createElement("span", {
    className: "l"
  }, "Profit since last payout"), /*#__PURE__*/React.createElement("span", {
    className: "v"
  }, fmtN(m.profitCycle, true))), /*#__PURE__*/React.createElement("div", {
    className: "fn-money-row you"
  }, /*#__PURE__*/React.createElement("span", {
    className: "l"
  }, "Your share", /*#__PURE__*/React.createElement("span", {
    className: "split-tag"
  }, "50%")), /*#__PURE__*/React.createElement("span", {
    className: "v"
  }, fmtN(m.yourShare))), /*#__PURE__*/React.createElement("div", {
    className: "fn-money-row firm"
  }, /*#__PURE__*/React.createElement("span", {
    className: "l"
  }, "Firm share", /*#__PURE__*/React.createElement("span", {
    className: "split-tag"
  }, "50%")), /*#__PURE__*/React.createElement("span", {
    className: "v"
  }, fmtN(m.firmShare))), /*#__PURE__*/React.createElement("div", {
    className: "fn-money-row"
  }, /*#__PURE__*/React.createElement("span", {
    className: "l"
  }, "Lifetime profit", /*#__PURE__*/React.createElement("span", {
    className: "s"
  }, "since funding")), /*#__PURE__*/React.createElement("span", {
    className: "v"
  }, fmtN(m.lifetimeGross)))), /*#__PURE__*/React.createElement("div", {
    className: "fn-withdrawable" + (m.withdrawable > 0 ? "" : " zero")
  }, /*#__PURE__*/React.createElement("span", {
    className: "l"
  }, "Withdrawable now"), /*#__PURE__*/React.createElement("span", {
    className: "v"
  }, fmtN(m.withdrawable))));
}
function History({
  m
}) {
  const paid = [{
    date: PRIOR_PAYOUT.date,
    gross: PRIOR_PAYOUT.gross,
    share: PRIOR_PAYOUT.gross * SPLIT,
    firm: PRIOR_PAYOUT.gross * SPLIT,
    status: "paid"
  }];
  return /*#__PURE__*/React.createElement("div", {
    className: "cb-panel"
  }, /*#__PURE__*/React.createElement("div", {
    className: "cb-phead"
  }, /*#__PURE__*/React.createElement("span", {
    className: "k"
  }, "Withdrawal History"), /*#__PURE__*/React.createElement("span", {
    className: "r"
  }, paid.length, " payout", paid.length !== 1 ? "s" : "")), /*#__PURE__*/React.createElement("div", {
    className: "fn-hist"
  }, /*#__PURE__*/React.createElement("div", {
    className: "fn-hist-row head"
  }, /*#__PURE__*/React.createElement("span", null, "Date"), /*#__PURE__*/React.createElement("span", {
    className: "fn-num-right"
  }, "Gross profit"), /*#__PURE__*/React.createElement("span", {
    className: "fn-num-right"
  }, "Your 50%"), /*#__PURE__*/React.createElement("span", {
    className: "fn-num-right"
  }, "Firm 50%"), /*#__PURE__*/React.createElement("span", null, "Status")), paid.length === 0 ? /*#__PURE__*/React.createElement("div", {
    className: "fn-hist-empty"
  }, "No payouts yet \u2014 meet the requirement above to request your first.") : paid.map((p, i) => /*#__PURE__*/React.createElement("div", {
    className: "fn-hist-row",
    key: i
  }, /*#__PURE__*/React.createElement("span", {
    className: "date"
  }, p.date), /*#__PURE__*/React.createElement("span", {
    className: "gross fn-num-right"
  }, fmtN(p.gross)), /*#__PURE__*/React.createElement("span", {
    className: "share fn-num-right"
  }, fmtN(p.share)), /*#__PURE__*/React.createElement("span", {
    className: "firm fn-num-right"
  }, fmtN(p.firm)), /*#__PURE__*/React.createElement("span", {
    className: "status paid"
  }, /*#__PURE__*/React.createElement("span", {
    className: "dot"
  }), "Paid")))));
}
window.FundedParts = {
  fundedModel,
  FnHero,
  Eligibility,
  SplitBreakdown,
  History,
  fmtN,
  FN_TIERS
};
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/funded/Funded.jsx", error: String((e && e.message) || e) }); }

// ui_kits/terminal/BottomRow.jsx
try { (() => {
/* Bottom panel row: OPEN POSITION · THETA SCRUBBER · KEY LEVELS · TODAY */
function BottomRow({
  position,
  upl,
  scrubT,
  setScrubT,
  onClose,
  greeks
}) {
  const d = window.TD;
  return /*#__PURE__*/React.createElement("div", {
    className: "td-bottom"
  }, /*#__PURE__*/React.createElement("section", {
    className: "bp pos"
  }, /*#__PURE__*/React.createElement("div", {
    className: "bp-head"
  }, /*#__PURE__*/React.createElement("span", {
    className: "k"
  }, "OPEN POSITION"), /*#__PURE__*/React.createElement("span", {
    className: "r"
  }, position ? "DTE 0" : "")), position ? /*#__PURE__*/React.createElement("div", {
    className: "pos-body"
  }, /*#__PURE__*/React.createElement("div", {
    className: "pos-title"
  }, /*#__PURE__*/React.createElement("span", {
    className: "tri"
  }, "\u25B2"), " ", /*#__PURE__*/React.createElement("b", null, "SPY"), " Long ", position.side), /*#__PURE__*/React.createElement("div", {
    className: "pos-meta"
  }, "K ", position.strike, " \xB7 entry 09:30 \xB7 ", position.contracts, " contract", position.contracts > 1 ? "s" : ""), /*#__PURE__*/React.createElement("div", {
    className: "pos-pnl " + (upl >= 0 ? "bull" : "bear")
  }, d.fmtMoney(upl, true)), /*#__PURE__*/React.createElement("div", {
    className: "pos-greeks"
  }, /*#__PURE__*/React.createElement("span", null, "\u0394 ", greeks.delta), /*#__PURE__*/React.createElement("span", null, "\u0393 ", greeks.gamma), /*#__PURE__*/React.createElement("span", {
    className: "bear"
  }, "\u03B8 ", greeks.theta), /*#__PURE__*/React.createElement("span", null, "\u03BD ", greeks.vega)), /*#__PURE__*/React.createElement("div", {
    className: "pos-be"
  }, "BE ", /*#__PURE__*/React.createElement("span", {
    className: "be"
  }, "$", (position.strike + position.price).toFixed(2))), /*#__PURE__*/React.createElement("div", {
    className: "pos-risk"
  }, /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("span", {
    className: "l"
  }, "MAX LOSS"), /*#__PURE__*/React.createElement("span", {
    className: "bear"
  }, "\u2212", d.fmtMoney(position.price * 100 * position.contracts).slice(1))), /*#__PURE__*/React.createElement("div", {
    className: "ralign"
  }, /*#__PURE__*/React.createElement("span", {
    className: "l"
  }, "MAX GAIN"), /*#__PURE__*/React.createElement("span", null, "unlimited"))), /*#__PURE__*/React.createElement("button", {
    className: "pos-close",
    onClick: onClose
  }, "CLOSE \xB7 REALIZE ", d.fmtMoney(upl, true))) : /*#__PURE__*/React.createElement("div", {
    className: "bp-empty"
  }, "No open position. Click a strike \u2192 BUY to open.")), /*#__PURE__*/React.createElement("section", {
    className: "bp scrub"
  }, /*#__PURE__*/React.createElement("div", {
    className: "bp-head"
  }, /*#__PURE__*/React.createElement("span", {
    className: "k"
  }, "THETA SCRUBBER"), /*#__PURE__*/React.createElement("span", {
    className: "r amber"
  }, "SIMULATE DECAY \u2192")), /*#__PURE__*/React.createElement("div", {
    className: "scrub-body"
  }, /*#__PURE__*/React.createElement("div", {
    className: "scrub-ends"
  }, /*#__PURE__*/React.createElement("span", null, "ENTRY"), /*#__PURE__*/React.createElement("span", null, "EXP \xB7 DTE 0")), /*#__PURE__*/React.createElement("input", {
    type: "range",
    min: "0",
    max: "1",
    step: "0.01",
    value: scrubT,
    disabled: !position,
    onChange: e => setScrubT(parseFloat(e.target.value)),
    className: "td-slider"
  }), /*#__PURE__*/React.createElement("div", {
    className: "scrub-foot"
  }, /*#__PURE__*/React.createElement("span", {
    className: "decay"
  }, "DECAY ", /*#__PURE__*/React.createElement("span", {
    className: "bar"
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      width: (scrubT * 100).toFixed(0) + "%"
    }
  })), " ", (scrubT * 100).toFixed(0), "%"), /*#__PURE__*/React.createElement("button", {
    className: "reset",
    onClick: () => setScrubT(0),
    disabled: !position || scrubT === 0
  }, "reset")), /*#__PURE__*/React.createElement("span", {
    className: "hint"
  }, "BEs widen toward expiry as theta burns."))), /*#__PURE__*/React.createElement("section", {
    className: "bp levels"
  }, /*#__PURE__*/React.createElement("div", {
    className: "bp-head"
  }, /*#__PURE__*/React.createElement("span", {
    className: "k"
  }, "KEY LEVELS"), /*#__PURE__*/React.createElement("span", {
    className: "r"
  }, "SPY")), /*#__PURE__*/React.createElement("div", {
    className: "lev-body"
  }, [["EM↑", "761.20"], ["EM↓", "756.10"], ["CW", "760"], ["PW", "755"], ["MP", "758"], ["GF", "757"]].map(([k, v]) => /*#__PURE__*/React.createElement("div", {
    className: "lev-row",
    key: k
  }, /*#__PURE__*/React.createElement("span", {
    className: "lk"
  }, k), /*#__PURE__*/React.createElement("span", {
    className: "lv"
  }, v))), /*#__PURE__*/React.createElement("div", {
    className: "lev-row ivr"
  }, /*#__PURE__*/React.createElement("span", {
    className: "lk"
  }, "IV RANK"), /*#__PURE__*/React.createElement("span", {
    className: "lv amber"
  }, "72")), /*#__PURE__*/React.createElement("div", {
    className: "lev-toggle"
  }, /*#__PURE__*/React.createElement("span", null, "SHOW ON CHART"), /*#__PURE__*/React.createElement("span", {
    className: "sw on"
  }, /*#__PURE__*/React.createElement("i", null))))), /*#__PURE__*/React.createElement("section", {
    className: "bp today"
  }, /*#__PURE__*/React.createElement("div", {
    className: "bp-head"
  }, /*#__PURE__*/React.createElement("span", {
    className: "k"
  }, "TODAY"), /*#__PURE__*/React.createElement("span", {
    className: "r"
  }, position ? d.fmtMoney(upl, true) : "$0.00")), /*#__PURE__*/React.createElement("div", {
    className: "today-body"
  }, position ? /*#__PURE__*/React.createElement("div", {
    className: "today-row"
  }, /*#__PURE__*/React.createElement("span", {
    className: "tt"
  }, "09:30"), /*#__PURE__*/React.createElement("span", {
    className: "td-side"
  }, "Long ", position.side), /*#__PURE__*/React.createElement("span", {
    className: "ts"
  }, "SPY"), /*#__PURE__*/React.createElement("span", {
    className: "to"
  }, "\u2014 \xB7 open")) : /*#__PURE__*/React.createElement("div", {
    className: "bp-empty"
  }, "No fills today."), /*#__PURE__*/React.createElement("div", {
    className: "today-foot"
  }, "VIEW FULL JOURNAL \u2192"))));
}
window.TDBottom = BottomRow;
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/terminal/BottomRow.jsx", error: String((e && e.message) || e) }); }

// ui_kits/terminal/Chart.jsx
try { (() => {
/* Annotated candlestick chart with the signature magenta breakeven line
   that walks as theta decays. Canvas-based for crisp hairlines. */
function TDChart({
  candles,
  position,
  scrubT,
  timeframe
}) {
  const canvasRef = React.useRef(null);
  const wrapRef = React.useRef(null);
  React.useEffect(() => {
    const canvas = canvasRef.current;
    const wrap = wrapRef.current;
    if (!canvas || !wrap) return;
    const draw = () => {
      const dpr = window.devicePixelRatio || 1;
      const W = wrap.clientWidth;
      const H = wrap.clientHeight;
      canvas.width = W * dpr;
      canvas.height = H * dpr;
      canvas.style.width = W + "px";
      canvas.style.height = H + "px";
      const ctx = canvas.getContext("2d");
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, W, H);
      const css = getComputedStyle(document.documentElement);
      const C = {
        grid: css.getPropertyValue("--td-border").trim(),
        bull: css.getPropertyValue("--td-bullish").trim(),
        bear: css.getPropertyValue("--td-bearish").trim(),
        pos: css.getPropertyValue("--td-position").trim(),
        fg2: css.getPropertyValue("--td-fg-tertiary-2").trim(),
        fg3: css.getPropertyValue("--td-fg-tertiary").trim(),
        panel: css.getPropertyValue("--td-bg-1").trim()
      };
      const padR = 56; // price axis gutter
      const plotW = W - padR;
      const volH = H * 0.16;
      const plotH = H - volH - 8;
      let hi = -Infinity,
        lo = Infinity,
        vmax = 0;
      candles.forEach(d => {
        hi = Math.max(hi, d.h);
        lo = Math.min(lo, d.l);
        vmax = Math.max(vmax, d.v);
      });

      // Fold position breakevens into the visible range so the magenta
      // BE line is always on-screen (positions sit near the money).
      let beTodayVals = [],
        beExpiryVals = [],
        beLabelSide = "Long call";
      if (position) {
        const premium = position.price ?? position.premium ?? 0;
        const side = position.side || "call";
        beLabelSide = side === "straddle" ? "Long straddle" : side === "put" ? "Long put" : "Long call";
        const walk = 0.18 + 0.82 * scrubT;
        if (side === "straddle") {
          beExpiryVals = [position.strike - premium, position.strike + premium];
          beTodayVals = [position.strike - premium * walk, position.strike + premium * walk];
        } else if (side === "put") {
          beExpiryVals = [position.strike - premium];
          beTodayVals = [position.strike - premium * walk];
        } else {
          beExpiryVals = [position.strike + premium];
          beTodayVals = [position.strike + premium * walk];
        }
        [...beExpiryVals, ...beTodayVals, position.strike].forEach(v => {
          hi = Math.max(hi, v);
          lo = Math.min(lo, v);
        });
      }
      const pad = (hi - lo) * 0.08;
      hi += pad;
      lo -= pad;
      const yOf = p => (hi - p) / (hi - lo) * plotH;
      const n = candles.length;
      const step = plotW / n;
      const cw = Math.max(1.5, step * 0.62);

      // horizontal price gridlines + labels
      ctx.font = "10px 'IBM Plex Mono', monospace";
      ctx.textBaseline = "middle";
      const gridStep = 1; // $1
      const startG = Math.ceil(lo);
      ctx.strokeStyle = C.grid;
      ctx.lineWidth = 1;
      for (let p = startG; p <= hi; p += gridStep) {
        if (p % 1 !== 0) continue;
        const y = yOf(p);
        if (p % 1 === 0 && p % 1 < 0.001) {
          ctx.globalAlpha = 0.35;
          ctx.beginPath();
          ctx.moveTo(0, y + 0.5);
          ctx.lineTo(plotW, y + 0.5);
          ctx.stroke();
          ctx.globalAlpha = 1;
        }
        ctx.fillStyle = C.fg3;
        ctx.textAlign = "left";
        ctx.fillText(p.toFixed(2), plotW + 6, y);
      }

      // volume bars
      candles.forEach((d, i) => {
        const x = i * step + step / 2;
        const up = d.c >= d.o;
        const bh = d.v / vmax * (volH - 4);
        ctx.fillStyle = up ? C.bull : C.bear;
        ctx.globalAlpha = 0.5;
        ctx.fillRect(x - cw / 2, H - bh, cw, bh);
        ctx.globalAlpha = 1;
      });

      // candles
      candles.forEach((d, i) => {
        const x = i * step + step / 2;
        const up = d.c >= d.o;
        const col = up ? C.bull : C.bear;
        ctx.strokeStyle = col;
        ctx.fillStyle = col;
        ctx.lineWidth = 1;
        // wick
        ctx.beginPath();
        ctx.moveTo(Math.round(x) + 0.5, yOf(d.h));
        ctx.lineTo(Math.round(x) + 0.5, yOf(d.l));
        ctx.stroke();
        // body
        const yo = yOf(d.o),
          yc = yOf(d.c);
        const top = Math.min(yo, yc);
        const bh = Math.max(1, Math.abs(yc - yo));
        ctx.fillRect(x - cw / 2, top, cw, bh);
      });

      // last price tag
      const last = candles[n - 1].c;
      const ly = yOf(last);
      ctx.fillStyle = C.bull;
      ctx.fillRect(plotW, ly - 8, padR, 16);
      ctx.fillStyle = "#0c0f16";
      ctx.font = "500 10px 'IBM Plex Mono', monospace";
      ctx.textAlign = "center";
      ctx.fillText(last.toFixed(2), plotW + padR / 2, ly);

      // ---- POSITION OVERLAY (the differentiator) ----
      if (position) {
        const {
          entryIndex
        } = position;
        const ex = entryIndex * step + step / 2;
        const ey = yOf(candles[entryIndex].l) + 18;

        // faint expiry-BE ghost line(s) — where the BE is walking toward
        ctx.strokeStyle = C.pos;
        ctx.lineWidth = 1;
        beExpiryVals.forEach(be => {
          const gy = yOf(be);
          ctx.globalAlpha = 0.28;
          ctx.setLineDash([2, 4]);
          ctx.beginPath();
          ctx.moveTo(0, gy + 0.5);
          ctx.lineTo(plotW, gy + 0.5);
          ctx.stroke();
        });
        ctx.setLineDash([]);
        ctx.globalAlpha = 1;

        // today BE line(s) — magenta dashed, walk with the scrubber
        ctx.font = "500 10px 'IBM Plex Mono', monospace";
        beTodayVals.forEach((be, idx) => {
          const by = yOf(be);
          ctx.strokeStyle = C.pos;
          ctx.lineWidth = 1.5;
          ctx.setLineDash([5, 4]);
          ctx.beginPath();
          ctx.moveTo(0, by + 0.5);
          ctx.lineTo(plotW, by + 0.5);
          ctx.stroke();
          ctx.setLineDash([]);
          const beLabel = "BE $" + be.toFixed(2);
          const lw = ctx.measureText(beLabel).width + 12;
          ctx.fillStyle = C.pos;
          ctx.fillRect(plotW - lw, by - 8, lw, 16);
          ctx.fillStyle = "#fff";
          ctx.textAlign = "center";
          ctx.fillText(beLabel, plotW - lw / 2, by);
        });

        // entry triangle marker
        ctx.fillStyle = C.pos;
        ctx.beginPath();
        ctx.moveTo(ex, ey - 6);
        ctx.lineTo(ex - 5, ey + 3);
        ctx.lineTo(ex + 5, ey + 3);
        ctx.closePath();
        ctx.fill();
        ctx.font = "10px 'IBM Plex Mono', monospace";
        ctx.fillStyle = C.pos;
        ctx.textAlign = "left";
        ctx.fillText("ENTRY · " + beLabelSide, ex + 9, ey + 1);
      }
    };
    draw();
    const ro = new ResizeObserver(draw);
    ro.observe(wrap);
    return () => ro.disconnect();
  }, [candles, position, scrubT, timeframe]);
  return /*#__PURE__*/React.createElement("div", {
    ref: wrapRef,
    style: {
      position: "absolute",
      inset: 0
    }
  }, /*#__PURE__*/React.createElement("canvas", {
    ref: canvasRef
  }));
}
window.TDChart = TDChart;
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/terminal/Chart.jsx", error: String((e && e.message) || e) }); }

// ui_kits/terminal/Panels.jsx
try { (() => {
/* Terminal chrome — Rail, Header, ChainPanel, TradeTicket, BottomRow.
   Self-contained (attached to window) so the kit runs without the DS
   bundle; visuals mirror the design-system primitives 1:1. */

const ICONS = {
  chart: /*#__PURE__*/React.createElement("g", null, /*#__PURE__*/React.createElement("line", {
    x1: "6",
    y1: "3",
    x2: "6",
    y2: "17"
  }), /*#__PURE__*/React.createElement("rect", {
    x: "4",
    y: "6",
    width: "4",
    height: "7",
    fill: "currentColor"
  }), /*#__PURE__*/React.createElement("line", {
    x1: "14",
    y1: "3",
    x2: "14",
    y2: "17"
  }), /*#__PURE__*/React.createElement("rect", {
    x: "12",
    y: "8",
    width: "4",
    height: "5"
  })),
  journal: /*#__PURE__*/React.createElement("g", null, /*#__PURE__*/React.createElement("path", {
    d: "M4 4h9a2 2 0 0 1 2 2v11H6a2 2 0 0 1-2-2V4z"
  }), /*#__PURE__*/React.createElement("line", {
    x1: "7",
    y1: "8",
    x2: "12",
    y2: "8"
  }), /*#__PURE__*/React.createElement("line", {
    x1: "7",
    y1: "11",
    x2: "12",
    y2: "11"
  }), /*#__PURE__*/React.createElement("line", {
    x1: "7",
    y1: "14",
    x2: "10",
    y2: "14"
  })),
  analytics: /*#__PURE__*/React.createElement("g", null, /*#__PURE__*/React.createElement("line", {
    x1: "3",
    y1: "17",
    x2: "17",
    y2: "17"
  }), /*#__PURE__*/React.createElement("rect", {
    x: "4",
    y: "11",
    width: "3",
    height: "6"
  }), /*#__PURE__*/React.createElement("rect", {
    x: "9",
    y: "7",
    width: "3",
    height: "10"
  }), /*#__PURE__*/React.createElement("rect", {
    x: "14",
    y: "4",
    width: "3",
    height: "13"
  })),
  watchlist: /*#__PURE__*/React.createElement("g", null, /*#__PURE__*/React.createElement("circle", {
    cx: "4.5",
    cy: "5.5",
    r: "1",
    fill: "currentColor",
    stroke: "none"
  }), /*#__PURE__*/React.createElement("line", {
    x1: "8",
    y1: "5.5",
    x2: "17",
    y2: "5.5"
  }), /*#__PURE__*/React.createElement("circle", {
    cx: "4.5",
    cy: "10",
    r: "1",
    fill: "currentColor",
    stroke: "none"
  }), /*#__PURE__*/React.createElement("line", {
    x1: "8",
    y1: "10",
    x2: "17",
    y2: "10"
  }), /*#__PURE__*/React.createElement("circle", {
    cx: "4.5",
    cy: "14.5",
    r: "1",
    fill: "currentColor",
    stroke: "none"
  }), /*#__PURE__*/React.createElement("line", {
    x1: "8",
    y1: "14.5",
    x2: "17",
    y2: "14.5"
  })),
  settings: /*#__PURE__*/React.createElement("g", null, /*#__PURE__*/React.createElement("circle", {
    cx: "10",
    cy: "10",
    r: "2.5"
  }), /*#__PURE__*/React.createElement("path", {
    d: "M10 2.5v2M10 15.5v2M2.5 10h2M15.5 10h2M4.7 4.7l1.4 1.4M13.9 13.9l1.4 1.4M4.7 15.3l1.4-1.4M13.9 6.1l1.4-1.4"
  }))
};
function Glyph({
  name,
  size = 20
}) {
  return /*#__PURE__*/React.createElement("svg", {
    width: size,
    height: size,
    viewBox: "0 0 20 20",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 1.5,
    strokeLinecap: "round",
    strokeLinejoin: "round"
  }, ICONS[name]);
}
function Rail({
  active,
  onNav
}) {
  const items = [["chart", "Chart"], ["journal", "Journal"], ["analytics", "Analytics"], ["watchlist", "Watch"]];
  return /*#__PURE__*/React.createElement("nav", {
    className: "td-rail"
  }, /*#__PURE__*/React.createElement("div", {
    className: "td-rail-mark"
  }, /*#__PURE__*/React.createElement("svg", {
    viewBox: "0 0 36 36",
    width: "32",
    height: "32"
  }, /*#__PURE__*/React.createElement("rect", {
    x: "1",
    y: "1",
    width: "34",
    height: "34",
    rx: "5",
    ry: "5",
    fill: "none",
    stroke: "var(--td-amber)",
    strokeWidth: "2"
  }), /*#__PURE__*/React.createElement("text", {
    x: "18",
    y: "18",
    textAnchor: "middle",
    dominantBaseline: "central",
    fontFamily: "var(--td-font-mono)",
    fontSize: "20",
    fontWeight: "500",
    letterSpacing: "-0.02em",
    fill: "var(--td-fg-primary)"
  }, "TD"))), items.map(([key, label]) => /*#__PURE__*/React.createElement("button", {
    key: key,
    className: "td-rail-btn" + (active === key ? " active" : ""),
    onClick: () => onNav(key),
    title: label
  }, /*#__PURE__*/React.createElement(Glyph, {
    name: key
  }), /*#__PURE__*/React.createElement("span", null, label))), /*#__PURE__*/React.createElement("button", {
    className: "td-rail-btn td-rail-foot",
    title: "Settings"
  }, /*#__PURE__*/React.createElement(Glyph, {
    name: "settings"
  }), /*#__PURE__*/React.createElement("span", null, "Settings")));
}
function Header({
  position,
  upl
}) {
  const d = window.TD;
  const detail = d.CANDLES[d.CANDLES.length - 1];
  const prev = d.CANDLES[0].o;
  const chg = detail.c - prev;
  const chgPct = chg / prev * 100;
  const bal = 50000 + (upl || 0);
  const pills = [{
    label: "BAL",
    value: d.fmtMoney(bal)
  }, {
    label: "MLL",
    value: d.fmtMoney(48000)
  }, {
    label: "DLL",
    value: "$0 / $1,500"
  }, {
    label: "RP&L",
    value: d.fmtMoney(0),
    tone: "default"
  }, {
    label: "UP&L",
    value: d.fmtMoney(upl || 0, true),
    signed: upl || 0
  }];
  return /*#__PURE__*/React.createElement("header", {
    className: "td-header"
  }, /*#__PURE__*/React.createElement("button", {
    className: "td-tier"
  }, "50K Combine ", /*#__PURE__*/React.createElement("span", {
    className: "caret"
  }, "\u25BE")), /*#__PURE__*/React.createElement("div", {
    className: "td-search"
  }, /*#__PURE__*/React.createElement("span", {
    className: "mag"
  }, "\u2315"), /*#__PURE__*/React.createElement("span", {
    className: "sym"
  }, "SPY"), /*#__PURE__*/React.createElement("span", {
    className: "ph"
  }, "\xB7 search ticker\u2026")), /*#__PURE__*/React.createElement("div", {
    className: "td-price"
  }, /*#__PURE__*/React.createElement("span", {
    className: "lbl"
  }, "SPY"), /*#__PURE__*/React.createElement("span", {
    className: "val"
  }, d.fmtMoney(detail.c)), /*#__PURE__*/React.createElement("span", {
    className: chg >= 0 ? "bull" : "bear"
  }, chg >= 0 ? "+" : "−", Math.abs(chg).toFixed(2), " (", d.fmtPct(chgPct), ")")), /*#__PURE__*/React.createElement("div", {
    className: "td-pills"
  }, pills.map(p => {
    const tone = p.signed !== undefined ? p.signed > 0 ? "bull" : p.signed < 0 ? "bear" : "" : "";
    return /*#__PURE__*/React.createElement("div", {
      className: "td-pill",
      key: p.label
    }, /*#__PURE__*/React.createElement("span", {
      className: "lbl"
    }, p.label), /*#__PURE__*/React.createElement("span", {
      className: "val " + tone
    }, p.value));
  }), /*#__PURE__*/React.createElement("div", {
    className: "td-pill mkt"
  }, /*#__PURE__*/React.createElement("span", {
    className: "lbl"
  }, "MKT"), /*#__PURE__*/React.createElement("span", {
    className: "val bear"
  }, "CLOSED ", /*#__PURE__*/React.createElement("span", {
    className: "sep"
  }, "\xB7"), /*#__PURE__*/React.createElement("span", {
    className: "lc"
  }, "until 09:30 et")))));
}
function ChainPanel({
  chain,
  action,
  onPick
}) {
  const rowsRef = React.useRef(null);
  React.useEffect(() => {
    const el = rowsRef.current;
    if (!el) return;
    const atm = el.querySelector(".td-row.atm");
    if (atm) el.scrollTop = atm.offsetTop - el.clientHeight / 2 + atm.clientHeight / 2;
  }, []);
  return /*#__PURE__*/React.createElement("div", {
    className: "td-chain"
  }, /*#__PURE__*/React.createElement("div", {
    className: "td-chain-head"
  }, /*#__PURE__*/React.createElement("span", {
    className: "k"
  }, "OPTION CHAIN"), /*#__PURE__*/React.createElement("span", {
    className: "v"
  }, "SPY"), /*#__PURE__*/React.createElement("span", {
    className: "t"
  }, "0DTE \xB7 exp ", chain.expiry), /*#__PURE__*/React.createElement("span", {
    className: "t"
  }, "SPOT $", chain.spot.toFixed(2)), /*#__PURE__*/React.createElement("span", {
    className: "t"
  }, "ATM $", chain.atm), /*#__PURE__*/React.createElement("span", {
    className: "t"
  }, "IV ", (chain.iv * 100).toFixed(0), "%"), /*#__PURE__*/React.createElement("span", {
    className: "tag"
  }, "indicative pricing")), /*#__PURE__*/React.createElement("div", {
    className: "td-chain-col"
  }, /*#__PURE__*/React.createElement("span", null, "Call"), /*#__PURE__*/React.createElement("span", null, "Strike"), /*#__PURE__*/React.createElement("span", null, "Put")), /*#__PURE__*/React.createElement("div", {
    className: "td-chain-rows",
    ref: rowsRef
  }, chain.rows.map(r => /*#__PURE__*/React.createElement("div", {
    key: r.strike,
    className: "td-row" + (r.isAtm ? " atm" : "")
  }, /*#__PURE__*/React.createElement("button", {
    className: "cell r " + (r.callSource === "bs" ? "dim" : ""),
    onClick: () => onPick({
      strike: r.strike,
      side: "call",
      price: r.call
    })
  }, r.call.toFixed(2), r.callSource === "bs" && /*#__PURE__*/React.createElement("span", {
    className: "m"
  }, "\xB7m")), /*#__PURE__*/React.createElement("button", {
    className: "strike" + (r.isAtm ? " atm" : ""),
    onClick: () => onPick({
      strike: r.strike,
      side: r.isAtm ? "straddle" : "call",
      price: r.isAtm ? +(r.call + r.put).toFixed(2) : r.call
    })
  }, r.strike), /*#__PURE__*/React.createElement("button", {
    className: "cell l " + (r.putSource === "bs" ? "dim" : ""),
    onClick: () => onPick({
      strike: r.strike,
      side: "put",
      price: r.put
    })
  }, r.put.toFixed(2), r.putSource === "bs" && /*#__PURE__*/React.createElement("span", {
    className: "m"
  }, "\xB7m"))))));
}
function TradeTicket({
  selection,
  qty,
  setQty,
  onFire,
  marketOpen
}) {
  const presets = [1, 3, 5, 10, 15];
  const cost = selection ? selection.price * 100 * qty : 0;
  const kind = selection ? selection.side === "straddle" ? "STRADDLE" : selection.side.toUpperCase() : "";
  const be = selection ? selection.side === "put" ? selection.strike - selection.price : selection.strike + selection.price : 0;
  return /*#__PURE__*/React.createElement("div", {
    className: "td-ticket"
  }, /*#__PURE__*/React.createElement("div", {
    className: "td-ticket-head"
  }, /*#__PURE__*/React.createElement("span", {
    className: "k"
  }, "TRADE TICKET"), /*#__PURE__*/React.createElement("span", {
    className: "hint"
  }, "selected from chain \u2191")), selection ? /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement("div", {
    className: "td-ticket-sum"
  }, /*#__PURE__*/React.createElement("span", {
    className: "big"
  }, selection.strike, " ", kind), /*#__PURE__*/React.createElement("span", {
    className: "u"
  }, "est."), /*#__PURE__*/React.createElement("span", {
    className: "s"
  }, window.TD.fmtMoney(cost), " debit"), /*#__PURE__*/React.createElement("span", {
    className: "u"
  }, "be"), /*#__PURE__*/React.createElement("span", {
    className: "be"
  }, "$", be.toFixed(2))), /*#__PURE__*/React.createElement("div", {
    className: "td-qty"
  }, /*#__PURE__*/React.createElement("div", {
    className: "stepper"
  }, /*#__PURE__*/React.createElement("button", {
    onClick: () => setQty(Math.max(1, qty - 1)),
    disabled: qty <= 1
  }, "\u2212"), /*#__PURE__*/React.createElement("div", {
    className: "val"
  }, qty), /*#__PURE__*/React.createElement("button", {
    onClick: () => setQty(qty + 1)
  }, "+")), /*#__PURE__*/React.createElement("div", {
    className: "chips"
  }, presets.map(n => /*#__PURE__*/React.createElement("button", {
    key: n,
    className: "chip" + (qty === n ? " on" : ""),
    onClick: () => setQty(n)
  }, n))))) : /*#__PURE__*/React.createElement("div", {
    className: "td-ticket-empty"
  }, marketOpen ? "Click a strike in the chain ↑" : "market closed"), /*#__PURE__*/React.createElement("div", {
    className: "td-actions"
  }, /*#__PURE__*/React.createElement("button", {
    className: "act buy" + (selection ? "" : " off"),
    onClick: () => selection && onFire("buy"),
    disabled: !selection
  }, /*#__PURE__*/React.createElement("span", {
    className: "l"
  }, "BUY +", selection ? qty : ""), /*#__PURE__*/React.createElement("span", {
    className: "sb"
  }, selection ? `long ${selection.side} · ${window.TD.fmtMoney(cost)} debit` : "pick a strike ↑")), /*#__PURE__*/React.createElement("button", {
    className: "act sell" + (selection ? "" : " off"),
    onClick: () => selection && onFire("sell"),
    disabled: !selection
  }, /*#__PURE__*/React.createElement("span", {
    className: "l"
  }, "SELL -", selection ? qty : ""), /*#__PURE__*/React.createElement("span", {
    className: "sb"
  }, selection ? `short ${selection.side} · ${window.TD.fmtMoney(cost)} credit` : "pick a strike ↑"))));
}
window.TDPanels = {
  Rail,
  Header,
  ChainPanel,
  TradeTicket,
  Glyph
};
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/terminal/Panels.jsx", error: String((e && e.message) || e) }); }

// ui_kits/terminal/data.js
try { (() => {
/* Trade Desk terminal — mock data + helpers (plain JS globals). */
(function () {
  // Deterministic PRNG so the chart is stable across renders.
  function mulberry32(a) {
    return function () {
      a |= 0;
      a = a + 0x6D2B79F5 | 0;
      let t = Math.imul(a ^ a >>> 15, 1 | a);
      t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t;
      return ((t ^ t >>> 14) >>> 0) / 4294967296;
    };
  }

  // Generate ~130 candles of SPY-ish 5m data drifting up into the 758–760 zone.
  function genCandles(n) {
    const rnd = mulberry32(424242);
    const out = [];
    let price = 750.4;
    for (let i = 0; i < n; i++) {
      const drift = 0.012 + Math.sin(i / 14) * 0.05;
      const vol = 0.22 + rnd() * 0.28;
      const o = price;
      const move = (rnd() - 0.48) * vol + drift * 0.5;
      let c = o + move;
      // a couple of impulse legs for character
      if (i === 28) c = o + 1.7;
      if (i === 96) c = o + 1.3;
      const hi = Math.max(o, c) + rnd() * vol * 0.9;
      const lo = Math.min(o, c) - rnd() * vol * 0.9;
      const v = 0.4 + rnd() * (i % 17 === 0 ? 2.4 : 1);
      out.push({
        o,
        h: hi,
        l: lo,
        c,
        v
      });
      price = c;
    }
    return out;
  }
  const CANDLES = genCandles(130);
  const SPOT = CANDLES[CANDLES.length - 1].c;

  // Option chain around ATM 759 (0DTE, indicative pricing).
  function genChain(spot) {
    const atm = Math.round(spot);
    const rows = [];
    for (let k = atm - 5; k <= atm + 5; k++) {
      // crude intrinsic + time-value model for a 0DTE feel
      const callIntrinsic = Math.max(0, spot - k);
      const putIntrinsic = Math.max(0, k - spot);
      const tv = Math.max(0.02, 0.9 - Math.abs(k - spot) * 0.16);
      const call = +(callIntrinsic + tv).toFixed(2);
      const put = +(putIntrinsic + tv).toFixed(2);
      const isAtm = k === atm;
      // strikes far OTM fall back to model pricing
      const far = Math.abs(k - spot) > 3;
      rows.push({
        strike: k,
        call: +Math.max(0.01, call).toFixed(2),
        put: +Math.max(0.01, put).toFixed(2),
        isAtm,
        callSource: far && k > spot ? "bs" : "quote",
        putSource: far && k < spot ? "bs" : "quote"
      });
    }
    return {
      rows,
      atm,
      spot,
      iv: 0.77,
      expiry: "2026-06-01"
    };
  }
  window.TD = {
    CANDLES,
    SPOT,
    CHAIN: genChain(SPOT),
    fmtMoney(v, signed) {
      if (!isFinite(v)) return "—";
      const s = signed ? v > 0 ? "+" : v < 0 ? "−" : "" : v < 0 ? "−" : "";
      return s + "$" + Math.abs(v).toLocaleString("en-US", {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2
      });
    },
    fmtPct(v) {
      const s = v > 0 ? "+" : v < 0 ? "−" : "";
      return s + Math.abs(v).toFixed(2) + "%";
    }
  };
})();
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/terminal/data.js", error: String((e && e.message) || e) }); }

__ds_ns.Badge = __ds_scope.Badge;

__ds_ns.Button = __ds_scope.Button;

__ds_ns.MetricPill = __ds_scope.MetricPill;

__ds_ns.TierPill = __ds_scope.TierPill;

__ds_ns.ChainRow = __ds_scope.ChainRow;

__ds_ns.Icon = __ds_scope.Icon;

__ds_ns.ActionButton = __ds_scope.ActionButton;

__ds_ns.PresetChips = __ds_scope.PresetChips;

__ds_ns.Stepper = __ds_scope.Stepper;

})();
