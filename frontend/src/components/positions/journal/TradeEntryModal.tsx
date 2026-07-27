import { useEffect, useMemo, useRef, useState } from "react";

import { Modal } from "@/components/ui/Modal";
import { useTickerDetail } from "@/hooks/useTickerDetail";
import { useCreateTrade, useUploadScreenshot } from "@/hooks/useTrades";
import { useSelectedTicker } from "@/stores/selectedTicker";
import {
  STRATEGY_LABELS,
  STRATEGY_LEG_TEMPLATES,
  computeNet,
  type TradeLeg,
} from "@/types/journal";

interface Props {
  open: boolean;
  onClose: () => void;
}

const STRATEGY_KEYS = Object.keys(STRATEGY_LEG_TEMPLATES);

function defaultExpiry(): string {
  // 21 days out — typical near-term monthly window.
  const d = new Date();
  d.setDate(d.getDate() + 21);
  // Roll forward to the next Friday.
  while (d.getDay() !== 5) d.setDate(d.getDate() + 1);
  return d.toISOString().slice(0, 10);
}

function todayIso(): string {
  return new Date().toISOString();
}

/**
 * Trade entry modal — Phase 1.
 *
 * Picking a strategy scaffolds the leg rows from STRATEGY_LEG_TEMPLATES;
 * the user only fills strike + expiry + price + contracts. Net debit /
 * credit previews live as the user types. Net override is allowed so
 * the user can journal a real fill that doesn't quite match mid-price.
 *
 * Implementation note: this is a real modal (fixed overlay covers the
 * page), not an in-flow dialog — the journal sits at the bottom of the
 * Positions shell and would otherwise push layout when opened.
 */
export function TradeEntryModal({ open, onClose }: Props) {
  const selected = useSelectedTicker((s) => s.symbol);
  const { data: detail } = useTickerDetail(selected ?? null);
  const createTrade = useCreateTrade();
  const uploadScreenshot = useUploadScreenshot();
  // Synchronous double-submit guard — createTrade.isPending only flips on the
  // next render, so a double-click / double-Enter would log two identical
  // journal trades before the disabled state applies.
  const submittingRef = useRef(false);

  const [symbol, setSymbol] = useState(selected ?? "");
  const [strategy, setStrategy] = useState<string>("long_call");
  const [legs, setLegs] = useState<TradeLeg[]>([]);
  const [entryUnderlying, setEntryUnderlying] = useState<string>("");
  const [notes, setNotes] = useState("");
  const [isPaper, setIsPaper] = useState(true);
  const [netOverride, setNetOverride] = useState<string>(""); // blank = use computed
  const [formError, setFormError] = useState<string | null>(null);

  // Phase 2 metadata — all optional.
  const [tags, setTags] = useState<string[]>([]);
  const [tagDraft, setTagDraft] = useState("");
  const [confidence, setConfidence] = useState<number | null>(null);
  const [thesis, setThesis] = useState("");
  const [plannedExit, setPlannedExit] = useState("");
  const [riskAmount, setRiskAmount] = useState("");

  // Screenshot staged at entry time. The trade must exist before it can
  // carry a screenshot (the upload sets it on an existing row), so we hold
  // the File here and POST it right after createTrade returns the new id.
  const [screenshot, setScreenshot] = useState<File | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  // Hydrate defaults when the modal opens.
  useEffect(() => {
    if (!open) return;
    setSymbol(selected ?? "");
    setStrategy("long_call");
    setLegs(scaffoldLegs("long_call", defaultExpiry(), detail?.price ?? 100));
    setEntryUnderlying(detail ? String(detail.price) : "");
    setNotes("");
    setIsPaper(true);
    setNetOverride("");
    setFormError(null);
    setTags([]);
    setTagDraft("");
    setConfidence(null);
    setThesis("");
    setPlannedExit("");
    setRiskAmount("");
    setScreenshot(null);
  }, [open, selected, detail]);

  const onPickScreenshot = (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0] ?? null;
    if (!f) {
      setScreenshot(null);
      return;
    }
    // Mirror the server guard so the user gets instant feedback rather than
    // a round-trip 422.
    if (!["image/png", "image/jpeg", "image/jpg"].includes(f.type)) {
      setFormError("Screenshot must be a PNG or JPEG image.");
      return;
    }
    if (f.size > 5 * 1024 * 1024) {
      setFormError("Screenshot must be 5 MB or smaller.");
      return;
    }
    setFormError(null);
    setScreenshot(f);
  };

  const addTag = () => {
    const t = tagDraft.trim();
    if (!t) return;
    if (tags.includes(t)) {
      setTagDraft("");
      return;
    }
    setTags([...tags, t]);
    setTagDraft("");
  };
  const removeTag = (t: string) => setTags(tags.filter((x) => x !== t));

  // Re-scaffold legs when strategy changes — preserves the current expiry
  // and ATM strike anchor so the user doesn't lose context.
  const onStrategyChange = (next: string) => {
    setStrategy(next);
    const expiry = legs[0]?.expiry ?? defaultExpiry();
    const anchorStrike =
      legs[0]?.strike ?? (Number(entryUnderlying) || detail?.price || 100);
    setLegs(scaffoldLegs(next, expiry, anchorStrike));
  };

  const computedNet = useMemo(() => computeNet(legs), [legs]);
  const displayedNet = netOverride !== "" ? Number(netOverride) : computedNet;

  if (!open) return null;

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setFormError(null);
    if (submittingRef.current) return;
    if (!symbol.trim()) {
      setFormError("Symbol is required.");
      return;
    }
    if (legs.length === 0) {
      setFormError("At least one leg required.");
      return;
    }
    const underlying = Number(entryUnderlying);
    if (!underlying || underlying <= 0) {
      setFormError("Entry underlying price must be > 0.");
      return;
    }
    submittingRef.current = true;
    try {
      const created = await createTrade.mutateAsync({
        symbol: symbol.toUpperCase().trim(),
        strategy,
        legs,
        entry_date: todayIso(),
        entry_underlying_price: underlying,
        net_debit_credit: netOverride !== "" ? Number(netOverride) : null,
        is_paper: isPaper,
        notes: notes.trim() || null,
        tags,
        confidence,
        thesis: thesis.trim() || null,
        planned_exit: plannedExit.trim() || null,
        risk_amount: riskAmount ? Number(riskAmount) : null,
      });
      // The trade now exists — attach the staged screenshot if there is one.
      // A failed upload doesn't unwind the (already-saved) trade; surface it
      // as a toast (via the hook's onError) and still close the modal.
      if (screenshot && created?.id != null) {
        try {
          await uploadScreenshot.mutateAsync({ id: created.id, file: screenshot });
        } catch {
          /* hook's onError toasts; the trade itself was saved */
        }
      }
      onClose();
    } catch (err) {
      setFormError((err as Error).message);
    } finally {
      submittingRef.current = false;
    }
  };

  return (
    <Modal
      open={open}
      onClose={onClose}
      labelledBy="trade-entry-title"
      align="top"
      panelClassName="w-[640px] max-h-[80vh] overflow-y-auto bg-tier-0 border border-hairline-strong"
    >
      <form onSubmit={onSubmit} style={{ borderRadius: 0 }}>
        <header className="flex items-center justify-between px-4 py-2 border-b border-hairline bg-tier-1">
          <span
            id="trade-entry-title"
            className="text-xs2 uppercase tracking-label-up text-fg-primary"
          >
            Log a trade
          </span>
          <button
            type="button"
            onClick={onClose}
            className="text-tiny text-fg-tertiary hover:text-fg-primary"
            aria-label="Close"
          >
            ESC ×
          </button>
        </header>

        <SectionHeader label="Setup" />
        <div className="grid grid-cols-2 gap-4 px-4 pb-4 pt-2">
          <Field label="Symbol">
            <input
              value={symbol}
              onChange={(e) => setSymbol(e.target.value.toUpperCase())}
              spellCheck={false}
              autoComplete="off"
              className="w-full h-7 px-2 text-xs2 font-mono uppercase bg-tier-1 border border-hairline text-fg-primary rounded-btn"
            />
          </Field>
          <Field label="Strategy">
            <select
              value={strategy}
              onChange={(e) => onStrategyChange(e.target.value)}
              className="w-full h-7 px-1 text-xs2 bg-tier-1 border border-hairline text-fg-primary rounded-btn"
            >
              {STRATEGY_KEYS.map((key) => (
                <option key={key} value={key}>
                  {STRATEGY_LABELS[key] ?? key}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Entry underlying price">
            <input
              type="number"
              step="0.01"
              value={entryUnderlying}
              onChange={(e) => setEntryUnderlying(e.target.value)}
              className="w-full h-7 px-2 text-xs2 font-mono tabular-nums bg-tier-1 border border-hairline text-fg-primary rounded-btn"
            />
          </Field>
          <Field label="Paper / live">
            <div className="flex items-stretch gap-2 h-7">
              <button
                type="button"
                onClick={() => setIsPaper(true)}
                className={[
                  "flex-1 text-tiny uppercase tracking-label-up border",
                  isPaper
                    ? "border-cyan text-cyan bg-tier-1"
                    : "border-hairline text-fg-tertiary hover:bg-tier-2",
                ].join(" ") + " rounded-btn"}
              >
                Paper
              </button>
              <button
                type="button"
                onClick={() => setIsPaper(false)}
                className={[
                  "flex-1 text-tiny uppercase tracking-label-up border",
                  !isPaper
                    ? "border-amber text-amber bg-tier-1"
                    : "border-hairline text-fg-tertiary hover:bg-tier-2",
                ].join(" ") + " rounded-btn"}
              >
                Live
              </button>
            </div>
          </Field>
        </div>

        <LegEditor legs={legs} onChange={setLegs} />

        <div className="grid grid-cols-2 gap-4 px-4 py-3 border-t border-hairline">
          <div>
            <div className="text-tiny uppercase tracking-label-up text-fg-secondary mb-1">
              Net cost (computed)
            </div>
            <div className="text-medium font-medium tabular-nums text-fg-primary">
              {formatCost(computedNet)}
            </div>
            <div className="text-tiny text-fg-tertiary mt-0.5">
              {computedNet >= 0 ? "Debit (paid)" : "Credit (received)"}
            </div>
          </div>
          <Field label="Override net (optional)">
            <input
              type="number"
              step="0.01"
              value={netOverride}
              onChange={(e) => setNetOverride(e.target.value)}
              placeholder={String(computedNet)}
              className="w-full h-7 px-2 text-xs2 font-mono tabular-nums bg-tier-1 border border-hairline text-fg-primary placeholder:text-fg-tertiary rounded-btn"
            />
            <div className="text-tiny text-fg-tertiary mt-0.5">
              Will save as {formatCost(displayedNet)}.
            </div>
          </Field>
        </div>

        <SectionHeader label="Thesis & plan" />
        <div className="grid grid-cols-2 gap-4 px-4 pb-3 pt-2">
          <Field label="Tags">
            <div className="flex flex-col gap-1">
              <div className="flex gap-1 flex-wrap min-h-[1.5rem]">
                {tags.map((t) => (
                  <span
                    key={t}
                    className="inline-flex items-center gap-1 px-1.5 py-px text-tiny border border-hairline bg-tier-1 text-fg-secondary rounded-hair"
                    style={{ fontSize: 12 }}
                  >
                    {t}
                    <button
                      type="button"
                      onClick={() => removeTag(t)}
                      className="text-fg-tertiary hover:text-bearish leading-none"
                      aria-label={`Remove tag ${t}`}
                    >
                      ×
                    </button>
                  </span>
                ))}
              </div>
              <div className="flex gap-1">
                <input
                  type="text"
                  value={tagDraft}
                  onChange={(e) => setTagDraft(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") {
                      e.preventDefault();
                      addTag();
                    }
                  }}
                  placeholder="earnings, momentum…"
                  className="flex-1 h-7 px-2 text-xs2 bg-tier-1 border border-hairline text-fg-primary placeholder:text-fg-tertiary rounded-btn"
                />
                <button
                  type="button"
                  onClick={addTag}
                  className="h-7 px-2 text-tiny uppercase tracking-label-up border border-hairline text-fg-secondary hover:bg-tier-2 rounded-btn"
                >
                  add
                </button>
              </div>
            </div>
          </Field>
          <Field label="Confidence">
            <div className="flex items-center gap-1">
              {[1, 2, 3, 4, 5].map((n) => (
                <button
                  key={n}
                  type="button"
                  onClick={() => setConfidence(confidence === n ? null : n)}
                  className={[
                    "h-7 w-7 text-tiny tabular-nums border",
                    confidence != null && n <= confidence
                      ? "border-amber text-amber bg-tier-1"
                      : "border-hairline text-fg-tertiary hover:bg-tier-2",
                  ].join(" ") + " rounded-btn"}
                  aria-label={`Confidence ${n}`}
                >
                  {n}
                </button>
              ))}
              <span className="ml-1 text-tiny text-fg-tertiary">
                {confidence == null ? "—" : `${confidence}/5`}
              </span>
            </div>
          </Field>
        </div>

        <Field label="Thesis" className="px-4 pb-3">
          <textarea
            value={thesis}
            onChange={(e) => setThesis(e.target.value)}
            rows={2}
            placeholder="Why this setup, right now?"
            className="w-full px-2 py-1 text-xs2 bg-tier-1 border border-hairline text-fg-primary placeholder:text-fg-tertiary resize-none rounded-btn"
          />
        </Field>

        <Field label="Planned exit" className="px-4 pb-3">
          <textarea
            value={plannedExit}
            onChange={(e) => setPlannedExit(e.target.value)}
            rows={2}
            placeholder="At what level / event do you close?"
            className="w-full px-2 py-1 text-xs2 bg-tier-1 border border-hairline text-fg-primary placeholder:text-fg-tertiary resize-none rounded-btn"
          />
        </Field>

        <SectionHeader label="Risk" />
        <div className="grid grid-cols-2 gap-4 px-4 pb-3 pt-2">
          <Field label="Risk amount ($)">
            <input
              type="number"
              step="1"
              min="0"
              value={riskAmount}
              onChange={(e) => setRiskAmount(e.target.value)}
              placeholder="500"
              className="w-full h-7 px-2 text-xs2 font-mono tabular-nums bg-tier-1 border border-hairline text-fg-primary placeholder:text-fg-tertiary rounded-btn"
            />
            <div className="text-tiny text-fg-tertiary mt-0.5">
              Drives R-multiple on close.
            </div>
          </Field>
          <Field label="Notes (entry)">
            <textarea
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              rows={2}
              className="w-full px-2 py-1 text-xs2 bg-tier-1 border border-hairline text-fg-primary resize-none rounded-btn"
            />
          </Field>
          <Field label="Screenshot (PNG / JPEG, ≤ 5 MB)" className="col-span-2">
            <div className="flex items-center gap-2">
              <input
                ref={fileInputRef}
                type="file"
                accept="image/png,image/jpeg"
                onChange={onPickScreenshot}
                className="hidden"
              />
              <button
                type="button"
                onClick={() => fileInputRef.current?.click()}
                className="h-7 px-2 text-tiny uppercase tracking-label-up border border-hairline text-fg-secondary hover:bg-tier-2 rounded-btn"
              >
                {screenshot ? "Change…" : "Attach image…"}
              </button>
              {screenshot && (
                <span className="inline-flex items-center gap-1 text-tiny text-fg-secondary">
                  <span className="truncate" style={{ maxWidth: 220 }}>
                    {screenshot.name}
                  </span>
                  <button
                    type="button"
                    onClick={() => {
                      setScreenshot(null);
                      if (fileInputRef.current) fileInputRef.current.value = "";
                    }}
                    className="text-fg-tertiary hover:text-bearish leading-none px-1"
                    aria-label="Remove screenshot"
                  >
                    ×
                  </button>
                </span>
              )}
            </div>
            <div className="text-tiny text-fg-tertiary mt-0.5">
              Uploaded after the trade is saved.
            </div>
          </Field>
        </div>

        {formError && (
          <div className="px-4 pb-2 text-tiny text-bearish">{formError}</div>
        )}

        <footer className="flex items-center justify-end gap-2 px-4 py-3 border-t border-hairline bg-tier-1">
          <button
            type="button"
            onClick={onClose}
            className="h-7 px-3 text-tiny uppercase tracking-label-up border border-hairline text-fg-secondary hover:bg-tier-2 rounded-btn"
          >
            Cancel
          </button>
          <button
            type="submit"
            disabled={createTrade.isPending || uploadScreenshot.isPending}
            className="h-7 px-3 text-tiny uppercase tracking-label-up border border-amber text-amber bg-tier-1 hover:bg-tier-2 disabled:opacity-50 rounded-btn"
          >
            {uploadScreenshot.isPending
              ? "Uploading…"
              : createTrade.isPending
                ? "Saving…"
                : "Save trade"}
          </button>
        </footer>
      </form>
    </Modal>
  );
}

function Field({
  label,
  children,
  className,
}: {
  label: string;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <label className={`flex flex-col gap-1 ${className ?? ""}`}>
      <span className="text-tiny uppercase tracking-label-up text-fg-secondary">
        {label}
      </span>
      {children}
    </label>
  );
}

function SectionHeader({ label }: { label: string }) {
  return (
    <div className="px-4 py-1.5 bg-tier-1 border-t border-hairline">
      <span className="text-tiny uppercase tracking-label-up text-fg-secondary">
        {label}
      </span>
    </div>
  );
}

function LegEditor({
  legs,
  onChange,
}: {
  legs: TradeLeg[];
  onChange: (legs: TradeLeg[]) => void;
}) {
  const updateLeg = (idx: number, patch: Partial<TradeLeg>) => {
    onChange(legs.map((l, i) => (i === idx ? { ...l, ...patch } : l)));
  };

  return (
    <section className="border-t border-hairline">
      <div className="grid grid-cols-[60px_60px_80px_120px_60px_80px] gap-2 px-4 py-1.5 bg-tier-1 text-tiny uppercase tracking-label-up text-fg-secondary">
        <span>Side</span>
        <span>Action</span>
        <span>Strike</span>
        <span>Expiry</span>
        <span>Qty</span>
        <span>Premium</span>
      </div>
      <div className="px-4 py-2 flex flex-col gap-1">
        {legs.map((leg, i) => (
          <div
            key={i}
            className="grid grid-cols-[60px_60px_80px_120px_60px_80px] gap-2 items-center"
          >
            <select
              value={leg.side}
              onChange={(e) => updateLeg(i, { side: e.target.value as TradeLeg["side"] })}
              className="h-7 text-tiny bg-tier-1 border border-hairline text-fg-primary rounded-btn"
            >
              <option value="call">CALL</option>
              <option value="put">PUT</option>
            </select>
            <select
              value={leg.action}
              onChange={(e) => updateLeg(i, { action: e.target.value as TradeLeg["action"] })}
              className="h-7 text-tiny bg-tier-1 border border-hairline text-fg-primary rounded-btn"
            >
              <option value="buy">BUY</option>
              <option value="sell">SELL</option>
            </select>
            <input
              type="number"
              step="0.5"
              value={leg.strike || ""}
              onChange={(e) => updateLeg(i, { strike: Number(e.target.value) })}
              className="h-7 px-1 text-tiny font-mono tabular-nums bg-tier-1 border border-hairline text-fg-primary text-right rounded-btn"
            />
            <input
              type="date"
              value={leg.expiry}
              onChange={(e) => updateLeg(i, { expiry: e.target.value })}
              className="h-7 px-1 text-tiny bg-tier-1 border border-hairline text-fg-primary rounded-btn"
            />
            <input
              type="number"
              step="1"
              min="1"
              value={leg.contracts}
              onChange={(e) => updateLeg(i, { contracts: Number(e.target.value) || 1 })}
              className="h-7 px-1 text-tiny font-mono tabular-nums bg-tier-1 border border-hairline text-fg-primary text-right rounded-btn"
            />
            <input
              type="number"
              step="0.01"
              min="0"
              value={leg.entry_price || ""}
              onChange={(e) => updateLeg(i, { entry_price: Number(e.target.value) })}
              className="h-7 px-1 text-tiny font-mono tabular-nums bg-tier-1 border border-hairline text-fg-primary text-right rounded-btn"
            />
          </div>
        ))}
      </div>
    </section>
  );
}

function scaffoldLegs(strategy: string, expiry: string, anchorStrike: number): TradeLeg[] {
  const template = STRATEGY_LEG_TEMPLATES[strategy] ?? [
    { side: "call", action: "buy" },
  ];
  // Round anchor strike to the nearest dollar for sane defaults.
  const anchor = Math.round(anchorStrike);
  return template.map((t, i) => ({
    side: t.side,
    action: t.action,
    // Offset wing legs from anchor — keeps the form non-trivial out of
    // the box for spreads / condors. User adjusts as needed.
    strike: anchor + offsetForLegIndex(strategy, i),
    expiry,
    contracts: 1,
    entry_price: 0,
  }));
}

function offsetForLegIndex(strategy: string, idx: number): number {
  // For multi-leg strategies, scaffold the wing strikes a few dollars
  // away from the anchor. This is just an editing convenience; the user
  // sets the actual strikes from the chain.
  if (strategy === "bull_call_spread") return idx === 0 ? 0 : 5;
  if (strategy === "bear_put_spread") return idx === 0 ? 0 : -5;
  if (strategy === "bull_put_spread") return idx === 0 ? 0 : -5;
  if (strategy === "bear_call_spread") return idx === 0 ? 0 : 5;
  if (strategy === "long_strangle") return idx === 0 ? 5 : -5;
  if (strategy === "iron_condor") {
    return [5, 10, -5, -10][idx] ?? 0;
  }
  return 0;
}

function formatCost(value: number): string {
  const sign = value < 0 ? "−" : "";
  const abs = Math.abs(value);
  return `${sign}$${abs.toFixed(2)}`;
}
