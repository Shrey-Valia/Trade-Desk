Large BUY / SELL ticket buttons. Use as the two-up action row at the bottom of a trade ticket.

```jsx
<div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
  <ActionButton intent="buy"  label="BUY +1"  sub="long call · $8.00 debit" />
  <ActionButton intent="sell" label="SELL -1" sub="short call · $8.00 credit" />
</div>
```

`intent` picks the green/red action fill (a distinct axis from P&L bullish/bearish). Pass `disabled` for the dimmed `market closed` / no-selection state.
