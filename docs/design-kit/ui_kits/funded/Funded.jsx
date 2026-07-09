/* Funded Account view — risk-first (MLL hero) + funded-specific payout
   eligibility, 50/50 split breakdown, withdrawal history.
   Deterministic mock; ELIGIBLE / LOCKED payout states; 50K/100K/150K. */

const FN_TIERS = {
  "50K":  { start: 50000, trail: 2000 },
  "100K": { start: 100000, trail: 4000 },
  "150K": { start: 150000, trail: 4500 },
};
const SPLIT = 0.5;            // 50/50
const GREEN_MIN = 150;        // each green day must clear >$150
const GREEN_NEED = 3;         // 3 cumulative qualifying green days
const CONSISTENCY = 0.40;     // no green day > 40% of cycle profit

const fmtN = (v, signed) => {
  const s = signed ? (v > 0 ? "+" : v < 0 ? "−" : "") : v < 0 ? "−" : "";
  return s + "$" + Math.abs(Math.round(v)).toLocaleString("en-US");
};

/* Cycle-since-last-payout ledgers. Day P&L is FIXED across tiers (a
   trader's recent week is what it is); only start + trail scale by tier.
   LOCKED: 2 qualifying green days. ELIGIBLE: 3 (and 31% best-day share). */
const FN_CYCLES = {
  LOCKED:   [ ["Mon Jun 1", 300], ["Tue Jun 2", 140], ["Wed Jun 3", -70], ["Thu Jun 4", 300], ["Fri Jun 5", 120] ],
  ELIGIBLE: [ ["Mon Jun 1", 300], ["Tue Jun 2", 140], ["Wed Jun 3", -70], ["Thu Jun 4", 300], ["Fri Jun 5", 290] ],
};
// prior payout (fixed) — drives history + lifetime numbers
const PRIOR_PAYOUT = { date: "May 27", gross: 1400, daysAgo: 9 };

function fundedModel(tierKey, payoutState) {
  const t = FN_TIERS[tierKey];
  const cycle = FN_CYCLES[payoutState];
  const days = cycle.map(([d, p]) => ({ date: d, pnl: p }));
  const profitCycle = days.reduce((a, b) => a + b.pnl, 0);
  const grossPositive = days.filter((d) => d.pnl > 0).reduce((a, b) => a + b.pnl, 0);
  const qualifying = days.filter((d) => d.pnl > GREEN_MIN).length;
  const bestGreen = Math.max(...days.map((d) => d.pnl));
  const bestShare = grossPositive > 0 ? bestGreen / grossPositive : 0;

  const balance = t.start + profitCycle;
  const floor = t.start;                 // funded floor locks at funded capital
  const distance = balance - floor;      // = profitCycle
  const ratio = distance / t.trail;

  const checks = {
    greenDays: qualifying >= GREEN_NEED,
    overMin: days.filter((d) => d.pnl > 0).every((d) => d.pnl > GREEN_MIN) || qualifying >= GREEN_NEED,
    consistency: bestShare <= CONSISTENCY,
    weekly: PRIOR_PAYOUT.daysAgo >= 7,
  };
  const eligible = checks.greenDays && checks.consistency && checks.weekly;

  // split math (since last payout)
  const yourShare = profitCycle > 0 ? profitCycle * SPLIT : 0;
  const firmShare = profitCycle > 0 ? profitCycle * SPLIT : 0;
  const withdrawable = eligible ? yourShare : 0;

  // lifetime since funding
  const lifetimeGross = PRIOR_PAYOUT.gross + Math.max(0, profitCycle);
  const lifetimePaidToYou = PRIOR_PAYOUT.gross * SPLIT;

  return {
    t, tierKey, payoutState, days, profitCycle, grossPositive, qualifying, bestGreen, bestShare,
    balance, floor, distance, ratio, checks, eligible, yourShare, firmShare, withdrawable,
    lifetimeGross, lifetimePaidToYou,
  };
}

function fnTone(ratio, breached) {
  if (breached || ratio < 0.10) return "red";
  if (ratio < 0.25) return "amber";
  return "green";
}

/* gauge — funded floor locked at start; still shows trail history */
function FnGauge({ m }) {
  const min = m.t.start - m.t.trail;
  const max = m.t.start + m.t.trail * 1.1;
  const span = max - min;
  const pos = (v) => Math.max(0, Math.min(100, ((v - min) / span) * 100));
  const floorP = pos(m.floor);
  const youP = pos(m.balance);
  const breached = m.distance <= 0;
  const warn = m.ratio < 0.25 && m.ratio >= 0;
  return (
    <div className="cb-gauge">
      <div className="cb-gauge-track">
        <div className="cb-seg danger" style={{ left: 0, width: floorP + "%" }} />
        {breached ? (
          <div className="cb-seg breach" style={{ left: youP + "%", width: (floorP - youP) + "%" }} />
        ) : (
          <div className={"cb-seg cushion" + (warn ? " warn" : "")} style={{ left: floorP + "%", width: (youP - floorP) + "%" }} />
        )}
      </div>
      <div className="cb-trail" style={{ left: "0%", width: floorP + "%" }}>
        <span className="tl">floor locked at funded capital</span>
        <span className="line" /><span className="arr">▸</span>
      </div>
      <div className="cb-mark floor" style={{ left: floorP + "%" }}>
        <span className="lab">FLOOR {fmtN(m.floor)}</span><span className="stem" />
      </div>
      <div className={"cb-mark you " + (breached ? "bear" : "bull")} style={{ left: youP + "%" }}>
        <span className="lab">YOU {fmtN(m.balance)}</span><span className="stem" />
      </div>
    </div>
  );
}

function FnHero({ m }) {
  const breached = m.distance <= 0;
  const tn = fnTone(m.ratio, breached);
  return (
    <div className="cb-hero">
      <div className="cb-hero-head">
        <span className="k">Maximum Loss Limit · Trailing Drawdown · Real Capital</span>
        <span className="sub">{breached ? "Account breached" : "Distance to the floor"}</span>
      </div>
      <div className="cb-hero-body">
        <div className="cb-hero-top">
          <div className={"cb-distance " + tn}>
            <span className="big">{fmtN(Math.abs(m.distance))}</span>
            <span className="cap">{breached ? "below floor — funded account lost" : "above floor"}</span>
          </div>
          <div className="cb-hero-stats">
            <div className="cb-hstat"><span className="l">MLL Floor</span><span className="v pos">{fmtN(m.floor)}</span></div>
            <div className="cb-hstat"><span className="l">Trail dist.</span><span className="v">{fmtN(m.t.trail)}</span></div>
            <div className="cb-hstat"><span className="l">Balance</span><span className="v bull">{fmtN(m.balance)}</span></div>
          </div>
        </div>
        <FnGauge m={m} />
        <div className="cb-hero-foot">
          <span>This is firm capital. Lose <b>{fmtN(m.distance)}</b> more and the funded account is gone — getting paid is secondary to not blowing up.</span>
        </div>
      </div>
    </div>
  );
}

function Eligibility({ m, onRequest }) {
  const rows = [
    { pass: m.checks.greenDays, t: `${GREEN_NEED} cumulative green days`, d: `${m.qualifying} of ${GREEN_NEED} days over ${fmtN(GREEN_MIN)}` },
    { pass: m.checks.overMin, t: `Each green day over ${fmtN(GREEN_MIN)}`, d: m.qualifying >= GREEN_NEED ? "all qualifying days clear it" : `${m.qualifying} qualifying so far` },
    { pass: m.checks.consistency, t: `Consistency rule (≤${(CONSISTENCY*100)|0}%)`, d: `best green day is ${(m.bestShare*100).toFixed(0)}% of cycle profit`, bad: !m.checks.consistency },
    { pass: m.checks.weekly, t: "One request per week", d: `last payout ${PRIOR_PAYOUT.daysAgo} days ago`, bad: !m.checks.weekly },
  ];
  return (
    <div className="cb-panel">
      <div className="cb-phead"><span className="k">Payout Eligibility</span><span className="r">{m.eligible ? "ready" : (GREEN_NEED - m.qualifying) + " green day to go"}</span></div>
      <div className={"fn-elig-status " + (m.eligible ? "ready" : "locked")}>
        <span className="ic">{m.eligible ? "✓" : "⏳"}</span>
        <span className="txt">
          <span className="big">{m.eligible ? "You can request a payout" : "Payout locked"}</span>
          <span className="sm">{m.eligible ? "All requirements met since your last payout" : "Keep trading green to unlock — you're almost there"}</span>
        </span>
      </div>
      <div className="fn-greendays">
        {Array.from({ length: GREEN_NEED }).map((_, i) => (
          <span key={i} className={"pip" + (i < m.qualifying ? " on" : "")}>{i < m.qualifying ? "✓" : i + 1}</span>
        ))}
        <span className="lab"><b>{m.qualifying}</b> of {GREEN_NEED} qualifying green days</span>
      </div>
      <div className="cb-check">
        {rows.map((r, i) => (
          <div className="cb-check-row" key={i}>
            <span className={"cb-check-mark " + (r.pass ? "pass" : r.bad ? "fail" : "pending")}>{r.pass ? "✓" : r.bad ? "✗" : "○"}</span>
            <span className="cb-check-txt"><span className="t">{r.t}</span><span className={"d" + (r.pass ? " bull" : r.bad ? " bear" : "")}>{r.d}</span></span>
          </div>
        ))}
      </div>
      {m.eligible ? (
        <a className="fn-req-btn on" href="../payout/index.html">REQUEST PAYOUT · {fmtN(m.withdrawable)} →</a>
      ) : (
        <button className="fn-req-btn off" disabled>REQUEST PAYOUT — locked</button>
      )}
    </div>
  );
}

function SplitBreakdown({ m }) {
  return (
    <div className="cb-panel">
      <div className="cb-phead"><span className="k">Profit &amp; Split · 50 / 50</span><span className="r">since last payout</span></div>
      <div className="fn-money">
        <div className="fn-money-row">
          <span className="l">Profit since last payout</span>
          <span className="v">{fmtN(m.profitCycle, true)}</span>
        </div>
        <div className="fn-money-row you">
          <span className="l">Your share<span className="split-tag">50%</span></span>
          <span className="v">{fmtN(m.yourShare)}</span>
        </div>
        <div className="fn-money-row firm">
          <span className="l">Firm share<span className="split-tag">50%</span></span>
          <span className="v">{fmtN(m.firmShare)}</span>
        </div>
        <div className="fn-money-row">
          <span className="l">Lifetime profit<span className="s">since funding</span></span>
          <span className="v">{fmtN(m.lifetimeGross)}</span>
        </div>
      </div>
      <div className={"fn-withdrawable" + (m.withdrawable > 0 ? "" : " zero")}>
        <span className="l">Withdrawable now</span>
        <span className="v">{fmtN(m.withdrawable)}</span>
      </div>
    </div>
  );
}

function History({ m }) {
  const paid = [{ date: PRIOR_PAYOUT.date, gross: PRIOR_PAYOUT.gross, share: PRIOR_PAYOUT.gross * SPLIT, firm: PRIOR_PAYOUT.gross * SPLIT, status: "paid" }];
  return (
    <div className="cb-panel">
      <div className="cb-phead"><span className="k">Withdrawal History</span><span className="r">{paid.length} payout{paid.length !== 1 ? "s" : ""}</span></div>
      <div className="fn-hist">
        <div className="fn-hist-row head">
          <span>Date</span><span className="fn-num-right">Gross profit</span><span className="fn-num-right">Your 50%</span><span className="fn-num-right">Firm 50%</span><span>Status</span>
        </div>
        {paid.length === 0 ? (
          <div className="fn-hist-empty">No payouts yet — meet the requirement above to request your first.</div>
        ) : paid.map((p, i) => (
          <div className="fn-hist-row" key={i}>
            <span className="date">{p.date}</span>
            <span className="gross fn-num-right">{fmtN(p.gross)}</span>
            <span className="share fn-num-right">{fmtN(p.share)}</span>
            <span className="firm fn-num-right">{fmtN(p.firm)}</span>
            <span className="status paid"><span className="dot" />Paid</span>
          </div>
        ))}
      </div>
    </div>
  );
}

window.FundedParts = { fundedModel, FnHero, Eligibility, SplitBreakdown, History, fmtN, FN_TIERS };
