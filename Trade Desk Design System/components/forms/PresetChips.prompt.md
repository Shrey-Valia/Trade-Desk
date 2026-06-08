Round one-tap quantity presets. Use beside a Stepper in the trade ticket.

```jsx
const [qty, setQty] = React.useState(1);
<PresetChips value={qty} onSelect={setQty} presets={[1,3,5,10,15]} />
```

Selected chip gets the amber border + amber text on the lifted fill.
