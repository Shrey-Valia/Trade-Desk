import { Link } from "react-router-dom";

import { TradeDeskLogo } from "@/components/branding/TradeDeskLogo";
import { colors } from "@/lib/design";
import { monthlyPrice } from "@/lib/pricing";
import { profitTarget, TIER_SPECS } from "@/lib/tierSpecs";

/**
 * "/" for guests. The landing leads with the INSTRUMENT — a live-feeling
 * terminal preview of the corridor (your breakeven above, the trailing floor
 * rising below) — not a marketing splash. The funnel is continuous with the
 * app: CTA → /signup?next=/combines/new → simulated checkout → combine.
 *
 * Prices come from lib/pricing + lib/tierSpecs (the enforced numbers) so the
 * page can never advertise a rule the engine doesn't hold.
 */
const START_HREF = "/signup?next=%2Fcombines%2Fnew";

export function LandingPage() {
  return (
    <div className="min-h-screen bg-tier-0 text-fg-primary flex flex-col">
      <TopNav />
      <Hero />
      <SpecStrip />
      <Lifecycle />
      <TierPricing />
      <Capabilities />
      <BottomCta />
      <Footer />
    </div>
  );
}

function TopNav() {
  return (
    <header className="border-b border-hairline">
      <div
        className="mx-auto flex items-center justify-between gap-4 px-6"
        style={{ maxWidth: 1120, height: 56 }}
      >
        <div className="flex items-center gap-4">
          <TradeDeskLogo />
          <span className="hidden sm:inline text-tiny text-fg-tertiary-2" style={{ fontSize: 11 }}>
            0DTE options prop firm
          </span>
        </div>
        <nav className="flex items-center gap-1.5">
          <Link
            to="/signin"
            className="h-8 px-3 inline-flex items-center text-tiny uppercase tracking-label-up text-fg-secondary hover:text-fg-primary"
          >
            Sign in
          </Link>
          <Link
            to={START_HREF}
            className="h-8 px-3.5 inline-flex items-center text-tiny uppercase tracking-label-up border border-amber text-amber hover:bg-tier-1 font-medium"
            style={{ borderRadius: 3 }}
          >
            Start a combine
          </Link>
        </nav>
      </div>
    </header>
  );
}

function Hero() {
  return (
    <section className="border-b border-hairline">
      <div
        className="mx-auto grid gap-12 px-6 py-14 lg:py-20 items-center"
        style={{ maxWidth: 1120, gridTemplateColumns: "minmax(0, 1fr)" }}
      >
        <div className="grid gap-12 lg:gap-14 lg:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)] items-center">
          <div className="flex flex-col items-start gap-6">
            <h1
              className="font-display leading-[0.98]"
              style={{
                fontSize: "clamp(40px, 6vw, 72px)",
                fontWeight: 700,
                letterSpacing: "-0.03em",
              }}
            >
              Pass the combine.
              <br />
              <span
                style={{
                  backgroundImage:
                    "linear-gradient(180deg, #F1DCA0 0%, #D4A24C 52%, #A97C2E 100%)",
                  WebkitBackgroundClip: "text",
                  backgroundClip: "text",
                  color: "transparent",
                }}
              >
                Trade our capital.
              </span>
            </h1>
            <p
              className="text-fg-secondary leading-relaxed"
              style={{ fontSize: 15, maxWidth: 440 }}
            >
              Prove your edge on 0DTE options with simulated capital under real
              risk rails. Hit the profit target without breaching the trailing
              max-loss, and trade a funded account keeping up to 80%.
            </p>
            <div className="flex items-center gap-3 pt-1">
              <Link
                to={START_HREF}
                className="h-10 px-5 inline-flex items-center gap-2 uppercase tracking-label-up bg-amber text-tier-0 hover:bg-fg-primary font-medium"
                style={{ fontSize: 12, borderRadius: 3 }}
              >
                Start a combine
                <span aria-hidden>→</span>
              </Link>
              <Link
                to="/signin"
                className="h-10 px-4 inline-flex items-center uppercase tracking-label-up text-fg-secondary hover:text-fg-primary"
                style={{ fontSize: 12 }}
              >
                Sign in
              </Link>
            </div>
            <div className="flex items-center gap-2 text-fg-tertiary-2" style={{ fontSize: 11 }}>
              <span>Paper execution</span>
              <Dot />
              <span>Live market data</span>
              <Dot />
              <span>No card charged</span>
            </div>
          </div>

          <TerminalPreview />
        </div>
      </div>
    </section>
  );
}

function Dot() {
  return <span className="text-fg-disabled">·</span>;
}

/**
 * The instrument. A window on the corridor: candles trending up between the
 * BEAM-magenta breakeven descending from the top and the rising red trailing-
 * drawdown floor, with the live risk readout below. This is the product, not
 * a marketing graphic — so it uses the app's real tokens.
 */
function TerminalPreview() {
  return (
    <div
      className="border border-hairline-strong bg-tier-1 overflow-hidden"
      style={{ borderRadius: 6 }}
    >
      <div
        className="flex items-center gap-3 border-b border-hairline px-3"
        style={{ height: 34 }}
      >
        <span className="text-tiny font-medium" style={{ fontSize: 12 }}>
          SPY
        </span>
        <span className="text-tiny text-fg-secondary tabular-nums" style={{ fontSize: 12 }}>
          601.42
        </span>
        <span className="text-tiny text-bullish tabular-nums" style={{ fontSize: 11 }}>
          +0.38%
        </span>
        <span className="ml-auto flex items-center gap-1.5 text-fg-tertiary-2" style={{ fontSize: 10 }}>
          <span
            className="inline-block rounded-full"
            style={{ width: 6, height: 6, background: colors.bullish }}
          />
          100K · funded
        </span>
      </div>

      <div className="px-3 pt-3">
        <div className="flex items-center justify-between text-fg-tertiary-2" style={{ fontSize: 10 }}>
          <span className="uppercase tracking-label-up">SPY · 1m · the corridor</span>
          <span>
            <span style={{ color: colors.positionMagenta }}>breakeven</span>
            {"  ·  "}
            <span style={{ color: colors.bearish }}>drawdown floor</span>
          </span>
        </div>
        <CorridorChart />
      </div>

      <div className="grid grid-cols-[1.5fr_1fr_1fr] border-t border-hairline">
        <RiskCell
          label="Distance to failure"
          value="1,840"
          sub="61% clear"
          subColor={colors.bullish}
          gaugePct={61}
          gaugeColor={colors.bullish}
          wide
        />
        <RiskCell label="Target" value="38%" sub="3 of 5 days" gaugePct={38} gaugeColor={colors.accentAmber} />
        <RiskCell label="Day loss" value="14%" sub="used today" gaugePct={14} gaugeColor={colors.warning} />
      </div>
    </div>
  );
}

const CHART_W = 560;
const CHART_H = 168;

/**
 * The corridor — a clean, real-feeling chart telling one story: price rises
 * from just above the trailing-drawdown floor, up through the (nearly flat)
 * breakeven line, and into the shaded profit zone — while the red floor keeps
 * ratcheting up beneath it. Candles are deterministic (sin-based, no RNG) so
 * the render is stable. Profit zone shaded green above breakeven; danger zone
 * shaded red below the floor; the corridor between is where you trade.
 */
function CorridorChart() {
  const N = 22;
  const pad = 6;
  const inner = CHART_W - pad * 2;
  const stepX = inner / N;

  // Breakeven: a near-flat reference (a fixed price). Floor: rising left→right.
  const beL = 78;
  const beR = 72;
  const floorL = 156;
  const floorR = 118;

  // Close-price y per candle — a rising trend (y falls) with organic wiggle,
  // starting near the floor and finishing above breakeven in the profit zone.
  const closes: number[] = [];
  for (let i = 0; i < N; i++) {
    const t = i / (N - 1);
    const trend = 138 - t * 102; // 138 (near floor) → 36 (deep in profit)
    const wiggle = Math.sin(i * 0.82) * 5.5 + Math.sin(i * 1.9 + 1.3) * 3;
    closes.push(trend + wiggle);
  }

  return (
    <svg
      viewBox={`0 0 ${CHART_W} ${CHART_H}`}
      width="100%"
      height={CHART_H}
      role="img"
      aria-label="Price candles rising from just above a rising red drawdown floor, up through a flat magenta breakeven line into a shaded green profit zone."
      style={{ display: "block", marginTop: 4 }}
    >
      {/* profit zone (above breakeven) + danger zone (below the rising floor) */}
      <polygon points={`0,0 ${CHART_W},0 ${CHART_W},${beR} 0,${beL}`} fill={colors.bullish} opacity="0.05" />
      <polygon
        points={`0,${floorL} ${CHART_W},${floorR} ${CHART_W},${CHART_H} 0,${CHART_H}`}
        fill={colors.bearish}
        opacity="0.055"
      />

      {/* breakeven — your position, nearly flat; floor — trailing, rising */}
      <line x1="0" y1={beL} x2={CHART_W} y2={beR} stroke={colors.positionMagenta} strokeWidth="1.25" strokeDasharray="2 3" opacity="0.9" />
      <line x1="0" y1={floorL} x2={CHART_W} y2={floorR} stroke={colors.bearish} strokeWidth="1.25" opacity="0.55" />

      {/* candles */}
      {closes.map((close, i) => {
        const open = i === 0 ? close + 7 : closes[i - 1];
        const up = close <= open; // lower y = higher price
        const c = up ? colors.bullish : colors.bearish;
        const x = pad + i * stepX + stepX / 2;
        const bodyTop = Math.min(open, close);
        const bodyH = Math.max(2.5, Math.abs(open - close));
        const wickUp = 3 + (i % 3) * 1.6;
        const wickDown = 3 + ((i + 1) % 3) * 1.6;
        return (
          <g key={i}>
            <line x1={x} y1={bodyTop - wickUp} x2={x} y2={bodyTop + bodyH + wickDown} stroke={c} strokeWidth="1" opacity="0.9" />
            <rect x={x - 2.5} y={bodyTop} width="5" height={bodyH} fill={c} rx="0.5" />
          </g>
        );
      })}

      {/* right-edge price tags */}
      <g>
        <rect x={CHART_W - 54} y={beR - 7} width="52" height="14" rx="2" fill={colors.positionMagenta} opacity="0.16" />
        <text x={CHART_W - 28} y={beR + 3} textAnchor="middle" fontSize="9" fontFamily="monospace" fill={colors.positionMagenta}>
          600.10
        </text>
        <rect x={CHART_W - 54} y={floorR - 7} width="52" height="14" rx="2" fill={colors.bearish} opacity="0.14" />
        <text x={CHART_W - 28} y={floorR + 3} textAnchor="middle" fontSize="9" fontFamily="monospace" fill={colors.bearish}>
          598.16
        </text>
      </g>
    </svg>
  );
}

function RiskCell({
  label,
  value,
  sub,
  subColor,
  gaugePct,
  gaugeColor,
  wide,
}: {
  label: string;
  value: string;
  sub: string;
  subColor?: string;
  gaugePct: number;
  gaugeColor: string;
  wide?: boolean;
}) {
  return (
    <div className={`px-3 py-2.5 ${wide ? "" : "border-l border-hairline"}`}>
      <div className="uppercase tracking-label-up text-fg-tertiary-2" style={{ fontSize: 10 }}>
        {label}
      </div>
      <div
        className="font-display tabular-nums"
        style={{ fontSize: wide ? 24 : 18, fontWeight: 600, marginTop: 1, letterSpacing: "-0.01em" }}
      >
        {value}
      </div>
      <div className="mt-1.5 overflow-hidden" style={{ height: 5, borderRadius: 3, background: colors.bgTier2 }}>
        <div style={{ width: `${gaugePct}%`, height: "100%", background: gaugeColor }} />
      </div>
      <div className="mt-1 tabular-nums" style={{ fontSize: 10, color: subColor ?? colors.fgTertiary2 }}>
        {sub}
      </div>
    </div>
  );
}

/** The rules as a dense terminal spec line — not a marketing stat grid. */
function SpecStrip() {
  const specs = [
    ["Account", "$50K · $100K · $150K"],
    ["Max loss", "trails your high-water mark"],
    ["Daily loss", "resets 5pm PT"],
    ["Markets", "SPY · QQQ · IWM 0DTE"],
    ["Split", "up to 80% funded"],
  ];
  return (
    <section className="border-b border-hairline bg-tier-1">
      <div
        className="mx-auto flex flex-wrap items-center gap-x-8 gap-y-2 px-6 py-3.5"
        style={{ maxWidth: 1120 }}
      >
        {specs.map(([k, v]) => (
          <div key={k} className="flex items-baseline gap-2">
            <span className="uppercase tracking-label-up text-fg-tertiary-2" style={{ fontSize: 10 }}>
              {k}
            </span>
            <span className="text-tiny text-fg-secondary tabular-nums" style={{ fontSize: 12 }}>
              {v}
            </span>
          </div>
        ))}
      </div>
    </section>
  );
}

/** The account lifecycle — a real state machine, not a numbered 01/02/03 list. */
function Lifecycle() {
  const stages = [
    {
      tag: "Evaluation",
      body: "Buy a combine and trade 0DTE within the rules. The dashboard tracks your trailing floor, daily budget and target in real time.",
    },
    {
      tag: "Funded",
      body: "Hit the profit target over the minimum days without breaching a limit and the account funds automatically. Activate it to unlock payouts.",
    },
    {
      tag: "Payout",
      body: "Clear the winning-day and consistency requirements and withdraw your split — up to 80% of the profit on the funded account.",
    },
  ];
  return (
    <section className="border-b border-hairline">
      <div className="mx-auto px-6 py-14" style={{ maxWidth: 1120 }}>
        <div className="grid gap-x-8 gap-y-8 sm:grid-cols-3">
          {stages.map((s, i) => (
            <div key={s.tag} className="flex flex-col gap-2.5">
              <div className="flex items-center gap-2.5">
                <span
                  className="uppercase tracking-label-up text-amber"
                  style={{ fontSize: 12, letterSpacing: "0.06em" }}
                >
                  {s.tag}
                </span>
                {i < stages.length - 1 && (
                  <span className="hidden sm:inline text-fg-disabled">→</span>
                )}
              </div>
              <div className="h-px w-full bg-hairline" />
              <p className="text-tiny text-fg-tertiary leading-relaxed" style={{ maxWidth: 320 }}>
                {s.body}
              </p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

function TierPricing() {
  const usd = (n: number) => `$${n.toLocaleString("en-US")}`;
  const tiers = TIER_SPECS.map((t) => ({
    key: t.key,
    start: usd(t.starting_balance),
    target: usd(profitTarget(t.key)),
    trail: usd(t.trailing_distance),
    dll: usd(t.dll_amount),
    price: monthlyPrice(t.key, "activation", "50_50"),
  }));
  return (
    <section className="border-b border-hairline bg-tier-1" id="pricing">
      <div className="mx-auto px-6 py-14" style={{ maxWidth: 1120 }}>
        <div className="flex items-baseline justify-between flex-wrap gap-2 mb-8">
          <h2 className="font-display" style={{ fontSize: 26, fontWeight: 600, letterSpacing: "-0.02em" }}>
            Same engine at every size.
          </h2>
          <span className="text-tiny text-fg-tertiary-2">Only the numbers scale.</span>
        </div>
        <div className="grid gap-4 sm:grid-cols-3">
          {tiers.map((t) => (
            <div
              key={t.key}
              className="border border-hairline-strong bg-tier-0 flex flex-col"
              style={{ borderRadius: 5 }}
            >
              <div className="flex items-baseline justify-between px-4 pt-4 pb-3 border-b border-hairline">
                <span className="font-display" style={{ fontSize: 17, fontWeight: 600 }}>
                  {t.key}
                </span>
                <span className="tabular-nums">
                  <span className="text-fg-primary" style={{ fontSize: 15 }}>
                    ${t.price}
                  </span>
                  <span className="text-fg-tertiary-2" style={{ fontSize: 11 }}>
                    /mo
                  </span>
                </span>
              </div>
              <div className="px-4 py-3.5 flex flex-col gap-2 tabular-nums flex-1">
                <Spec label="Simulated capital" value={t.start} />
                <Spec label="Profit target" value={t.target} />
                <Spec label="Max loss limit" value={`trails ${t.trail}`} />
                <Spec label="Daily loss limit" value={t.dll} />
              </div>
              <div className="px-4 pb-4">
                <Link
                  to={START_HREF}
                  className="w-full h-9 inline-flex items-center justify-center uppercase tracking-label-up border border-amber text-amber hover:bg-amber hover:text-tier-0 font-medium transition-colors"
                  style={{ fontSize: 11, borderRadius: 3 }}
                >
                  Start {t.key}
                </Link>
              </div>
            </div>
          ))}
        </div>
        <p className="text-tiny text-fg-tertiary-2 mt-4" style={{ maxWidth: 620 }}>
          Choose the activation path (lower monthly, a one-time $149 fee when you
          fund) or no-activation (+$50/mo, $0 when funded), and an 80/20 or 50/50
          split, at checkout. Simulated paper evaluation — no card is charged.
        </p>
      </div>
    </section>
  );
}

function Spec({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline justify-between gap-3">
      <span className="uppercase tracking-label-up text-fg-tertiary-2" style={{ fontSize: 10 }}>
        {label}
      </span>
      <span className="text-tiny text-fg-secondary">{value}</span>
    </div>
  );
}

function Capabilities() {
  const rows = [
    {
      title: "Breakeven on the chart",
      body: "Your position's breakeven is painted on the price axis and walks in real time as theta decays — the corridor above, the trailing floor below.",
    },
    {
      title: "Risk rails you can see",
      body: "Distance-to-failure, daily-loss budget and target progress sit on the terminal itself. The engine enforces them — no surprise liquidations.",
    },
    {
      title: "A journal that grades you",
      body: "Every fill lands in the calendar journal with mistake tags, R-multiples and analytics that show whether you actually traded the plan.",
    },
  ];
  return (
    <section className="border-b border-hairline">
      <div className="mx-auto px-6 py-14" style={{ maxWidth: 1120 }}>
        <div className="grid divide-y divide-hairline sm:divide-y-0 sm:grid-cols-3 sm:gap-8">
          {rows.map((r) => (
            <div key={r.title} className="flex flex-col gap-2 py-4 sm:py-0">
              <span className="font-display" style={{ fontSize: 15, fontWeight: 600 }}>
                {r.title}
              </span>
              <span className="text-tiny text-fg-tertiary leading-relaxed" style={{ maxWidth: 320 }}>
                {r.body}
              </span>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

function BottomCta() {
  return (
    <section className="border-b border-hairline bg-tier-1">
      <div
        className="mx-auto flex flex-wrap items-center justify-between gap-5 px-6 py-12"
        style={{ maxWidth: 1120 }}
      >
        <h2 className="font-display" style={{ fontSize: 26, fontWeight: 600, letterSpacing: "-0.02em" }}>
          The bell rings at 9:30. Be ready.
        </h2>
        <Link
          to={START_HREF}
          className="h-11 px-6 inline-flex items-center gap-2 uppercase tracking-label-up bg-amber text-tier-0 hover:bg-fg-primary font-medium"
          style={{ fontSize: 12, borderRadius: 3 }}
        >
          Start a combine
          <span aria-hidden>→</span>
        </Link>
      </div>
    </section>
  );
}

function Footer() {
  return (
    <footer className="mt-auto">
      <div
        className="mx-auto flex items-center justify-between flex-wrap gap-3 px-6 py-6"
        style={{ maxWidth: 1120 }}
      >
        <TradeDeskLogo size="mini" />
        <span className="text-fg-tertiary-2" style={{ fontSize: 11, maxWidth: 620 }}>
          Simulated trading only. Trade Desk combines are evaluations on paper
          execution with live market data — not brokerage accounts, and not
          financial advice.
        </span>
      </div>
      <div className="border-t border-hairline">
        <nav
          aria-label="Legal"
          className="mx-auto flex items-center flex-wrap gap-x-5 gap-y-2 px-6 py-4"
          style={{ maxWidth: 1120 }}
        >
          {[
            { to: "/terms", label: "Terms of Service" },
            { to: "/privacy", label: "Privacy Policy" },
            { to: "/refund-policy", label: "Refund Policy" },
            { to: "/risk-disclosure", label: "Risk Disclosure" },
          ].map((l) => (
            <Link
              key={l.to}
              to={l.to}
              className="uppercase tracking-label-up text-fg-tertiary-2 hover:text-amber"
              style={{ fontSize: 11 }}
            >
              {l.label}
            </Link>
          ))}
        </nav>
      </div>
    </footer>
  );
}
