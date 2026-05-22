const pctFormatter = new Intl.NumberFormat("en-US", {
  style: "percent",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
  signDisplay: "exceptZero",
});

const moneyFormatter = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

const signedMoneyFormatter = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
  signDisplay: "exceptZero",
});

const compactFormatter = new Intl.NumberFormat("en-US", {
  notation: "compact",
  maximumFractionDigits: 1,
});

export const formatPercent = (pct: number): string => pctFormatter.format(pct / 100);

export const formatPrice = (price: number): string => moneyFormatter.format(price);

export const formatChangeDollar = (delta: number): string =>
  signedMoneyFormatter.format(delta);

export const formatVolume = (volume: number): string => compactFormatter.format(volume);

/**
 * Today's volume over 20-day average, in the inline `32.4M / 28.1M` form
 * used by the Bloomberg-style price header (Row A) starting in commit 7.
 * The ratio is read at a glance — same units on both sides, slash conveys
 * the comparison without needing a separate "Avg" cell.
 */
export const formatVolumeRatio = (today: number, avg: number): string =>
  `${formatVolume(today)} / ${formatVolume(avg)}`;

export const formatRange = (low: number, high: number): string =>
  `${formatPrice(low)} – ${formatPrice(high)}`;
