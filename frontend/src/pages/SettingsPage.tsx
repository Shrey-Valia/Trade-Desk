import { useEffect, useState } from "react";

import { PageHeader } from "@/components/layout/PageHeader";
import { UIButton } from "@/components/ui/UIButton";
import { Link, useNavigate } from "react-router-dom";

import { useAccountState } from "@/hooks/useAccountState";
import { useActivateCombine } from "@/hooks/useCombines";
import { useMe, useSignout } from "@/hooks/useAuth";
import { useZeroDteUniverse } from "@/hooks/useLiquidUniverse";
import { useChartPrefs } from "@/stores/chartPrefs";
import { APPEARANCE_DEFAULTS, useUserSettings } from "@/stores/userSettings";
import type { TierKey, TierSpec } from "@/types/account";
import { CHART_TIMEFRAMES, type ChartTimeframe } from "@/types/chart";

// Standard candle-interval ladder. Default selection "5m" matches the
// toolbar's cold-open. Picker and toolbar share CHART_TIMEFRAMES so
// the two stay in lockstep automatically.
const TIMEFRAMES: readonly ChartTimeframe[] = CHART_TIMEFRAMES;

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
          <AccountSection />
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

/** Who's signed in + the way out. Signout clears the query cache and
 * the route guard bounces to /signin. */
function AccountSection() {
  const me = useMe();
  const signout = useSignout();
  const navigate = useNavigate();
  return (
    <div className="border-b border-hairline px-3 py-3 flex items-center justify-between gap-3">
      <div className="min-w-0">
        <div
          className="uppercase tracking-label-up text-fg-secondary"
          style={{ fontSize: 9, letterSpacing: "0.08em" }}
        >
          Account
        </div>
        <div className="text-fg-primary mt-0.5 truncate" style={{ fontSize: 12 }}>
          {me.data?.display_name ? `${me.data.display_name} · ` : ""}
          {me.data?.email ?? "—"}
        </div>
      </div>
      <button
        type="button"
        disabled={signout.isPending}
        onClick={() =>
          signout.mutate(undefined, { onSuccess: () => navigate("/signin") })
        }
        className="h-7 px-3 text-tiny uppercase tracking-label-up border border-hairline text-fg-secondary hover:bg-tier-2 hover:text-fg-primary disabled:opacity-50 shrink-0"
        style={{ borderRadius: 0 }}
      >
        {signout.isPending ? "Signing out…" : "Sign out"}
      </button>
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
  const { data: account, isError, isLoading } = useAccountState();
  const activate = useActivateCombine();
  if (isLoading) {
    return (
      <div className="px-3 py-3 border-b border-hairline text-tiny text-fg-tertiary-2">
        Loading combine state…
      </div>
    );
  }
  if (isError || !account) {
    // Zero combines (fresh signup or all archived) — /state 404s.
    return (
      <div className="border-b border-hairline px-3 py-3 flex items-center justify-between gap-3">
        <div>
          <div
            className="uppercase tracking-label-up text-fg-secondary"
            style={{ fontSize: 9, letterSpacing: "0.08em" }}
          >
            Combines
          </div>
          <div className="text-fg-tertiary mt-0.5" style={{ fontSize: 11 }}>
            You don&rsquo;t own a combine yet — purchase one to unlock trading.
          </div>
        </div>
        <Link
          to="/combines/new"
          className="h-7 px-3 inline-flex items-center text-tiny uppercase tracking-label-up border border-amber text-amber bg-tier-1 hover:bg-tier-2 shrink-0"
          style={{ borderRadius: 0 }}
        >
          Start a combine
        </Link>
      </div>
    );
  }
  const combines = account.combines ?? [];
  return (
    <div className="border-b border-hairline">
      <div className="px-3 pt-3 pb-1 flex items-baseline justify-between">
        <div>
          <div
            className="uppercase tracking-label-up text-fg-secondary"
            style={{ fontSize: 9, letterSpacing: "0.08em" }}
          >
            Your combines
          </div>
          <div
            className="text-fg-tertiary mt-0.5"
            style={{ fontSize: 11, lineHeight: 1.35 }}
          >
            Each combine keeps its own balance, high-water mark, and trade
            history. The active one drives the terminal; manage (rename,
            archive) from the dashboard.
          </div>
        </div>
        <Link
          to="/combines/new"
          className="text-tiny uppercase tracking-label-up text-amber hover:underline shrink-0"
          style={{ fontSize: 10 }}
        >
          + new combine
        </Link>
      </div>
      <div className="grid grid-cols-3 gap-2 px-3 pb-3 pt-1">
        {combines
          .filter((c) => c.status !== "archived")
          .map((c) => {
            const active = c.id === account.combine_id;
            return (
              <button
                key={c.id}
                type="button"
                onClick={() => {
                  if (!active) activate.mutate(c.id);
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
                  {c.name}
                </span>
                <span className="text-fg-tertiary-2" style={{ fontSize: 10 }}>
                  {c.tier} · {c.account_code}
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
      <DailyLossLimitRow tiers={account.tiers} />
    </div>
  );
}

/**
 * Per-tier Daily Loss Limit override.
 *
 * Defaults come from the backend's TierSpec (Topstep-aligned 3% of
 * starting balance). User can override per tier within a 1-10% band of
 * the tier's starting balance. The DLL pill in the header reads the
 * override from userSettings; backend still emits dll_used/dll_budget
 * from its own defaults (display-only spec, no enforcement).
 */
function DailyLossLimitRow({ tiers }: { tiers: TierSpec[] }) {
  const overrides = useUserSettings((s) => s.dllOverrides);
  const setOverride = useUserSettings((s) => s.setDllOverride);
  return (
    <div className="border-b border-hairline">
      <div className="px-3 pt-3 pb-1">
        <div
          className="uppercase tracking-label-up text-fg-secondary"
          style={{ fontSize: 9, letterSpacing: "0.08em" }}
        >
          Daily loss limit
        </div>
        <div
          className="text-fg-tertiary mt-0.5"
          style={{ fontSize: 11, lineHeight: 1.35 }}
        >
          How much you can lose in one trading day before the DLL pill warns,
          then breaches. Resets at the next ET open. Display-only — trade
          opens are not blocked. Range: 1-10% of the tier's starting balance.
        </div>
      </div>
      <div className="grid grid-cols-3 gap-2 px-3 pb-3 pt-1">
        {tiers.map((t) => {
          const tierKey = t.key as TierKey;
          const override = overrides[tierKey];
          const value = override ?? t.dll_amount;
          const isDefault = override == null;
          const min = Math.round(t.starting_balance * 0.01);
          const max = Math.round(t.starting_balance * 0.10);
          return (
            <div
              key={t.key}
              className="flex flex-col gap-1 p-2 border border-hairline bg-tier-1"
              style={{ borderRadius: 0 }}
            >
              <span
                className="uppercase tracking-label-up text-fg-tertiary-2"
                style={{ fontSize: 10 }}
              >
                {t.key} DLL
              </span>
              <div className="flex items-center gap-1">
                <span className="text-fg-tertiary-2" style={{ fontSize: 11 }}>
                  $
                </span>
                <DllInput
                  tierKey={tierKey}
                  value={value}
                  min={min}
                  max={max}
                  onCommit={(n) => setOverride(tierKey, n)}
                />
                {!isDefault && (
                  <button
                    type="button"
                    onClick={() => setOverride(tierKey, null)}
                    className="text-fg-tertiary-2 hover:text-fg-secondary uppercase tracking-label-up"
                    style={{ fontSize: 9 }}
                    aria-label={`Reset ${t.key} DLL to default`}
                    title={`Reset to default ($${t.dll_amount.toLocaleString()})`}
                  >
                    reset
                  </button>
                )}
              </div>
              <span className="text-fg-tertiary-2" style={{ fontSize: 9 }}>
                {isDefault ? "default" : `default $${t.dll_amount.toLocaleString()}`}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

/** DLL override input — free typing, clamped commit.
 *
 * The store write happens on blur/Enter (not per keystroke) so typing
 * "1500" doesn't get clamped at the intermediate "1". Commits clamp to
 * the documented 1-10%-of-starting-balance band; garbage input reverts
 * to the last committed value. */
function DllInput({
  tierKey,
  value,
  min,
  max,
  onCommit,
}: {
  tierKey: TierKey;
  value: number;
  min: number;
  max: number;
  onCommit: (n: number) => void;
}) {
  const [text, setText] = useState(String(value));
  // Re-sync when the committed value changes underneath us (reset
  // button, tier defaults loading).
  useEffect(() => {
    setText(String(value));
  }, [value]);
  const commit = () => {
    const n = Number(text);
    if (!Number.isFinite(n) || text.trim() === "") {
      setText(String(value));
      return;
    }
    const clamped = Math.min(max, Math.max(min, Math.round(n)));
    setText(String(clamped));
    onCommit(clamped);
  };
  return (
    <input
      type="number"
      value={text}
      min={min}
      max={max}
      step={50}
      onChange={(e) => setText(e.target.value)}
      onBlur={commit}
      onKeyDown={(e) => {
        if (e.key === "Enter") (e.target as HTMLInputElement).blur();
      }}
      className="h-7 px-1.5 text-xs2 font-mono tabular-nums bg-tier-2 border border-tier-3 text-fg-primary rounded-btn"
      style={{ width: 80 }}
      aria-label={`${tierKey} daily loss limit`}
      title={`$${min.toLocaleString()} – $${max.toLocaleString()}`}
    />
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
  const resetAppearance = useUserSettings((s) => s.resetAppearance);
  const isDefault =
    bullishColor === APPEARANCE_DEFAULTS.bullishColor &&
    bearishColor === APPEARANCE_DEFAULTS.bearishColor &&
    bgGradient === APPEARANCE_DEFAULTS.bgGradient &&
    gridOpacity === APPEARANCE_DEFAULTS.gridOpacity;
  return (
    <div className="border-t border-hairline">
      <div className="px-3 pt-3 pb-1">
        <div className="flex items-baseline justify-between">
          <div
            className="uppercase tracking-label-up text-fg-secondary"
            style={{ fontSize: 10, letterSpacing: "0.08em" }}
          >
            Chart appearance
          </div>
          {!isDefault && (
            <button
              type="button"
              onClick={resetAppearance}
              className="text-fg-tertiary-2 hover:text-fg-secondary uppercase tracking-label-up"
              style={{ fontSize: 9 }}
              title="Restore the default candle colors, gradient, and grid opacity"
            >
              reset to defaults
            </button>
          )}
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
