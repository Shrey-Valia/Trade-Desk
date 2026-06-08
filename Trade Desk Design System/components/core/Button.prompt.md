Monospace button with terminal chrome — use for any clickable action in a Trade Desk surface.

```jsx
<Button variant="primary">CLOSE · REALIZE +$132.93</Button>
<Button variant="secondary" active>5m</Button>
<Button variant="ghost" size="sm">reset</Button>
<Button variant="danger">BREACH — flatten</Button>
```

Variants: `primary` (amber CTA), `secondary` (default, hairline; pass `active` to turn amber — used for timeframe toggles), `ghost` (chromeless), `danger` (bearish). Sizes `sm`/`md`/`lg`. Pass `disabled` for the dimmed `tier-1` state.
