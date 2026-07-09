/* Annotated candlestick chart with the signature magenta breakeven line
   that walks as theta decays. Canvas-based for crisp hairlines. */
function TDChart({ candles, position, scrubT, timeframe }) {
  const canvasRef = React.useRef(null);
  const wrapRef = React.useRef(null);

  React.useEffect(() => {
    const canvas = canvasRef.current;
    const wrap = wrapRef.current;
    if (!canvas || !wrap) return;

    const draw = () => {
      const dpr = window.devicePixelRatio || 1;
      const W = wrap.clientWidth;
      const H = wrap.clientHeight;
      canvas.width = W * dpr;
      canvas.height = H * dpr;
      canvas.style.width = W + "px";
      canvas.style.height = H + "px";
      const ctx = canvas.getContext("2d");
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, W, H);

      const css = getComputedStyle(document.documentElement);
      const C = {
        grid: css.getPropertyValue("--td-border").trim(),
        bull: css.getPropertyValue("--td-bullish").trim(),
        bear: css.getPropertyValue("--td-bearish").trim(),
        pos: css.getPropertyValue("--td-position").trim(),
        fg2: css.getPropertyValue("--td-fg-tertiary-2").trim(),
        fg3: css.getPropertyValue("--td-fg-tertiary").trim(),
        panel: css.getPropertyValue("--td-bg-1").trim(),
      };

      const padR = 56; // price axis gutter
      const plotW = W - padR;
      const volH = H * 0.16;
      const plotH = H - volH - 8;

      let hi = -Infinity, lo = Infinity, vmax = 0;
      candles.forEach((d) => { hi = Math.max(hi, d.h); lo = Math.min(lo, d.l); vmax = Math.max(vmax, d.v); });

      // Fold position breakevens into the visible range so the magenta
      // BE line is always on-screen (positions sit near the money).
      let beTodayVals = [], beExpiryVals = [], beLabelSide = "Long call";
      if (position) {
        const premium = position.price ?? position.premium ?? 0;
        const side = position.side || "call";
        beLabelSide = side === "straddle" ? "Long straddle" : side === "put" ? "Long put" : "Long call";
        const walk = 0.18 + 0.82 * scrubT;
        if (side === "straddle") {
          beExpiryVals = [position.strike - premium, position.strike + premium];
          beTodayVals = [position.strike - premium * walk, position.strike + premium * walk];
        } else if (side === "put") {
          beExpiryVals = [position.strike - premium];
          beTodayVals = [position.strike - premium * walk];
        } else {
          beExpiryVals = [position.strike + premium];
          beTodayVals = [position.strike + premium * walk];
        }
        [...beExpiryVals, ...beTodayVals, position.strike].forEach((v) => { hi = Math.max(hi, v); lo = Math.min(lo, v); });
      }
      const pad = (hi - lo) * 0.08;
      hi += pad; lo -= pad;
      const yOf = (p) => ((hi - p) / (hi - lo)) * plotH;
      const n = candles.length;
      const step = plotW / n;
      const cw = Math.max(1.5, step * 0.62);

      // horizontal price gridlines + labels
      ctx.font = "10px 'IBM Plex Mono', monospace";
      ctx.textBaseline = "middle";
      const gridStep = 1; // $1
      const startG = Math.ceil(lo);
      ctx.strokeStyle = C.grid; ctx.lineWidth = 1;
      for (let p = startG; p <= hi; p += gridStep) {
        if (p % 1 !== 0) continue;
        const y = yOf(p);
        if (p % 1 === 0 && p % 1 < 0.001) {
          ctx.globalAlpha = 0.35;
          ctx.beginPath(); ctx.moveTo(0, y + 0.5); ctx.lineTo(plotW, y + 0.5); ctx.stroke();
          ctx.globalAlpha = 1;
        }
        ctx.fillStyle = C.fg3;
        ctx.textAlign = "left";
        ctx.fillText(p.toFixed(2), plotW + 6, y);
      }

      // volume bars
      candles.forEach((d, i) => {
        const x = i * step + step / 2;
        const up = d.c >= d.o;
        const bh = (d.v / vmax) * (volH - 4);
        ctx.fillStyle = up ? C.bull : C.bear;
        ctx.globalAlpha = 0.5;
        ctx.fillRect(x - cw / 2, H - bh, cw, bh);
        ctx.globalAlpha = 1;
      });

      // candles
      candles.forEach((d, i) => {
        const x = i * step + step / 2;
        const up = d.c >= d.o;
        const col = up ? C.bull : C.bear;
        ctx.strokeStyle = col; ctx.fillStyle = col; ctx.lineWidth = 1;
        // wick
        ctx.beginPath();
        ctx.moveTo(Math.round(x) + 0.5, yOf(d.h));
        ctx.lineTo(Math.round(x) + 0.5, yOf(d.l));
        ctx.stroke();
        // body
        const yo = yOf(d.o), yc = yOf(d.c);
        const top = Math.min(yo, yc);
        const bh = Math.max(1, Math.abs(yc - yo));
        ctx.fillRect(x - cw / 2, top, cw, bh);
      });

      // last price tag
      const last = candles[n - 1].c;
      const ly = yOf(last);
      ctx.fillStyle = C.bull;
      ctx.fillRect(plotW, ly - 8, padR, 16);
      ctx.fillStyle = "#0c0f16";
      ctx.font = "500 10px 'IBM Plex Mono', monospace";
      ctx.textAlign = "center";
      ctx.fillText(last.toFixed(2), plotW + padR / 2, ly);

      // ---- POSITION OVERLAY (the differentiator) ----
      if (position) {
        const { entryIndex } = position;
        const ex = entryIndex * step + step / 2;
        const ey = yOf(candles[entryIndex].l) + 18;

        // faint expiry-BE ghost line(s) — where the BE is walking toward
        ctx.strokeStyle = C.pos; ctx.lineWidth = 1;
        beExpiryVals.forEach((be) => {
          const gy = yOf(be);
          ctx.globalAlpha = 0.28;
          ctx.setLineDash([2, 4]);
          ctx.beginPath(); ctx.moveTo(0, gy + 0.5); ctx.lineTo(plotW, gy + 0.5); ctx.stroke();
        });
        ctx.setLineDash([]); ctx.globalAlpha = 1;

        // today BE line(s) — magenta dashed, walk with the scrubber
        ctx.font = "500 10px 'IBM Plex Mono', monospace";
        beTodayVals.forEach((be, idx) => {
          const by = yOf(be);
          ctx.strokeStyle = C.pos; ctx.lineWidth = 1.5;
          ctx.setLineDash([5, 4]);
          ctx.beginPath(); ctx.moveTo(0, by + 0.5); ctx.lineTo(plotW, by + 0.5); ctx.stroke();
          ctx.setLineDash([]);
          const beLabel = "BE $" + be.toFixed(2);
          const lw = ctx.measureText(beLabel).width + 12;
          ctx.fillStyle = C.pos;
          ctx.fillRect(plotW - lw, by - 8, lw, 16);
          ctx.fillStyle = "#fff"; ctx.textAlign = "center";
          ctx.fillText(beLabel, plotW - lw / 2, by);
        });

        // entry triangle marker
        ctx.fillStyle = C.pos;
        ctx.beginPath();
        ctx.moveTo(ex, ey - 6);
        ctx.lineTo(ex - 5, ey + 3);
        ctx.lineTo(ex + 5, ey + 3);
        ctx.closePath(); ctx.fill();
        ctx.font = "10px 'IBM Plex Mono', monospace";
        ctx.fillStyle = C.pos; ctx.textAlign = "left";
        ctx.fillText("ENTRY · " + beLabelSide, ex + 9, ey + 1);
      }
    };

    draw();
    const ro = new ResizeObserver(draw);
    ro.observe(wrap);
    return () => ro.disconnect();
  }, [candles, position, scrubT, timeframe]);

  return (
    <div ref={wrapRef} style={{ position: "absolute", inset: 0 }}>
      <canvas ref={canvasRef} />
    </div>
  );
}
window.TDChart = TDChart;
