import { useState, type ReactNode } from "react";

import { ActionButton } from "@/components/ui/ActionButton";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { ChainRow } from "@/components/ui/ChainRow";
import { MetricPill } from "@/components/ui/MetricPill";
import { PresetChips } from "@/components/ui/PresetChips";
import { Stepper } from "@/components/ui/Stepper";
import { TierPill } from "@/components/ui/TierPill";

/**
 * Isolated preview harness for the shared UI primitive library
 * (design-system reconciliation, Step 2). NOT mounted in the live app
 * or its router — served standalone via /ui-preview.html so the
 * primitives can be eyeballed against the DS specimen cards.
 *
 * Every primitive is rendered with representative props and every state
 * variant. Interactive primitives (Stepper, PresetChips) hold local
 * state here; nothing reaches a data store or the network.
 */
export function UIHarness() {
  const [qty, setQty] = useState(3);
  const [qtyMin, setQtyMin] = useState(1);
  const [preset, setPreset] = useState(5);

  return (
    <div className="min-h-screen bg-tier-0 text-fg-primary font-mono px-6 py-6">
      <header className="mb-6">
        <h1 className="text-large font-medium">Trade Desk — UI Primitives</h1>
        <p className="text-tiny text-fg-tertiary-2 mt-1">
          Shared library preview · Tailwind-native · not wired into any screen.
        </p>
      </header>

      <Section title="Button" note="variant primary / secondary / ghost / danger · size sm 24 / md 32 / lg 40 · active · disabled">
        <Row label="variants (md)">
          <Button variant="primary">PRIMARY</Button>
          <Button variant="secondary">SECONDARY</Button>
          <Button variant="ghost">GHOST</Button>
          <Button variant="danger">DANGER</Button>
        </Row>
        <Row label="active">
          <Button variant="secondary" active>
            SECONDARY
          </Button>
          <Button variant="ghost" active>
            GHOST
          </Button>
        </Row>
        <Row label="disabled">
          <Button variant="primary" disabled>
            PRIMARY
          </Button>
          <Button variant="secondary" disabled>
            SECONDARY
          </Button>
          <Button variant="ghost" disabled>
            GHOST
          </Button>
          <Button variant="danger" disabled>
            DANGER
          </Button>
        </Row>
        <Row label="sizes">
          <Button size="sm">SM</Button>
          <Button size="md">MD</Button>
          <Button size="lg">LG</Button>
        </Row>
      </Section>

      <Section title="MetricPill" note="tier-2 + 1px tier-3 + 4px · ~110×44 · 10px label / 15px value · tone + signed + sub + children">
        <Row label="tones / signed">
          <MetricPill label="BAL" value="$50,132.93" />
          <MetricPill label="UP&L" value="+$132.93" signed={132.93} />
          <MetricPill label="UP&L" value="−$250.00" signed={-250} />
          <MetricPill label="RP&L" value="$0.00" signed={0} />
          <MetricPill label="MLL" value="$48,000" tone="warning" />
          <MetricPill label="TF" value="5m" tone="amber" />
        </Row>
        <Row label="sub + children (badge)">
          <MetricPill label="MKT" value="CLOSED" tone="bearish" sub="until 09:30 et" width={150} />
          <MetricPill label="MLL" value="$48,000" tone="bearish">
            <Badge tone="bearish">BREACH</Badge>
          </MetricPill>
          <MetricPill label="DLL" value="−$300 / $1,500" tone="bearish">
            <Badge tone="bearish">DLL HIT</Badge>
          </MetricPill>
        </Row>
      </Section>

      <Section title="Badge" note="16px · 2px radius · 9px uppercase · outlined">
        <Row label="tones">
          <Badge tone="bearish">BREACH</Badge>
          <Badge tone="warning">ER</Badge>
          <Badge tone="amber">ACTIVE</Badge>
          <Badge tone="bullish">WIN</Badge>
          <Badge tone="cyan">0DTE</Badge>
          <Badge tone="muted">MACRO</Badge>
        </Row>
      </Section>

      <Section title="TierPill" note='"{tier} Combine ▾" · 40px · bearish border when breached'>
        <Row label="states">
          <TierPill tier="50K" />
          <TierPill tier="100K" />
          <TierPill tier="150K" breached />
        </Row>
      </Section>

      <Section title="Stepper" note="−/value/+ · square 32px buttons · 60px value box · min/max">
        <Row label={`value = ${qty} (min 1, max 999)`}>
          <Stepper value={qty} onChange={setQty} />
        </Row>
        <Row label={`value = ${qtyMin} (min 1 — minus disabled at floor)`}>
          <Stepper value={qtyMin} onChange={setQtyMin} min={1} max={5} />
        </Row>
      </Section>

      <Section title="PresetChips" note="circular 32px · 1/3/5/10/15 · amber when selected">
        <Row label={`selected = ${preset}`}>
          <PresetChips value={preset} onSelect={setPreset} />
        </Row>
      </Section>

      <Section title="ActionButton" note="56px · action-buy/sell fills (NOT P&L colors) · 2-line · hover/press · disabled">
        <Row label="enabled">
          <div style={{ width: 180 }}>
            <ActionButton intent="buy" label="BUY +3" sub="long call · $24.00 debit" />
          </div>
          <div style={{ width: 180 }}>
            <ActionButton intent="sell" label="SELL -3" sub="short call · $24.00 credit" />
          </div>
        </Row>
        <Row label="disabled">
          <div style={{ width: 180 }}>
            <ActionButton intent="buy" label="BUY" sub="market closed" disabled />
          </div>
          <div style={{ width: 180 }}>
            <ActionButton intent="sell" label="SELL" sub="market closed" disabled />
          </div>
        </Row>
      </Section>

      <Section title="ChainRow" note="CALL │ STRIKE │ PUT (84/64/84) · 18px · ATM amber · ·m model marker">
        <div className="border border-hairline bg-tier-0 inline-flex flex-col" style={{ width: 84 + 64 + 84 }}>
          <ChainRow strike={748} call={11.2} put={0.62} />
          <ChainRow strike={749} call={9.85} put={0.94} />
          <ChainRow strike={750} call={8.0} put={1.55} isAtm />
          <ChainRow strike={751} call={5.4} put={2.7} />
          <ChainRow strike={752} call={3.1} put={4.85} callSource="bs" />
          <ChainRow strike={753} call={1.2} put={7.0} callSource="bs" putSource="bs" />
          <ChainRow strike={754} call={0.0} put={9.4} disabled />
        </div>
      </Section>

      <footer className="mt-8 pt-4 border-t border-hairline text-tiny text-fg-tertiary-2">
        Icon set is covered by the existing components/layout/RailIcons — not duplicated here.
      </footer>
    </div>
  );
}

function Section({
  title,
  note,
  children,
}: {
  title: string;
  note?: string;
  children: ReactNode;
}) {
  return (
    <section className="mb-7">
      <div className="flex items-baseline gap-3 mb-2 pb-1 border-b border-hairline">
        <h2 className="text-medium font-medium">{title}</h2>
        {note && <span className="text-tiny text-fg-tertiary-2">{note}</span>}
      </div>
      <div className="flex flex-col gap-3">{children}</div>
    </section>
  );
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex items-center gap-4 flex-wrap">
      <span
        className="uppercase tracking-label-up text-fg-tertiary-2 shrink-0"
        style={{ fontSize: 11, width: 220 }}
      >
        {label}
      </span>
      <div className="flex items-center gap-3 flex-wrap">{children}</div>
    </div>
  );
}
