−/value/+ quantity stepper. Use for contract count in a trade ticket.

```jsx
const [qty, setQty] = React.useState(1);
<Stepper value={qty} onChange={setQty} min={1} />
```

Square 32px buttons with a 60px value box. Pair with `PresetChips` for one-tap quantities.
