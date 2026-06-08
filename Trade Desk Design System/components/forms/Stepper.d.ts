import React from "react";

/**
 * Stepper — −/value/+ quantity control.
 */
export interface StepperProps extends Omit<React.HTMLAttributes<HTMLDivElement>, "onChange"> {
  /** Current value. */
  value: number;
  /** Called with the next value. */
  onChange: (next: number) => void;
  /** Min (default 1) / max (default 999). */
  min?: number;
  max?: number;
}

export function Stepper(props: StepperProps): JSX.Element;
