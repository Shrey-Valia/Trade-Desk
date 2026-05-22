import { CalendarStrip } from "@/components/layout/CalendarStrip";
import { StockDetailView } from "@/components/stock/StockDetailView";
import { WatchlistColumn } from "@/components/watchlist/WatchlistColumn";

export function DashboardPage() {
  return (
    <>
      <CalendarStrip />
      <div className="flex flex-1 min-h-0">
        <WatchlistColumn />
        <StockDetailView />
      </div>
    </>
  );
}
