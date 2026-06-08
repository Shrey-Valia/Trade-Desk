/* Combine Evaluation Dashboard — risk-first: the MLL/drawdown hero
   dominates. Three account states (ACTIVE / PASSED / FAILED) and three
   tiers (50K / 100K / 150K), deterministic mock data. */

const TIERS = {
  "50K":  { start: 50000, target: 3000, trail: 2000, k: 1 },
  "100K": { start: 100000, target: 6000, trail: 4000, k: 2 },
  "150K": { start: 150000, target: 9000, trail: 4500, k: 3 },
};
const MIN_DAYS = 2;

const fmt = (v, signed) => {
  if (!isFinite(v)) return "—";
  const s = signed ? (v > 0 ? "+" : v < 0 ? "−" : "") : v < 0 ? "−" : "";
  return s + "$" + Math.abs(v).toLocaleString("en-US", { maximumFractionDigits: 0 });
};
const fmt2 = (v, signed) => {
  const s = signed ? (v > 0 ? "+" : v < 0 ? "−" : "") : v < 0 ? "−" : "";
  return s + "$" + Math.abs(v).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
};

/* Base per-50K day ledgers per state; scaled by tier k. */
const SCENARIOS = {
  ACTIVE: { days: [480, 460, 300], todayIdx: 2 },
  PASSED: { days: [900, 850, 780, 670], todayIdx: 3 },
  FAILED: { days: [480, 460, 300, -1880], todayIdx: 3 },
};
const DAY_DATES = ["Mon Jun 1", "Tue Jun 2", "Wed Jun 3", "Thu Jun 4"];

function buildModel(tierKey, state) {
  const t = TIERS[tierKey];
  const sc = SCENARIOS[state];
  const days = sc.days.map((d) => d * t.k);
  const profit = days.reduce((a, b) => a + b, 0);
  const balance = t.start + profit;

  // High-water mark drives the trailing floor.
  // ACTIVE/FAILED: account peaked +trail above start intraday (floor lifted to start).
  // PASSED: at a new high.
  let highWater;
  if (state === "PASSED") highWater = balance;
  else highWater = t.start + t.trail; // peaked exactly one trail-distance up
  const floor = highWater - t.trail;
  const distance = balance - floor; // <0 means breached
  const ratio = distance / t.trail;

  // consistency: best day's share of total positive profit
  const grossProfit = days.filter((d) => d > 0).reduce((a, b) => a + b, 0);
  const bestDay = Math.max(...days);
  const bestShare = grossProfit > 0 ? bestDay / grossProfit : 0;

  const daysTraded = days.length;

  const checks = {
    profit: profit >= t.target,
    minDays: daysTraded >= MIN_DAYS,
    consistency: bestShare < 0.5 || profit <= 0,
    aboveFloor: distance > 0,
  };
  // derived state (FAILED forced when breached)
  let derived = state;
  if (!checks.aboveFloor) derived = "FAILED";
  else if (checks.profit && checks.minDays && checks.consistency) derived = "PASSED";
  else derived = "ACTIVE";

  return { t, tierKey, stateKey: state, state: derived, days, profit, balance, highWater, floor, distance, ratio, grossProfit, bestDay, bestShare, daysTraded, checks };
}

function tone(ratio) {
  if (ratio < 0.10) return "red";
  if (ratio < 0.25) return "amber";
  return "green";
}

/* ---------- gauge ---------- */
function Gauge({ m }) {
  const min = m.t.start - m.t.trail;            // original floor at combine open
  const passLine = m.t.start + m.t.target;      // the pass line
  const max = Math.max(passLine, m.highWater, m.balance) + m.t.trail * 0.18;
  const span = max - min;
  const pos = (v) => Math.max(0, Math.min(100, ((v - min) / span) * 100));
  const origFloorP = pos(m.t.start - m.t.trail); // = 0
  const floorP = pos(m.floor);
  const youP = pos(m.balance);
  const hwP = pos(m.highWater);
  const targetP = pos(passLine);
  const breached = m.distance <= 0;
  const cushionWarn = m.ratio < 0.25 && m.ratio >= 0;

  return (
    <div className="cb-gauge">
      <div className="cb-gauge-track">
        {/* danger zone: everything at/below the floor */}
        <div className="cb-seg danger" style={{ left: 0, width: floorP + "%" }} />
        {/* cushion (green/amber) between floor and you — or breach (red) if below */}
        {breached ? (
          <div className="cb-seg breach" style={{ left: youP + "%", width: (floorP - youP) + "%" }} />
        ) : (
          <div className={"cb-seg cushion" + (cushionWarn ? " warn" : "")} style={{ left: floorP + "%", width: (youP - floorP) + "%" }} />
        )}
        {/* toward-target hatch from you to target */}
        <div className="cb-seg toward" style={{ left: youP + "%", width: Math.max(0, targetP - youP) + "%" }} />
      </div>

      {/* trail arrow: original floor → current floor */}
      {floorP > origFloorP + 1 && (
        <div className="cb-trail" style={{ left: origFloorP + "%", width: (floorP - origFloorP) + "%" }}>
          <span className="tl">floor trailed up</span>
          <span className="line" /><span className="arr">▸</span>
        </div>
      )}

      {/* markers */}
      <div className="cb-mark floor" style={{ left: floorP + "%" }}>
        <span className="lab">FLOOR {fmt(m.floor)}</span><span className="stem" />
      </div>
      <div className={"cb-mark you " + (breached ? "bear" : "bull")} style={{ left: youP + "%" }}>
        <span className="lab">YOU {fmt(m.balance)}</span><span className="stem" />
      </div>
      <div className="cb-mark hw" style={{ left: hwP + "%" }}>
        <span className="lab">HWM {fmt(m.highWater)}</span><span className="stem" />
      </div>
      <div className="cb-mark target" style={{ left: targetP + "%" }}>
        <span className="lab" style={{ transform: "translateX(-50%)" }}>PASS {fmt(passLine)}</span><span className="stem" />
      </div>
    </div>
  );
}

/* ---------- hero ---------- */
function Hero({ m }) {
  const breached = m.distance <= 0;
  const tn = breached ? "red" : tone(m.ratio);
  const trailedFrom = m.t.start - m.t.trail;
  return (
    <div className="cb-hero">
      <div className="cb-hero-head">
        <span className="k">Maximum Loss Limit · Trailing Drawdown</span>
        <span className="sub">{breached ? "Account breached" : "Distance to the floor"}</span>
      </div>
      <div className="cb-hero-body">
        <div className="cb-hero-top">
          <div className={"cb-distance " + tn}>
            <span className="big">{fmt(Math.abs(m.distance))}</span>
            <span className="cap">{breached ? "below floor — account failed" : "above floor"}</span>
          </div>
          <div className="cb-hero-stats">
            <div className="cb-hstat">
              <span className="l">MLL Floor</span>
              <span className="v pos">{fmt(m.floor)}</span>
            </div>
            <div className="cb-hstat">
              <span className="l">Trail dist.</span>
              <span className="v">{fmt(m.t.trail)}</span>
            </div>
            <div className="cb-hstat">
              <span className="l">High-water</span>
              <span className="v bull">{fmt(m.highWater)}</span>
            </div>
          </div>
        </div>
        <Gauge m={m} />
        <div className="cb-hero-foot">
          {breached ? (
            <span>Balance fell <b>{fmt(Math.abs(m.distance))}</b> below the trailing floor. The combine is over.</span>
          ) : (
            <span>Floor has trailed up <b>{fmt(m.floor - trailedFrom)}</b> from its {fmt(trailedFrom)} open — lose <b>{fmt(m.distance)}</b> more and you're out.</span>
          )}
        </div>
      </div>
    </div>
  );
}

/* ---------- profit target ---------- */
function ProfitTarget({ m }) {
  const pct = Math.max(0, Math.min(100, (m.profit / m.t.target) * 100));
  const done = m.checks.profit;
  return (
    <div className="cb-panel">
      <div className="cb-phead"><span className="k">Profit Target · 6%</span><span className="r">how to pass</span></div>
      <div className="cb-pt-body">
        <div className="cb-pt-nums">
          <span className="cur">{fmt(Math.max(0, m.profit))}</span>
          <span className="tot">/ {fmt(m.t.target)}</span>
          <span className={"pct" + (done ? " done" : "")}>{pct.toFixed(0)}%</span>
        </div>
        <div className="cb-bar">
          <div className={"cb-bar fill" + (done ? " done" : "") + (m.profit < 0 ? " neg" : "")}
            style={{ width: (m.profit < 0 ? 100 : pct) + "%", position: "absolute", border: "none" }} />
        </div>
        <span className="cb-pt-cap">{done ? "Target reached" : fmt(m.t.target - m.profit) + " to go · no time limit"}</span>
      </div>
    </div>
  );
}

/* ---------- checklist ---------- */
function Checklist({ m }) {
  const rows = [
    {
      pass: m.checks.profit,
      t: "Profit target reached",
      d: `${fmt(Math.max(0, m.profit))} of ${fmt(m.t.target)}`,
    },
    {
      pass: m.checks.minDays,
      t: `Minimum ${MIN_DAYS} trading days`,
      d: `${m.daysTraded} of ${MIN_DAYS} days traded`,
    },
    {
      pass: m.checks.consistency,
      t: "Consistency rule (≤50%)",
      d: `best day is ${(m.bestShare * 100).toFixed(0)}% of total profit`,
      bad: !m.checks.consistency,
    },
    {
      pass: m.checks.aboveFloor,
      t: "Above MLL floor",
      d: m.distance > 0 ? `${fmt(m.distance)} of cushion remaining` : `breached by ${fmt(Math.abs(m.distance))}`,
      bad: !m.checks.aboveFloor,
    },
  ];
  const remaining = rows.filter((r) => !r.pass).length;
  return (
    <div className="cb-panel">
      <div className="cb-phead">
        <span className="k">Evaluation Checklist</span>
        <span className="r">{remaining === 0 ? "all clear" : remaining + " remaining"}</span>
      </div>
      <div className="cb-check">
        {rows.map((r, i) => (
          <div className="cb-check-row" key={i}>
            <span className={"cb-check-mark " + (r.pass ? "pass" : r.bad ? "fail" : "pending")}>{r.pass ? "✓" : r.bad ? "✗" : "○"}</span>
            <span className="cb-check-txt">
              <span className="t">{r.t}</span>
              <span className={"d" + (r.pass ? " bull" : r.bad ? " bear" : "")}>{r.d}</span>
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ---------- daily breakdown ---------- */
function DailyBreakdown({ m }) {
  const maxAbs = Math.max(...m.days.map((d) => Math.abs(d)), 1);
  return (
    <div className="cb-panel">
      <div className="cb-phead"><span className="k">Daily Breakdown</span><span className="r">consistency input</span></div>
      <div className="cb-days">
        {m.days.map((d, i) => {
          const isBest = d === m.bestDay && d > 0;
          const share = m.grossProfit > 0 && d > 0 ? d / m.grossProfit : 0;
          const flag = share >= 0.5;
          const w = (Math.abs(d) / maxAbs) * 50;
          const isToday = i === SCENARIOS[m.stateKey].todayIdx;
          return (
            <div className={"cb-day-row" + (isBest ? " best" : "")} key={i}>
              <span className="cb-day-date">{DAY_DATES[i]}{isToday ? <span className="today">today</span> : null}</span>
              <span className="cb-day-meter">
                <span className="mid" />
                {d >= 0 ? <span className="f bull" style={{ width: w + "%" }} /> : <span className="f bear" style={{ width: w + "%" }} />}
              </span>
              <span className={"cb-day-pnl " + (d >= 0 ? "bull" : "bear")}>{fmt2(d, true)}</span>
              <span className={"cb-day-share" + (flag ? " flag" : "")}>{d > 0 ? (share * 100).toFixed(0) + "%" : "—"}</span>
            </div>
          );
        })}
      </div>
      <div className="cb-days-foot">
        <span>Best day vs total</span>
        <span className={"best-share" + (m.bestShare >= 0.5 ? " flag" : "")}>
          {fmt2(m.bestDay, true)} · {(m.bestShare * 100).toFixed(0)}% {m.bestShare >= 0.5 ? "· over 50% ✗" : "· under 50% ✓"}
        </span>
      </div>
    </div>
  );
}

window.CombineParts = { buildModel, Hero, ProfitTarget, Checklist, DailyBreakdown, fmt, TIERS };
