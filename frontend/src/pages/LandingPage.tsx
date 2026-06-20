import { Link } from "react-router-dom";

import { TradeDeskLogo } from "@/components/branding/TradeDeskLogo";
import { monthlyPrice } from "@/lib/pricing";

/**
 * "/" for guests — the marketing landing page.
 *
 * Same design system as the app (tier backgrounds, hairlines, amber
 * accents, mono type) so the funnel feels continuous: CTA →
 * /signup?next=/combines/new → simulated checkout → combine.
 *
 * Prices come from lib/pricing.ts (the real matrix, mirrored from the
 * backend). Trade Desk is a paper prop firm — the checkout is simulated.
 */
export function LandingPage() {
  return (
    <div className="min-h-screen bg-tier-0 text-fg-primary flex flex-col">
      <TopNav />
      <Hero />
      <RulesBand />
      <TierPricing />
      <HowItWorks />
      <FeatureBand />
      <BottomCta />
      <Footer />
    </div>
  );
}

const START_HREF = "/signup?next=%2Fcombines%2Fnew";

function TopNav() {
  return (
    <header className="border-b border-hairline bg-tier-1">
      <div
        className="mx-auto flex items-center justify-between px-6"
        style={{ maxWidth: 1080, height: 56 }}
      >
        <TradeDeskLogo />
        <nav className="flex items-center gap-3">
          <Link
            to="/signin"
            className="h-8 px-3 inline-flex items-center text-tiny uppercase tracking-label-up text-fg-secondary hover:text-fg-primary"
          >
            Sign in
          </Link>
          <Link
            to={START_HREF}
            className="h-8 px-3 inline-flex items-center text-tiny uppercase tracking-label-up border border-amber text-amber bg-tier-2 hover:bg-tier-3 font-medium rounded-btn"
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
        className="mx-auto px-6 py-16 flex flex-col items-start gap-5"
        style={{ maxWidth: 1080 }}
      >
        <span
          className="uppercase tracking-label-up text-amber border border-amber px-2 py-0.5"
          style={{ fontSize: 12, borderRadius: 2 }}
        >
          0DTE options · funded evaluation
        </span>
        <h1
          className="font-medium leading-tight"
          style={{ fontSize: 40, maxWidth: 720 }}
        >
          Prove you can trade 0DTE options.
          <br />
          <span className="text-fg-secondary">
            Get funded when you do.
          </span>
        </h1>
        <p className="text-fg-tertiary leading-relaxed" style={{ fontSize: 14, maxWidth: 560 }}>
          Trade SPY, QQQ and IWM same-day options in a simulated combine with
          real market data, hard risk rails, and a terminal built for the
          breakeven math — chain to ticket to live position overlay in two
          clicks. Hit the profit target without breaking the rules and keep
          up to 80% of the upside on a funded account.
        </p>
        <div className="flex items-center gap-3">
          <Link
            to={START_HREF}
            className="h-10 px-5 inline-flex items-center uppercase tracking-label-up bg-action-buy hover:bg-action-buy-hover text-white font-semibold rounded-btn"
            style={{ fontSize: 13 }}
          >
            Start a Trading Combine →
          </Link>
          <Link
            to="/signin"
            className="h-10 px-4 inline-flex items-center uppercase tracking-label-up border border-hairline-strong text-fg-secondary hover:text-fg-primary hover:bg-tier-1 rounded-btn"
            style={{ fontSize: 12 }}
          >
            I have an account
          </Link>
        </div>
        <span className="text-tiny text-fg-tertiary-2">
          Paper execution on live market data. No real-money brokerage account
          required.
        </span>
      </div>
    </section>
  );
}

/** The rules ARE the product — show them like the terminal does. */
function RulesBand() {
  const items = [
    { label: "Account sizes", value: "$50K / $100K / $150K" },
    { label: "Max loss limit", value: "trails your high-water mark" },
    { label: "Daily loss limit", value: "resets every ET session" },
    { label: "Profit split", value: "up to 80% once funded" },
  ];
  return (
    <section className="border-b border-hairline bg-tier-1">
      <div
        className="mx-auto px-6 py-4 grid gap-4"
        style={{ maxWidth: 1080, gridTemplateColumns: "repeat(4, 1fr)" }}
      >
        {items.map((it) => (
          <div key={it.label} className="flex flex-col gap-0.5">
            <span
              className="uppercase tracking-label-up text-fg-tertiary-2"
              style={{ fontSize: 11, letterSpacing: "0.08em" }}
            >
              {it.label}
            </span>
            <span className="text-tiny text-fg-primary tabular-nums">{it.value}</span>
          </div>
        ))}
      </div>
    </section>
  );
}

function TierPricing() {
  const tiers = [
    {
      key: "50K",
      start: "$50,000",
      target: "$3,000",
      trail: "$2,000",
      dll: "$1,500",
      highlight: false,
    },
    {
      key: "100K",
      start: "$100,000",
      target: "$6,000",
      trail: "$4,000",
      dll: "$3,000",
      highlight: true,
    },
    {
      key: "150K",
      start: "$150,000",
      target: "$9,000",
      trail: "$4,500",
      dll: "$4,500",
      highlight: false,
    },
  ];
  return (
    <section className="border-b border-hairline" id="pricing">
      <div className="mx-auto px-6 py-12" style={{ maxWidth: 1080 }}>
        <SectionHead
          kicker="Pricing"
          title="Pick your combine."
          sub="Same rules engine at every size — only the numbers scale."
        />
        <div
          className="grid gap-4 mt-8"
          style={{ gridTemplateColumns: "repeat(3, 1fr)" }}
        >
          {tiers.map((t) => (
            <div
              key={t.key}
              className={[
                "border bg-tier-1 flex flex-col",
                t.highlight ? "border-amber" : "border-hairline-strong",
              ].join(" ")}
              style={{ borderRadius: 4 }}
            >
              {t.highlight && (
                <div
                  className="text-center uppercase tracking-label-up text-amber border-b border-amber py-1"
                  style={{ fontSize: 11 }}
                >
                  Most popular
                </div>
              )}
              <div className="px-4 pt-4 pb-3 border-b border-hairline">
                <div className="text-medium font-medium">{t.key} Combine</div>
                <div className="flex items-baseline gap-1 mt-1">
                  <span className="text-tiny text-fg-tertiary-2">from</span>
                  <span className="text-display font-medium text-amber tabular-nums">
                    ${monthlyPrice(t.key, "activation", "50_50")}
                  </span>
                  <span className="text-tiny text-fg-tertiary-2">/ month</span>
                </div>
              </div>
              <div className="px-4 py-3 flex flex-col gap-1.5 tabular-nums flex-1">
                <LandingSpec label="Simulated capital" value={t.start} />
                <LandingSpec label="Profit target" value={t.target} />
                <LandingSpec label="Max loss limit" value={`trails ${t.trail}`} />
                <LandingSpec label="Daily loss limit" value={t.dll} />
                <LandingSpec label="Markets" value="SPY · QQQ · IWM 0DTE" />
              </div>
              <div className="px-4 pb-4">
                <Link
                  to={START_HREF}
                  className={[
                    "w-full h-9 inline-flex items-center justify-center uppercase tracking-label-up font-medium rounded-btn",
                    t.highlight
                      ? "bg-action-buy hover:bg-action-buy-hover text-white"
                      : "border border-amber text-amber bg-tier-2 hover:bg-tier-3",
                  ].join(" ")}
                  style={{ fontSize: 11 }}
                >
                  Start {t.key}
                </Link>
              </div>
            </div>
          ))}
        </div>
        <p className="text-tiny text-fg-tertiary-2 mt-3">
          Choose the activation path (lower monthly + a one-time $149 fee when
          you get funded) or no-activation (+$50/mo, $0 when funded), and an
          80/20 or 50/50 profit split, at checkout. Simulated paper evaluation
          — no card is charged.
        </p>
      </div>
    </section>
  );
}

function LandingSpec({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline justify-between">
      <span
        className="uppercase tracking-label-up text-fg-tertiary-2"
        style={{ fontSize: 11 }}
      >
        {label}
      </span>
      <span className="text-tiny text-fg-secondary">{value}</span>
    </div>
  );
}

function HowItWorks() {
  const steps = [
    {
      n: "01",
      title: "Buy a combine",
      body: "Pick an account size. Your evaluation account provisions instantly with its own balance, loss limits, and profit target.",
    },
    {
      n: "02",
      title: "Trade within the rules",
      body: "0DTE chains, one-click straddles, live breakevens on the chart. The dashboard tracks every rule in real time — no surprises.",
    },
    {
      n: "03",
      title: "Get funded",
      body: "Hit the profit target without breaching a limit and move to a funded account keeping up to 80% of the profit.",
    },
  ];
  return (
    <section className="border-b border-hairline bg-tier-1">
      <div className="mx-auto px-6 py-12" style={{ maxWidth: 1080 }}>
        <SectionHead kicker="How it works" title="Three steps to funded." />
        <div
          className="grid gap-6 mt-8"
          style={{ gridTemplateColumns: "repeat(3, 1fr)" }}
        >
          {steps.map((s) => (
            <div key={s.n} className="flex flex-col gap-2">
              <span className="text-display font-medium text-amber tabular-nums">
                {s.n}
              </span>
              <span className="text-medium font-medium">{s.title}</span>
              <span className="text-tiny text-fg-tertiary leading-relaxed">
                {s.body}
              </span>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

function FeatureBand() {
  const features = [
    {
      title: "A terminal built for 0DTE",
      body: "Bloomberg-dense option chain, two-click straddles, theta scrubber, and breakeven lines drawn on the chart that drift as time decays.",
    },
    {
      title: "Risk rails you can see",
      body: "Balance, trailing max-loss and daily-loss limits live in the header of every screen. The same numbers drive the dashboard objectives.",
    },
    {
      title: "A journal that grades discipline",
      body: "Every fill lands in the calendar journal with mistake tags, R-multiples, and analytics that show whether you're trading the plan.",
    },
  ];
  return (
    <section className="border-b border-hairline">
      <div className="mx-auto px-6 py-12" style={{ maxWidth: 1080 }}>
        <SectionHead
          kicker="The desk"
          title="Everything a 0DTE trader actually uses."
        />
        <div
          className="grid gap-4 mt-8"
          style={{ gridTemplateColumns: "repeat(3, 1fr)" }}
        >
          {features.map((f) => (
            <div
              key={f.title}
              className="border border-hairline-strong bg-tier-1 px-4 py-4 flex flex-col gap-2"
              style={{ borderRadius: 4 }}
            >
              <span className="text-body font-medium">{f.title}</span>
              <span className="text-tiny text-fg-tertiary leading-relaxed">
                {f.body}
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
        className="mx-auto px-6 py-12 flex flex-col items-center gap-4 text-center"
        style={{ maxWidth: 1080 }}
      >
        <h2 className="text-display font-medium">
          The market opens at 9:30. Be ready for it.
        </h2>
        <Link
          to={START_HREF}
          className="h-10 px-5 inline-flex items-center uppercase tracking-label-up bg-action-buy hover:bg-action-buy-hover text-white font-semibold rounded-btn"
          style={{ fontSize: 13 }}
        >
          Start a Trading Combine →
        </Link>
      </div>
    </section>
  );
}

function Footer() {
  return (
    <footer className="mt-auto">
      <div
        className="mx-auto px-6 py-6 flex items-center justify-between flex-wrap gap-3"
        style={{ maxWidth: 1080 }}
      >
        <TradeDeskLogo size="mini" />
        <span className="text-tiny text-fg-tertiary-2" style={{ fontSize: 12 }}>
          Simulated trading only. Trade Desk combines are evaluations on paper
          execution with live market data — not brokerage accounts, and not
          financial advice.
        </span>
      </div>
    </footer>
  );
}

function SectionHead({
  kicker,
  title,
  sub,
}: {
  kicker: string;
  title: string;
  sub?: string;
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <span
        className="uppercase tracking-label-up text-amber"
        style={{ fontSize: 12, letterSpacing: "0.08em" }}
      >
        {kicker}
      </span>
      <h2 className="font-medium" style={{ fontSize: 24 }}>
        {title}
      </h2>
      {sub && <p className="text-tiny text-fg-tertiary">{sub}</p>}
    </div>
  );
}
