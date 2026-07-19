import type { Trade } from "@/types/journal";

/**
 * Client-side CSV export for the journal — no backend round-trip, the
 * rows on screen are the rows in the file.
 *
 * One row per trade; legs are compacted into a single readable cell
 * ("buy 15x 737C @ 1.02 exp 2026-06-09 | …") rather than exploded into
 * a row per leg, so the file opens cleanly as a flat trade ledger in
 * Excel/Sheets.
 */
export function tradesToCsv(trades: Trade[]): string {
  const header = [
    "id",
    "symbol",
    "strategy",
    "status",
    "account",
    "tier",
    "entry_date",
    "exit_date",
    "entry_underlying",
    "exit_underlying",
    "net_debit_credit",
    "realized_pnl",
    "r_multiple",
    "confidence",
    "legs",
    "tags",
    "mistake_tags",
    "thesis",
    "planned_exit",
    "risk_amount",
    "notes",
    "review_note",
  ];
  const rows = trades.map((t) => [
    String(t.id),
    t.symbol,
    t.strategy,
    t.status,
    t.is_paper ? "paper" : "live",
    t.tier,
    t.entry_date,
    t.exit_date ?? "",
    numCell(t.entry_underlying_price),
    numCell(t.exit_underlying_price),
    numCell(t.net_debit_credit),
    numCell(t.realized_pnl),
    numCell(t.r_multiple),
    t.confidence != null ? String(t.confidence) : "",
    t.legs.map(legLabel).join(" | "),
    t.tags.join("; "),
    t.mistake_tags.join("; "),
    t.thesis ?? "",
    t.planned_exit ?? "",
    numCell(t.risk_amount),
    t.notes ?? "",
    t.review_note ?? "",
  ]);
  return [header, ...rows]
    .map((cells) => cells.map(escapeCsvCell).join(","))
    .join("\r\n");
}

/**
 * Executions (fills) export — one row per EXECUTION rather than per trade:
 * every leg's entry fill (price, size, underlying, timestamp), plus one
 * close row per closed position (per-leg exit fills aren't persisted; the
 * close row carries the exit underlying, close reason and realized P&L).
 * The reconciliation-grade view the flat trade ledger can't give.
 */
export function executionsToCsv(trades: Trade[]): string {
  const header = [
    "trade_id",
    "symbol",
    "account",
    "event",
    "action",
    "type",
    "strike",
    "expiry",
    "contracts",
    "price",
    "underlying",
    "timestamp",
    "close_reason",
    "realized_pnl",
  ];
  const rows: string[][] = [];
  for (const t of trades) {
    if (t.status === "cancelled") continue;
    const wasFilled = t.status === "open" || t.status === "closed";
    if (!wasFilled) continue;
    for (const l of t.legs) {
      rows.push([
        String(t.id),
        t.symbol,
        t.is_paper ? "paper" : "live",
        "entry",
        l.action,
        l.side,
        String(l.strike),
        l.expiry,
        String(l.contracts ?? 1),
        numCell(l.entry_price),
        numCell(t.entry_underlying_price),
        t.entry_date,
        "",
        "",
      ]);
    }
    if (t.status === "closed") {
      rows.push([
        String(t.id),
        t.symbol,
        t.is_paper ? "paper" : "live",
        "close",
        "",
        "",
        "",
        "",
        "",
        "",
        numCell(t.exit_underlying_price),
        t.exit_date ?? "",
        t.close_reason ?? "",
        numCell(t.realized_pnl),
      ]);
    }
  }
  return [header, ...rows]
    .map((cells) => cells.map(escapeCsvCell).join(","))
    .join("\r\n");
}

function legLabel(l: Trade["legs"][number]): string {
  const k = `${l.strike}${l.side === "call" ? "C" : "P"}`;
  return `${l.action} ${l.contracts}x ${k} @ ${l.entry_price} exp ${l.expiry}`;
}

function numCell(v: number | null | undefined): string {
  return v == null || !Number.isFinite(v) ? "" : String(v);
}

/** RFC 4180: quote any cell containing comma, quote, or newline;
 * double internal quotes. Leading =/+/-/@ on non-numeric cells get a
 * tab prefix to defuse spreadsheet formula injection from free-text
 * fields (plain negative numbers stay parseable). */
function escapeCsvCell(raw: string): string {
  let s = raw;
  if (/^[=+\-@]/.test(s) && !/^-?\d+(\.\d+)?$/.test(s)) s = `\t${s}`;
  if (/[",\r\n]/.test(s)) s = `"${s.replace(/"/g, '""')}"`;
  return s;
}

/** Trigger a browser download of the given CSV text. */
export function downloadCsv(filename: string, csv: string): void {
  const blob = new Blob(["﻿" + csv], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}
