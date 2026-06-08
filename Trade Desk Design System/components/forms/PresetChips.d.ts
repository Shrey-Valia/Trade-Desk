import React from "react";

/**
 * PresetChips — round quantity presets (1 / 3 / 5 / 10 / 15).
 */
export interface PresetChipsProps extends React.HTMLAttributes<HTMLDivElement> {
  /** Preset values. Default [1,3,5,10,15]. */
  presets?: number[];
  /** Currently selected preset. */
  value: number;
  /** Called with the chosen preset. */
  onSelect: (n: number) => void;
}

export function PresetChips(props: PresetChipsProps): JSX.Element;
