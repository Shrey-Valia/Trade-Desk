import { useState } from "react";

import { LiveFeed } from "@/components/positions/LiveFeed";
import { NewsPanel } from "@/components/positions/NewsPanel";

type Tab = "news" | "feed";

/**
 * Bottom-strip panel that toggles between NEWS (ticker headlines) and
 * FEED (the unified market-pulse + fills tape). Used at BOTH bottom-strip
 * mount sites; tab state is local because the no-position box and the
 * active-position col5 are never shown at the same time.
 *
 * The NEWS/FEED segmented control is rendered into each panel's shared
 * PanelHeader right slot (via `headerControl`), so the toggle sits inline
 * with the panel title and no extra chrome row is added.
 */
export function BottomNewsFeedTabs({ symbol }: { symbol: string | null }) {
  const [tab, setTab] = useState<Tab>("news");
  const toggle = <SegToggle tab={tab} onChange={setTab} />;
  return tab === "news" ? (
    <NewsPanel symbol={symbol} headerControl={toggle} />
  ) : (
    <LiveFeed headerControl={toggle} />
  );
}

function SegToggle({ tab, onChange }: { tab: Tab; onChange: (t: Tab) => void }) {
  return (
    <span className="flex items-center gap-1" style={{ fontSize: 9 }}>
      <SegButton active={tab === "news"} onClick={() => onChange("news")}>
        News
      </SegButton>
      <span className="text-fg-tertiary" aria-hidden>
        ·
      </span>
      <SegButton active={tab === "feed"} onClick={() => onChange("feed")}>
        Feed
      </SegButton>
    </span>
  );
}

function SegButton({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={`uppercase tracking-label-up transition-colors duration-100 ${
        active ? "text-amber" : "text-fg-tertiary-2 hover:text-amber"
      }`}
    >
      {children}
    </button>
  );
}
