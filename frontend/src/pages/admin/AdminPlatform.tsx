import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { LoadError } from "@/components/ui/LoadError";
import {
  adminKeys,
  errorMessage,
  fetchPlatform,
  TRADING_MODES,
  updatePlatform,
  type TradingMode,
} from "@/lib/adminApi";
import { toast } from "@/stores/toast";

import { ActionModal, Btn, Chip, INPUT_CLS, Panel } from "./adminUi";

/**
 * Platform — the incident kill switch. One glance answers "what mode is
 * trading in RIGHT NOW"; one click (plus a confirm for halt) changes it.
 * Deliberately DB-only server-side, so this works exactly when the market
 * data feed is the thing that broke. Polls every 10s so two operators see
 * each other's flips.
 */

const MODE_META: Record<
  TradingMode,
  { label: string; blurb: string; banner: string; active: string }
> = {
  normal: {
    label: "Normal",
    blurb: "Opens and closes allowed",
    banner: "text-bullish border-bullish",
    active: "bg-tier-2 border-bullish text-bullish",
  },
  close_only: {
    label: "Close only",
    blurb: "New opens rejected — exits still allowed",
    banner: "text-warning border-warning",
    active: "bg-tier-2 border-warning text-warning",
  },
  halted: {
    label: "Halted",
    blurb: "ALL order flow stops — entry fills too",
    banner: "text-breach border-breach",
    active: "bg-tier-2 border-breach text-breach",
  },
};

export function AdminPlatform() {
  const qc = useQueryClient();
  const [confirmMode, setConfirmMode] = useState<TradingMode | null>(null);
  const [symbolInput, setSymbolInput] = useState("");

  const platform = useQuery({
    queryKey: adminKeys.platform,
    queryFn: fetchPlatform,
    staleTime: 5_000,
    refetchInterval: 10_000,
  });

  const put = useMutation({
    mutationFn: updatePlatform,
    onSuccess: (state) => {
      toast.success(
        `Platform updated — mode ${state.trading_mode.replace("_", " ")}, ${state.banned_symbols.length} banned symbol${state.banned_symbols.length === 1 ? "" : "s"}.`,
      );
      // Seed the fresh truth immediately; invalidation follows for rigor.
      qc.setQueryData(adminKeys.platform, state);
      setConfirmMode(null);
    },
    onError: (e) => toast.error(errorMessage(e)),
    onSettled: () => {
      qc.invalidateQueries({ queryKey: adminKeys.platform });
      qc.invalidateQueries({ queryKey: adminKeys.actionsPrefix });
    },
  });

  if (platform.isPending) {
    return (
      <div className="px-1 py-6 text-tiny text-fg-tertiary-2">
        Loading platform state…
      </div>
    );
  }
  if (platform.isError) {
    return <LoadError subject="platform state" onRetry={platform.refetch} />;
  }
  const state = platform.data;
  const mode = (
    TRADING_MODES.includes(state.trading_mode as TradingMode)
      ? state.trading_mode
      : "normal"
  ) as TradingMode;
  const meta = MODE_META[mode];

  const setMode = (next: TradingMode) => {
    if (next === mode || put.isPending) return;
    // Both restrictive modes stop new opens platform-wide — confirm either. Only
    // a return to "normal" (loosening) fires directly.
    if (next === "halted" || next === "close_only") {
      setConfirmMode(next);
      return;
    }
    put.mutate({ trading_mode: next });
  };

  const addSymbol = () => {
    const sym = symbolInput.trim().toUpperCase();
    if (!sym || put.isPending) return;
    if (!/^[A-Z.]{1,8}$/.test(sym)) {
      toast.error(`"${sym}" doesn't look like a symbol.`);
      return;
    }
    if (state.banned_symbols.includes(sym)) {
      toast.info(`${sym} is already banned.`);
      setSymbolInput("");
      return;
    }
    put.mutate({ banned_symbols: [...state.banned_symbols, sym] });
    setSymbolInput("");
  };

  const removeSymbol = (sym: string) => {
    if (put.isPending) return;
    put.mutate({ banned_symbols: state.banned_symbols.filter((s) => s !== sym) });
  };

  return (
    <div className="flex flex-col gap-3.5" style={{ maxWidth: 760 }}>
      {/* current state banner — unambiguous, big */}
      <div
        className={`border bg-tier-1 px-4 py-3.5 flex items-center gap-4 ${meta.banner}`}
        style={{ borderRadius: 4 }}
      >
        <div className="flex flex-col gap-0.5 min-w-0">
          <span
            className="uppercase tracking-label-up text-fg-tertiary-2"
            style={{ fontSize: 11 }}
          >
            Trading mode
          </span>
          <span className="font-display font-bold uppercase tracking-label-up text-display leading-7">
            {meta.label}
          </span>
          <span className="text-tiny text-fg-secondary normal-case">{meta.blurb}</span>
        </div>
        {mode !== "normal" && (
          <span aria-hidden className="ml-auto text-display leading-none">
            ⚠
          </span>
        )}
      </div>

      <Panel label="Set trading mode">
        <div className="px-3 py-3 flex flex-col gap-2">
          <div className="flex gap-0" role="group" aria-label="Trading mode">
            {TRADING_MODES.map((m, i) => {
              const mm = MODE_META[m];
              const isActive = m === mode;
              return (
                <button
                  key={m}
                  type="button"
                  disabled={put.isPending}
                  onClick={() => setMode(m)}
                  aria-pressed={isActive}
                  className={[
                    "h-9 px-4 uppercase tracking-label-up border font-medium",
                    "disabled:opacity-60 transition-colors duration-100",
                    i > 0 ? "-ml-px" : "",
                    isActive
                      ? mm.active
                      : "bg-tier-1 border-hairline-strong text-fg-tertiary-2 hover:text-fg-primary hover:bg-tier-2",
                  ].join(" ")}
                  style={{
                    fontSize: 12,
                    borderRadius:
                      i === 0
                        ? "4px 0 0 4px"
                        : i === TRADING_MODES.length - 1
                          ? "0 4px 4px 0"
                          : 0,
                  }}
                >
                  {mm.label}
                </button>
              );
            })}
          </div>
          <span className="text-tiny text-fg-tertiary">
            Takes effect on the next order check — no restart, no market-data
            dependency. Halting is confirmed; every flip is audited.
          </span>
        </div>
      </Panel>

      <Panel label={<>Banned symbols <span className="normal-case text-fg-tertiary-2 tabular-nums">· {state.banned_symbols.length}</span></>}>
        <div className="px-3 py-3 flex flex-col gap-2.5">
          <div className="flex gap-1.5 flex-wrap">
            {state.banned_symbols.length === 0 ? (
              <span className="text-tiny text-fg-tertiary-2">
                No per-symbol bans in force.
              </span>
            ) : (
              state.banned_symbols.map((sym) => (
                <span
                  key={sym}
                  className="inline-flex items-center gap-1 border border-bearish text-bearish px-1.5 uppercase tabular-nums"
                  style={{ fontSize: 12, borderRadius: 2, height: 24 }}
                >
                  {sym}
                  <button
                    type="button"
                    onClick={() => removeSymbol(sym)}
                    disabled={put.isPending}
                    aria-label={`Unban ${sym}`}
                    className="hover:text-fg-primary disabled:opacity-50"
                  >
                    ✕
                  </button>
                </span>
              ))
            )}
          </div>
          <form
            className="flex gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              addSymbol();
            }}
          >
            <input
              type="text"
              value={symbolInput}
              onChange={(e) => setSymbolInput(e.target.value.toUpperCase())}
              placeholder="SYMBOL"
              className={`${INPUT_CLS} w-32 uppercase tabular-nums`}
              style={{ fontSize: 12 }}
            />
            <Btn kind="danger" type="submit" disabled={put.isPending || !symbolInput.trim()}>
              Ban symbol
            </Btn>
          </form>
        </div>
      </Panel>

      <Panel
        label={
          <>
            0DTE universe{" "}
            <span className="normal-case text-fg-tertiary-2">
              · {state.enforce_tradeable_universe ? "enforced at open" : "NOT enforced"}
            </span>
          </>
        }
      >
        <div className="px-3 py-3 flex flex-col gap-2">
          <div className="flex gap-1.5 flex-wrap">
            {state.zero_dte_universe.map((sym) => (
              <Chip
                key={sym}
                tone={state.banned_symbols.includes(sym) ? "bearish" : "neutral"}
                title={state.banned_symbols.includes(sym) ? "Currently banned" : undefined}
              >
                {sym}
              </Chip>
            ))}
          </div>
          <span className="text-tiny text-fg-tertiary">
            Configured via settings (read-only here). Banned symbols above
            override it symbol-by-symbol.
          </span>
        </div>
      </Panel>

      <ActionModal
        open={confirmMode === "halted" || confirmMode === "close_only"}
        onClose={() => setConfirmMode(null)}
        title={
          confirmMode === "close_only"
            ? "Switch to close-only?"
            : "Halt all trading?"
        }
        description={
          confirmMode === "close_only"
            ? "Every new open is rejected platform-wide (exits still allowed) until an operator restores normal mode."
            : "Every open AND close is rejected platform-wide, and the order monitor stops filling entries, until an operator restores normal or close-only mode. Use close-only unless positions themselves are the hazard."
        }
        confirmLabel={confirmMode === "close_only" ? "Close-only mode" : "Halt trading"}
        confirmKind="danger"
        pending={put.isPending}
        onConfirm={() =>
          put.mutate({ trading_mode: confirmMode ?? "halted" })
        }
      />
    </div>
  );
}
