/* Terminal chrome — Rail, Header, ChainPanel, TradeTicket, BottomRow.
   Self-contained (attached to window) so the kit runs without the DS
   bundle; visuals mirror the design-system primitives 1:1. */

const ICONS = {
  chart: <g><line x1="6" y1="3" x2="6" y2="17"/><rect x="4" y="6" width="4" height="7" fill="currentColor"/><line x1="14" y1="3" x2="14" y2="17"/><rect x="12" y="8" width="4" height="5"/></g>,
  journal: <g><path d="M4 4h9a2 2 0 0 1 2 2v11H6a2 2 0 0 1-2-2V4z"/><line x1="7" y1="8" x2="12" y2="8"/><line x1="7" y1="11" x2="12" y2="11"/><line x1="7" y1="14" x2="10" y2="14"/></g>,
  analytics: <g><line x1="3" y1="17" x2="17" y2="17"/><rect x="4" y="11" width="3" height="6"/><rect x="9" y="7" width="3" height="10"/><rect x="14" y="4" width="3" height="13"/></g>,
  watchlist: <g><circle cx="4.5" cy="5.5" r="1" fill="currentColor" stroke="none"/><line x1="8" y1="5.5" x2="17" y2="5.5"/><circle cx="4.5" cy="10" r="1" fill="currentColor" stroke="none"/><line x1="8" y1="10" x2="17" y2="10"/><circle cx="4.5" cy="14.5" r="1" fill="currentColor" stroke="none"/><line x1="8" y1="14.5" x2="17" y2="14.5"/></g>,
  settings: <g><circle cx="10" cy="10" r="2.5"/><path d="M10 2.5v2M10 15.5v2M2.5 10h2M15.5 10h2M4.7 4.7l1.4 1.4M13.9 13.9l1.4 1.4M4.7 15.3l1.4-1.4M13.9 6.1l1.4-1.4"/></g>,
};
function Glyph({ name, size = 20 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 20 20" fill="none" stroke="currentColor"
      strokeWidth={1.5} strokeLinecap="round" strokeLinejoin="round">{ICONS[name]}</svg>
  );
}

function Rail({ active, onNav }) {
  const items = [["chart", "Chart"], ["journal", "Journal"], ["analytics", "Analytics"], ["watchlist", "Watch"]];
  return (
    <nav className="td-rail">
      <div className="td-rail-mark">
        <svg viewBox="0 0 36 36" width="32" height="32">
          <rect x="1" y="1" width="34" height="34" rx="5" ry="5" fill="none" stroke="var(--td-amber)" strokeWidth="2"/>
          <text x="18" y="18" textAnchor="middle" dominantBaseline="central" fontFamily="var(--td-font-mono)" fontSize="20" fontWeight="500" letterSpacing="-0.02em" fill="var(--td-fg-primary)">TD</text>
        </svg>
      </div>
      {items.map(([key, label]) => (
        <button key={key} className={"td-rail-btn" + (active === key ? " active" : "")} onClick={() => onNav(key)} title={label}>
          <Glyph name={key} />
          <span>{label}</span>
        </button>
      ))}
      <button className="td-rail-btn td-rail-foot" title="Settings"><Glyph name="settings" /><span>Settings</span></button>
    </nav>
  );
}

function Header({ position, upl }) {
  const d = window.TD;
  const detail = d.CANDLES[d.CANDLES.length - 1];
  const prev = d.CANDLES[0].o;
  const chg = detail.c - prev;
  const chgPct = (chg / prev) * 100;
  const bal = 50000 + (upl || 0);
  const pills = [
    { label: "BAL", value: d.fmtMoney(bal) },
    { label: "MLL", value: d.fmtMoney(48000) },
    { label: "DLL", value: "$0 / $1,500" },
    { label: "RP&L", value: d.fmtMoney(0), tone: "default" },
    { label: "UP&L", value: d.fmtMoney(upl || 0, true), signed: upl || 0 },
  ];
  return (
    <header className="td-header">
      <button className="td-tier">50K Combine <span className="caret">▾</span></button>
      <div className="td-search">
        <span className="mag">⌕</span>
        <span className="sym">SPY</span>
        <span className="ph">· search ticker…</span>
      </div>
      <div className="td-price">
        <span className="lbl">SPY</span>
        <span className="val">{d.fmtMoney(detail.c)}</span>
        <span className={chg >= 0 ? "bull" : "bear"}>{chg >= 0 ? "+" : "−"}{Math.abs(chg).toFixed(2)} ({d.fmtPct(chgPct)})</span>
      </div>
      <div className="td-pills">
        {pills.map((p) => {
          const tone = p.signed !== undefined ? (p.signed > 0 ? "bull" : p.signed < 0 ? "bear" : "") : "";
          return (
            <div className="td-pill" key={p.label}>
              <span className="lbl">{p.label}</span>
              <span className={"val " + tone}>{p.value}</span>
            </div>
          );
        })}
        <div className="td-pill mkt">
          <span className="lbl">MKT</span>
          <span className="val bear">CLOSED <span className="sep">·</span><span className="lc">until 09:30 et</span></span>
        </div>
      </div>
    </header>
  );
}

function ChainPanel({ chain, action, onPick }) {
  const rowsRef = React.useRef(null);
  React.useEffect(() => {
    const el = rowsRef.current;
    if (!el) return;
    const atm = el.querySelector(".td-row.atm");
    if (atm) el.scrollTop = atm.offsetTop - el.clientHeight / 2 + atm.clientHeight / 2;
  }, []);
  return (
    <div className="td-chain">
      <div className="td-chain-head">
        <span className="k">OPTION CHAIN</span>
        <span className="v">SPY</span>
        <span className="t">0DTE · exp {chain.expiry}</span>
        <span className="t">SPOT ${chain.spot.toFixed(2)}</span>
        <span className="t">ATM ${chain.atm}</span>
        <span className="t">IV {(chain.iv * 100).toFixed(0)}%</span>
        <span className="tag">indicative pricing</span>
      </div>
      <div className="td-chain-col"><span>Call</span><span>Strike</span><span>Put</span></div>
      <div className="td-chain-rows" ref={rowsRef}>
        {chain.rows.map((r) => (
          <div key={r.strike} className={"td-row" + (r.isAtm ? " atm" : "")}>
            <button className={"cell r " + (r.callSource === "bs" ? "dim" : "")} onClick={() => onPick({ strike: r.strike, side: "call", price: r.call })}>
              {r.call.toFixed(2)}{r.callSource === "bs" && <span className="m">·m</span>}
            </button>
            <button className={"strike" + (r.isAtm ? " atm" : "")} onClick={() => onPick({ strike: r.strike, side: r.isAtm ? "straddle" : "call", price: r.isAtm ? +(r.call + r.put).toFixed(2) : r.call })}>{r.strike}</button>
            <button className={"cell l " + (r.putSource === "bs" ? "dim" : "")} onClick={() => onPick({ strike: r.strike, side: "put", price: r.put })}>
              {r.put.toFixed(2)}{r.putSource === "bs" && <span className="m">·m</span>}
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}

function TradeTicket({ selection, qty, setQty, onFire, marketOpen }) {
  const presets = [1, 3, 5, 10, 15];
  const cost = selection ? selection.price * 100 * qty : 0;
  const kind = selection ? (selection.side === "straddle" ? "STRADDLE" : selection.side.toUpperCase()) : "";
  const be = selection ? (selection.side === "put" ? selection.strike - selection.price : selection.strike + selection.price) : 0;
  return (
    <div className="td-ticket">
      <div className="td-ticket-head"><span className="k">TRADE TICKET</span><span className="hint">selected from chain ↑</span></div>
      {selection ? (
        <React.Fragment>
          <div className="td-ticket-sum">
            <span className="big">{selection.strike} {kind}</span>
            <span className="u">est.</span>
            <span className="s">{window.TD.fmtMoney(cost)} debit</span>
            <span className="u">be</span>
            <span className="be">${be.toFixed(2)}</span>
          </div>
          <div className="td-qty">
            <div className="stepper">
              <button onClick={() => setQty(Math.max(1, qty - 1))} disabled={qty <= 1}>−</button>
              <div className="val">{qty}</div>
              <button onClick={() => setQty(qty + 1)}>+</button>
            </div>
            <div className="chips">
              {presets.map((n) => (
                <button key={n} className={"chip" + (qty === n ? " on" : "")} onClick={() => setQty(n)}>{n}</button>
              ))}
            </div>
          </div>
        </React.Fragment>
      ) : (
        <div className="td-ticket-empty">{marketOpen ? "Click a strike in the chain ↑" : "market closed"}</div>
      )}
      <div className="td-actions">
        <button className={"act buy" + (selection ? "" : " off")} onClick={() => selection && onFire("buy")} disabled={!selection}>
          <span className="l">BUY +{selection ? qty : ""}</span>
          <span className="sb">{selection ? `long ${selection.side} · ${window.TD.fmtMoney(cost)} debit` : "pick a strike ↑"}</span>
        </button>
        <button className={"act sell" + (selection ? "" : " off")} onClick={() => selection && onFire("sell")} disabled={!selection}>
          <span className="l">SELL -{selection ? qty : ""}</span>
          <span className="sb">{selection ? `short ${selection.side} · ${window.TD.fmtMoney(cost)} credit` : "pick a strike ↑"}</span>
        </button>
      </div>
    </div>
  );
}

window.TDPanels = { Rail, Header, ChainPanel, TradeTicket, Glyph };
