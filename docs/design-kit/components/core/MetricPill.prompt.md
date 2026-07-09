Labeled value box — the terminal's core "card". Use for header metrics and any label-over-value readout.

```jsx
<MetricPill label="BAL" value="$50,132.93" />
<MetricPill label="UP&L" value="+$132.93" signed={132.93} />
<MetricPill label="MLL" value="$48,000.00" tone="warning">
  <Badge tone="bearish">BREACH</Badge>
</MetricPill>
```

`signed` colors the value by sign (bullish/bearish); `tone` forces a color (`bullish`/`bearish`/`warning`/`amber`). Children render inline after the value (e.g. a Badge). Always tabular. ~110×44.
