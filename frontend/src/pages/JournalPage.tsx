import { useState } from "react";

import { PageHeader } from "@/components/layout/PageHeader";
import { TradeEntryModal } from "@/components/positions/journal/TradeEntryModal";
import { TradeList } from "@/components/positions/journal/TradeList";
import { useTrades } from "@/hooks/useTrades";
import { useSelectedTicker } from "@/stores/selectedTicker";

/**
 * Full-page journal — Step 1 of the navigation revamp.
 *
 * Reuses the existing TradeList + TradeEntryModal verbatim. The "as-is"
 * content from the bottom-of-/positions journal panel, lifted into its
 * own destination so the left rail has somewhere to point. Scope toggle
 * defaults to "all" here since the page isn't anchored to a ticker.
 *
 * The journal-→-calendar conversion is a later step in the revamp;
 * leaving content untouched per the step-1 spec.
 */
export function JournalPage() {
  const selectedSymbol = useSelectedTicker((s) => s.symbol);
  const [scope, setScope] = useState<"current" | "all">("all");
  const [modalOpen, setModalOpen] = useState(false);

  const { data } = useTrades();
  const trades = data?.trades ?? [];
  const filtered =
    scope === "all" || !selectedSymbol
      ? trades
      : trades.filter((t) => t.symbol === selectedSymbol);

  return (
    <div className="flex flex-col h-full min-h-0 bg-tier-0">
      <PageHeader title="Journal" subtitle={`${trades.length} trades`} />
      <main className="flex-1 min-h-0 border-t border-hairline">
        <TradeList
          trades={filtered}
          scope={scope}
          onScopeChange={setScope}
          selectedSymbol={selectedSymbol}
          onAddTrade={() => setModalOpen(true)}
        />
      </main>
      <TradeEntryModal open={modalOpen} onClose={() => setModalOpen(false)} />
    </div>
  );
}
