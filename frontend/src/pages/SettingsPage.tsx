import { useState } from "react";

import { PageHeader } from "@/components/layout/PageHeader";
import { UIButton } from "@/components/ui/UIButton";
import { useAccountState, useSwitchTier } from "@/hooks/useAccountState";
import { useZeroDteUniverse } from "@/hooks/useLiquidUniverse";
import { useChartPrefs } from "@/stores/chartPrefs";
import { useUserSettings } from "@/stores/userSettings";
import type { TierSpec } from "@/types/account";
import type { ChartTimeframe } from "@/types/chart";

// 1D is intentionally excluded — the backend's 1D bars (today's minute
// bars) return 404 outside market hours; the toolbar dropped it for
// the same reason. Settings stays in lockstep so a stale default
// doesn't cold-open into a 404 over the weekend.
const TIMEFRAMES: ChartTimeframe[] = ["5D", "1M", "3M"];

/**
 * Settings — four persisted preferences that affect how the app opens.
 *
 *   1. Default ticker          (used by PositionsPage cold-open)
 *   2. Default contract qty    (used by chain-cell + straddle opens)
 *   3. Market-structure annotations on by default (chartPrefs)
 *   4. Default chart timeframe (used by PositionsPage initial state)
 *
 * Each row is one preference + its control + a one-line explanation,
 * separated by hairlines per DESIGN.md. No clutter, no Save button —
 * changes persist immediately to localStorage.
 */
export function SettingsPage() {
  const defaultTicker = useUserSettings((s) => s.defaultTicker);
  const setDefaultTicker = useUserSettings((s) => s.setDefaultTicker);
  const defaultContracts = useUserSettings((s) => s.defaultContracts);
  const setDefaultContracts = useUserSettings((s) => s.setDefaultContracts);
  const defaultTimeframe = useUserSettings((s) => s.defaultTimeframe);
  const setDefaultTimeframe = useUserSettings((s) => s.setDefaultTimeframe);
  const showAnnotations = useChartPrefs((s) => s.showMarketAnnotations);
  const toggleAnnotations = useChartPrefs((s) => s.toggleMarketAnnotations);

  const { data: universeData } = useZeroDteUniverse();
  const universe = universeData?.symbols ?? [];

  return (
    <div className="flex flex-col h-full min-h-0 bg-tier-0">
      <PageHeader title="Settings" />
      <main className="flex-1 min-h-0 overflow-y-auto border-t border-hairline">
        <section className="max-w-2xl">
          <CombineTierSection />
          <SettingRow
            label="Default ticker"
            help="The symbol the chart loads on cold open. Restricted to the 0DTE-eligible allowlist."
          >
            <TickerPicker
              value={defaultTicker}
              options={universe}
              onChange={setDefaultTicker}
            />
          </SettingRow>

          <SettingRow
            label="Default contract quantity"
            help="Fill size for new 0DTE opens (chain click and + BUY/SELL STRADDLE)."
          >
            <NumberStepper
              value={defaultContracts}
              min={1}
              max={100}
              onChange={setDefaultContracts}
            />
          </SettingRow>

          <SettingRow
            label="Market-structure annotations on by default"
            help="EM±, walls, max pain, gamma flip on the chart. The legend toggle still lets you flip them per session."
          >
            <Toggle on={showAnnotations} onChange={toggleAnnotations} />
          </SettingRow>

          <SettingRow
            label="Default chart timeframe"
            help="Timeframe selected when the chart first renders."
          >
            <TimeframePicker
              value={defaultTimeframe}
              onChange={setDefaultTimeframe}
            />
          </SettingRow>

          <ChartAppearanceSection />
        </section>

        <p
          className="px-3 py-3 text-fg-tertiary border-t border-hairline"
          style={{ fontSize: 9 }}
        >
          Most settings apply immediately. Default ticker and default timeframe
          take effect on next reload.
        </p>
      </main>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Row scaffold + atomic controls — pure DESIGN.md: hairlines, IBM Plex Mono,
// 0 border-radius, amber for active, no shadows.
// ---------------------------------------------------------------------------

function SettingRow({
  label,
  help,
  children,
}: {
  label: string;
  help: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex items-start gap-4 px-3 py-3 border-b border-hairline">
      <div className="flex-1 min-w-0">
        <div
          className="uppercase tracking-label-up text-fg-secondary"
          style={{ fontSize: 9, letterSpacing: "0.08em" }}
        >
          {label}
        </div>
        <div
          className="text-fg-tertiary mt-0.5"
          style={{ fontSize: 11, lineHeight: 1.35 }}
        >
          {help}
        </div>
      </div>
      <div className="shrink-0">{children}</div>
    </div>
  );
}

/**
 * Combine tier section — picks one of three industry-standard sizes.
 * Highlights the active tier with amber; switching opens a confirm
 * prompt so a stray click doesn't swap accounts.
 */
function CombineTierSection() {
  const { data: account, isLoading } = useAccountState();
  const switchTier = useSwitchTier();
  const [confirmTier, setConfirmTier] = useState<TierSpec | null>(null);
  if (isLoading || !account) {
    return (
      <div className="px-3 py-3 border-b border-hairline text-tiny text-fg-tertiary-2">
        Loading combine state…
      </div>
    );
  }
  const activeKey = account.active_tier;
  return (
    <div className="border-b border-hairline">
      <div className="px-3 pt-3 pb-1">
        <div
          className="uppercase tracking-label-up text-fg-secondary"
          style={{ fontSize: 9, letterSpacing: "0.08em" }}
        >
          Combine tier
        </div>
        <div
          className="text-fg-tertiary mt-0.5"
          style={{ fontSize: 11, lineHeight: 1.35 }}
        >
          Pick a prop-firm-style combine. Each tier keeps its own balance,
          high-water mark, and trade history. Switching saves progress on the
          tier you're leaving.
        </div>
      </div>
      <div className="grid grid-cols-3 gap-2 px-3 pb-3 pt-1">
        {account.tiers.map((t) => {
          const active = t.key === activeKey;
          return (
            <button
              key={t.key}
              type="button"
              onClick={() => {
                if (!active) setConfirmTier(t);
              }}
              className={[
                "flex flex-col items-start gap-1 p-2 border text-left tabular-nums",
                active
                  ? "border-amber bg-tier-2"
                  : "border-hairline bg-tier-1 hover:bg-tier-2",
              ].join(" ")}
              style={{ borderRadius: 0 }}
              aria-pressed={active}
            >
              <span
                className={[
                  "uppercase tracking-label-up font-medium",
                  active ? "text-amber" : "text-fg-primary",
                ].join(" ")}
                style={{ fontSize: 11 }}
              >
                {t.key} Combine
              </span>
              <span className="text-fg-secondary" style={{ fontSize: 11 }}>
                Start ${t.starting_balance.toLocaleString()}
              </span>
              <span className="text-fg-tertiary-2" style={{ fontSize: 10 }}>
                Trail ${t.trailing_distance.toLocaleString()} · MLL $
                {t.initial_mll.toLocaleString()}
              </span>
              {active && (
                <span
                  className="mt-0.5 uppercase tracking-label-up text-amber"
                  style={{ fontSize: 9 }}
                >
                  active
                </span>
              )}
            </button>
          );
        })}
      </div>
      {confirmTier && (
        <ConfirmSwitch
          target={confirmTier}
          pending={switchTier.isPending}
          onCancel={() => setConfirmTier(null)}
          onConfirm={() => {
            switchTier.mutate(confirmTier.key, {
              onSettled: () => setConfirmTier(null),
            });
          }}
        />
      )}
    </div>
  );
}

function ConfirmSwitch({
  target,
  pending,
  onCancel,
  onConfirm,
}: {
  target: TierSpec;
  pending: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  return (
    <div
      role="dialog"
      aria-modal="true"
      className="fixed inset-0 z-40 flex items-center justify-center bg-tier-0/80"
      onClick={onCancel}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        className="border border-hairline-strong bg-tier-1 px-4 py-3 max-w-md"
        style={{ borderRadius: 0 }}
      >
        <div
          className="uppercase tracking-label-up text-fg-secondary"
          style={{ fontSize: 9 }}
        >
          Switch combine?
        </div>
        <div className="text-fg-primary mt-1" style={{ fontSize: 13 }}>
          Switch to the {target.key} combine?
        </div>
        <div className="text-fg-tertiary-2 mt-1" style={{ fontSize: 11 }}>
          Your current tier's progress is saved automatically. Each tier keeps
          its own trade history and high-water mark.
        </div>
        <div className="flex gap-2 mt-3 justify-end">
          <UIButton
            size="sm"
            variant="ghost"
            onClick={onCancel}
            className="uppercase tracking-label-up"
          >
            Cancel
          </UIButton>
          <UIButton
            size="sm"
            active
            onClick={onConfirm}
            disabled={pending}
            className="uppercase tracking-label-up"
          >
            {pending ? "Switching…" : `Switch to ${target.key}`}
          </UIButton>
        </div>
      </div>
    </div>
  );
}

function TickerPicker({
  value,
  options,
  onChange,
}: {
  value: string;
  options: string[];
  onChange: (s: string) => void;
}) {
  // When the allowlist is loaded, render a real <select>. If it hasn't
  // loaded yet, fall back to a plain text input so the user can still
  // edit and persist before the API answers.
  if (options.length === 0) {
    return (
      <input
        type="text"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        spellCheck={false}
        autoComplete="off"
        className="h-7 px-2 text-xs2 font-mono uppercase tracking-wide bg-tier-1 border border-hairline text-fg-primary"
        style={{ borderRadius: 0, width: 96 }}
        aria-label="Default ticker"
      />
    );
  }
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className="h-7 px-2 text-xs2 font-mono uppercase tracking-wide bg-tier-1 border border-hairline text-fg-primary"
      style={{ borderRadius: 0, width: 96 }}
      aria-label="Default ticker"
    >
      {options.includes(value) ? null : (
        <option value={value}>{value} (off-list)</option>
      )}
      {options.map((sym) => (
        <option key={sym} value={sym}>
          {sym}
        </option>
      ))}
    </select>
  );
}

function NumberStepper({
  value,
  min,
  max,
  onChange,
}: {
  value: number;
  min: number;
  max: number;
  onChange: (n: number) => void;
}) {
  return (
    <div className="flex items-center" style={{ gap: 4 }}>
      <UIButton
        size="sm"
        onClick={() => onChange(value - 1)}
        disabled={value <= min}
        className="w-[28px] px-0"
        aria-label="Decrease contract quantity"
      >
        −
      </UIButton>
      <input
        type="number"
        value={value}
        min={min}
        max={max}
        onChange={(e) => onChange(Number(e.target.value) || min)}
        className="h-[26px] w-[48px] text-center font-mono tabular-nums bg-tier-2 border border-tier-3 text-fg-primary rounded-btn"
        aria-label="Contract quantity"
      />
      <UIButton
        size="sm"
        onClick={() => onChange(value + 1)}
        disabled={value >= max}
        className="w-[28px] px-0"
        aria-label="Increase contract quantity"
      >
        +
      </UIButton>
    </div>
  );
}

function Toggle({
  on,
  onChange,
}: {
  on: boolean;
  onChange: () => void;
}) {
  return (
    <UIButton
      role="switch"
      aria-checked={on}
      onClick={onChange}
      active={on}
      size="sm"
      className="uppercase tracking-label-up min-w-[64px]"
    >
      {on ? "On" : "Off"}
    </UIButton>
  );
}

function TimeframePicker({
  value,
  onChange,
}: {
  value: ChartTimeframe;
  onChange: (tf: ChartTimeframe) => void;
}) {
  return (
    <div className="flex" style={{ gap: 4 }}>
      {TIMEFRAMES.map((tf) => (
        <UIButton
          key={tf}
          size="sm"
          active={tf === value}
          onClick={() => onChange(tf)}
          aria-pressed={tf === value}
          className="min-w-[44px]"
        >
          {tf}
        </UIButton>
      ))}
    </div>
  );
}

/**
 * Chart Appearance — visual rework adds four customizable knobs.
 * Each persists to userSettings and applies live (the chart subscribes
 * to bullishColor/bearishColor/gridOpacity directly; bgGradient is
 * routed via App.tsx → html[data-bg-gradient]).
 */
function ChartAppearanceSection() {
  const bullishColor = useUserSettings((s) => s.bullishColor);
  const setBullishColor = useUserSettings((s) => s.setBullishColor);
  const bearishColor = useUserSettings((s) => s.bearishColor);
  const setBearishColor = useUserSettings((s) => s.setBearishColor);
  const bgGradient = useUserSettings((s) => s.bgGradient);
  const setBgGradient = useUserSettings((s) => s.setBgGradient);
  const gridOpacity = useUserSettings((s) => s.gridOpacity);
  const setGridOpacity = useUserSettings((s) => s.setGridOpacity);
  return (
    <div className="border-t border-hairline">
      <div className="px-3 pt-3 pb-1">
        <div
          className="uppercase tracking-label-up text-fg-secondary"
          style={{ fontSize: 10, letterSpacing: "0.08em" }}
        >
          Chart appearance
        </div>
        <div
          className="text-fg-tertiary mt-0.5"
          style={{ fontSize: 11, lineHeight: 1.35 }}
        >
          Customize the candle palette, grid density, and background. All
          changes apply live and persist locally.
        </div>
      </div>
      <SettingRow label="Bullish candle color" help="Color used for up candles + volume bars on up bars.">
        <ColorSwatch value={bullishColor} onChange={setBullishColor} />
      </SettingRow>
      <SettingRow label="Bearish candle color" help="Color used for down candles + volume bars on down bars.">
        <ColorSwatch value={bearishColor} onChange={setBearishColor} />
      </SettingRow>
      <SettingRow
        label="Background gradient"
        help="Soft radial gradient behind the dashboard. Turn off for a flat fill."
      >
        <Toggle on={bgGradient} onChange={() => setBgGradient(!bgGradient)} />
      </SettingRow>
      <SettingRow
        label="Chart grid line opacity"
        help="0% hides the grid entirely; the default 30% reads as a faint reference."
      >
        <OpacitySlider value={gridOpacity} onChange={setGridOpacity} />
      </SettingRow>
    </div>
  );
}

function ColorSwatch({
  value,
  onChange,
}: {
  value: string;
  onChange: (hex: string) => void;
}) {
  return (
    <label className="inline-flex items-center gap-2 cursor-pointer">
      <span
        aria-hidden
        className="rounded-btn border border-tier-3"
        style={{ width: 32, height: 32, background: value }}
      />
      <input
        type="color"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="sr-only"
        aria-label="Color"
      />
      <span
        className="text-fg-tertiary-2 tabular-nums uppercase"
        style={{ fontSize: 11 }}
      >
        {value}
      </span>
    </label>
  );
}

function OpacitySlider({
  value,
  onChange,
}: {
  value: number;
  onChange: (n: number) => void;
}) {
  return (
    <div className="flex items-center gap-2" style={{ width: 200 }}>
      <input
        type="range"
        min={0}
        max={100}
        step={5}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="flex-1 accent-amber"
        aria-label="Grid opacity"
      />
      <span
        className="text-fg-secondary tabular-nums"
        style={{ fontSize: 12, minWidth: 36, textAlign: "right" }}
      >
        {value}%
      </span>
    </div>
  );
}
