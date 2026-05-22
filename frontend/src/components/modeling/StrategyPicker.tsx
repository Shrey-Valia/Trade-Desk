import { STRATEGY_TYPES, type StrategyType } from "@/types/bs";

interface Props {
  value: StrategyType;
  onChange: (s: StrategyType) => void;
}

/**
 * Strategy picker — hairline-bordered select on BG TIER 1, no rounded
 * corners. Native `<select>` styling on macOS/Chrome resists deeper amber
 * highlights on the popup options without `-webkit-appearance: none` + a
 * full custom dropdown reimplementation; we accept the native popup look
 * and only style the closed state. DESIGN.md acknowledges this limitation.
 */
export function StrategyPicker({ value, onChange }: Props) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value as StrategyType)}
      className="text-tiny border border-hairline bg-tier-1 text-fg-primary px-1.5 py-0.5 hover:border-fg-secondary focus:border-fg-secondary"
      style={{ borderRadius: 0 }}
    >
      {STRATEGY_TYPES.map((s) => (
        <option key={s.value} value={s.value}>
          {s.label}
        </option>
      ))}
    </select>
  );
}
