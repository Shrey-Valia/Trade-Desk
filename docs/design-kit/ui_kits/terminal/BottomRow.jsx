/* Bottom panel row: OPEN POSITION · THETA SCRUBBER · KEY LEVELS · TODAY */
function BottomRow({ position, upl, scrubT, setScrubT, onClose, greeks }) {
  const d = window.TD;
  return (
    <div className="td-bottom">
      {/* OPEN POSITION */}
      <section className="bp pos">
        <div className="bp-head"><span className="k">OPEN POSITION</span><span className="r">{position ? "DTE 0" : ""}</span></div>
        {position ? (
          <div className="pos-body">
            <div className="pos-title"><span className="tri">▲</span> <b>SPY</b> Long {position.side}</div>
            <div className="pos-meta">K {position.strike} · entry 09:30 · {position.contracts} contract{position.contracts > 1 ? "s" : ""}</div>
            <div className={"pos-pnl " + (upl >= 0 ? "bull" : "bear")}>{d.fmtMoney(upl, true)}</div>
            <div className="pos-greeks">
              <span>Δ {greeks.delta}</span><span>Γ {greeks.gamma}</span>
              <span className="bear">θ {greeks.theta}</span><span>ν {greeks.vega}</span>
            </div>
            <div className="pos-be">BE <span className="be">${(position.strike + position.price).toFixed(2)}</span></div>
            <div className="pos-risk">
              <div><span className="l">MAX LOSS</span><span className="bear">−{d.fmtMoney(position.price * 100 * position.contracts).slice(1)}</span></div>
              <div className="ralign"><span className="l">MAX GAIN</span><span>unlimited</span></div>
            </div>
            <button className="pos-close" onClick={onClose}>CLOSE · REALIZE {d.fmtMoney(upl, true)}</button>
          </div>
        ) : (
          <div className="bp-empty">No open position. Click a strike → BUY to open.</div>
        )}
      </section>

      {/* THETA SCRUBBER */}
      <section className="bp scrub">
        <div className="bp-head"><span className="k">THETA SCRUBBER</span><span className="r amber">SIMULATE DECAY →</span></div>
        <div className="scrub-body">
          <div className="scrub-ends"><span>ENTRY</span><span>EXP · DTE 0</span></div>
          <input type="range" min="0" max="1" step="0.01" value={scrubT}
            disabled={!position}
            onChange={(e) => setScrubT(parseFloat(e.target.value))} className="td-slider" />
          <div className="scrub-foot">
            <span className="decay">DECAY <span className="bar"><span style={{ width: (scrubT * 100).toFixed(0) + "%" }} /></span> {(scrubT * 100).toFixed(0)}%</span>
            <button className="reset" onClick={() => setScrubT(0)} disabled={!position || scrubT === 0}>reset</button>
          </div>
          <span className="hint">BEs widen toward expiry as theta burns.</span>
        </div>
      </section>

      {/* KEY LEVELS */}
      <section className="bp levels">
        <div className="bp-head"><span className="k">KEY LEVELS</span><span className="r">SPY</span></div>
        <div className="lev-body">
          {[["EM↑", "761.20"], ["EM↓", "756.10"], ["CW", "760"], ["PW", "755"], ["MP", "758"], ["GF", "757"]].map(([k, v]) => (
            <div className="lev-row" key={k}><span className="lk">{k}</span><span className="lv">{v}</span></div>
          ))}
          <div className="lev-row ivr"><span className="lk">IV RANK</span><span className="lv amber">72</span></div>
          <div className="lev-toggle"><span>SHOW ON CHART</span><span className="sw on"><i /></span></div>
        </div>
      </section>

      {/* TODAY */}
      <section className="bp today">
        <div className="bp-head"><span className="k">TODAY</span><span className="r">{position ? d.fmtMoney(upl, true) : "$0.00"}</span></div>
        <div className="today-body">
          {position ? (
            <div className="today-row">
              <span className="tt">09:30</span>
              <span className="td-side">Long {position.side}</span>
              <span className="ts">SPY</span>
              <span className="to">— · open</span>
            </div>
          ) : (
            <div className="bp-empty">No fills today.</div>
          )}
          <div className="today-foot">VIEW FULL JOURNAL →</div>
        </div>
      </section>
    </div>
  );
}
window.TDBottom = BottomRow;
