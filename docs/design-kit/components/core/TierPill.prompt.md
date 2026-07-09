Combine-tier indicator + switcher — the leftmost element in the terminal header.

```jsx
<TierPill tier="50K" onClick={openMenu} />
<TierPill tier="150K" breached onClick={openMenu} />
```

Shows `{tier} COMBINE ▾`. Pass `breached` when balance is below the trailing MLL (turns bearish). It's a static trigger — render your own dropdown menu on click.
