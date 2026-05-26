import { PageHeader } from "@/components/layout/PageHeader";
import { useZeroDteUniverse } from "@/hooks/useLiquidUniverse";
import { useChartPrefs } from "@/stores/chartPrefs";
import { useUserSettings } from "@/stores/userSettings";
import type { ChartTimeframe } from "@/types/chart";

const TIMEFRAMES: ChartTimeframe[] = ["1D", "5D", "1M", "3M"];

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
        </section>

        <p
          className="px-3 py-3 text-fg-tertiary border-t border-hairline"
          style={{ fontSize: 9 }}
        >
          Changes persist locally; no Save needed. Reload the page to apply
          settings that affect cold-open behavior (default ticker, timeframe).
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
    <div className="flex items-stretch border border-hairline">
      <button
        type="button"
        onClick={() => onChange(value - 1)}
        disabled={value <= min}
        className="h-7 w-7 text-xs2 text-fg-secondary hover:bg-tier-2 hover:text-fg-primary disabled:opacity-40"
        style={{ borderRadius: 0 }}
        aria-label="Decrease contract quantity"
      >
        −
      </button>
      <input
        type="number"
        value={value}
        min={min}
        max={max}
        onChange={(e) => onChange(Number(e.target.value) || min)}
        className="h-7 w-12 text-center font-mono tabular-nums bg-tier-1 border-l border-r border-hairline text-fg-primary"
        style={{ borderRadius: 0 }}
        aria-label="Contract quantity"
      />
      <button
        type="button"
        onClick={() => onChange(value + 1)}
        disabled={value >= max}
        className="h-7 w-7 text-xs2 text-fg-secondary hover:bg-tier-2 hover:text-fg-primary disabled:opacity-40"
        style={{ borderRadius: 0 }}
        aria-label="Increase contract quantity"
      >
        +
      </button>
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
    <button
      type="button"
      role="switch"
      aria-checked={on}
      onClick={onChange}
      className={[
        "h-7 px-3 text-xs2 uppercase tracking-label-up border",
        on
          ? "border-amber text-amber bg-tier-1"
          : "border-hairline text-fg-tertiary hover:bg-tier-2",
      ].join(" ")}
      style={{ borderRadius: 0, minWidth: 64 }}
    >
      {on ? "On" : "Off"}
    </button>
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
    <div className="flex gap-px">
      {TIMEFRAMES.map((tf) => {
        const active = tf === value;
        return (
          <button
            key={tf}
            type="button"
            onClick={() => onChange(tf)}
            className={[
              "h-7 px-2 text-xs2 border tabular-nums",
              active
                ? "border-amber text-amber bg-tier-1"
                : "border-hairline text-fg-tertiary hover:bg-tier-2",
            ].join(" ")}
            style={{ borderRadius: 0 }}
            aria-pressed={active}
          >
            {tf}
          </button>
        );
      })}
    </div>
  );
}
