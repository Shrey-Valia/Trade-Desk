/* Trade Desk terminal — mock data + helpers (plain JS globals). */
(function () {
  // Deterministic PRNG so the chart is stable across renders.
  function mulberry32(a) {
    return function () {
      a |= 0; a = (a + 0x6D2B79F5) | 0;
      let t = Math.imul(a ^ (a >>> 15), 1 | a);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }

  // Generate ~130 candles of SPY-ish 5m data drifting up into the 758–760 zone.
  function genCandles(n) {
    const rnd = mulberry32(424242);
    const out = [];
    let price = 750.4;
    for (let i = 0; i < n; i++) {
      const drift = 0.012 + Math.sin(i / 14) * 0.05;
      const vol = 0.22 + rnd() * 0.28;
      const o = price;
      const move = (rnd() - 0.48) * vol + drift * 0.5;
      let c = o + move;
      // a couple of impulse legs for character
      if (i === 28) c = o + 1.7;
      if (i === 96) c = o + 1.3;
      const hi = Math.max(o, c) + rnd() * vol * 0.9;
      const lo = Math.min(o, c) - rnd() * vol * 0.9;
      const v = 0.4 + rnd() * (i % 17 === 0 ? 2.4 : 1);
      out.push({ o, h: hi, l: lo, c, v });
      price = c;
    }
    return out;
  }

  const CANDLES = genCandles(130);
  const SPOT = CANDLES[CANDLES.length - 1].c;

  // Option chain around ATM 759 (0DTE, indicative pricing).
  function genChain(spot) {
    const atm = Math.round(spot);
    const rows = [];
    for (let k = atm - 5; k <= atm + 5; k++) {
      // crude intrinsic + time-value model for a 0DTE feel
      const callIntrinsic = Math.max(0, spot - k);
      const putIntrinsic = Math.max(0, k - spot);
      const tv = Math.max(0.02, 0.9 - Math.abs(k - spot) * 0.16);
      const call = +(callIntrinsic + tv).toFixed(2);
      const put = +(putIntrinsic + tv).toFixed(2);
      const isAtm = k === atm;
      // strikes far OTM fall back to model pricing
      const far = Math.abs(k - spot) > 3;
      rows.push({
        strike: k,
        call: +Math.max(0.01, call).toFixed(2),
        put: +Math.max(0.01, put).toFixed(2),
        isAtm,
        callSource: far && k > spot ? "bs" : "quote",
        putSource: far && k < spot ? "bs" : "quote",
      });
    }
    return { rows, atm, spot, iv: 0.77, expiry: "2026-06-01" };
  }

  window.TD = {
    CANDLES,
    SPOT,
    CHAIN: genChain(SPOT),
    fmtMoney(v, signed) {
      if (!isFinite(v)) return "—";
      const s = signed ? (v > 0 ? "+" : v < 0 ? "−" : "") : v < 0 ? "−" : "";
      return s + "$" + Math.abs(v).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    },
    fmtPct(v) {
      const s = v > 0 ? "+" : v < 0 ? "−" : "";
      return s + Math.abs(v).toFixed(2) + "%";
    },
  };
})();
