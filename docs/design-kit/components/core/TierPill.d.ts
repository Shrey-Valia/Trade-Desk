import React from "react";

/**
 * TierPill — combine-tier indicator + switcher (50K / 100K / 150K).
 *
 * @startingPoint section="Core" subtitle="Combine tier switcher" viewport="700x100"
 */
export interface TierPillProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  /** Tier key, e.g. "50K". Default "50K". */
  tier?: string;
  /** Balance is below the trailing MLL — turns the pill bearish. */
  breached?: boolean;
}

export function TierPill(props: TierPillProps): JSX.Element;
