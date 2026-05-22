"""Static ticker → sector ETF mapping. Used by the sector_etf_return_5d feature.

ETFs map to themselves (SPY, QQQ) — they don't have earnings so they never
appear as feature targets, but the lookup is harmless.
"""

TICKER_TO_SECTOR_ETF: dict[str, str] = {
    # Watchlist universe
    "NVDA": "XLK", "AAPL": "XLK", "MSFT": "XLK", "AMD": "XLK", "META": "XLC",
    "GOOGL": "XLC", "AMZN": "XLY", "TSLA": "XLY", "PLTR": "XLK", "SMCI": "XLK",
    "BA": "XLI", "INTC": "XLK", "F": "XLY",
    "QQQ": "QQQ", "SPY": "SPY",
    # Training universe (~35 names)
    "JNJ": "XLV", "PG": "XLP", "KO": "XLP", "WMT": "XLP", "V": "XLF", "MA": "XLF",
    "COST": "XLP", "UNH": "XLV",
    "NFLX": "XLC", "CRM": "XLK", "ADBE": "XLK", "ORCL": "XLK",
    "COIN": "XLF", "RBLX": "XLC", "SNAP": "XLC", "U": "XLK", "RIVN": "XLY", "AFRM": "XLF",
    "JPM": "XLF", "BAC": "XLF", "GS": "XLF", "MS": "XLF", "C": "XLF", "WFC": "XLF",
    "PFE": "XLV", "MRK": "XLV", "LLY": "XLV", "ABBV": "XLV", "BMY": "XLV",
    "CAT": "XLI", "DE": "XLI", "HD": "XLY", "LOW": "XLY", "NKE": "XLY", "SBUX": "XLY",
}

# All sector ETFs we need to cache daily bars for. Plus VIX as a separate macro.
SECTOR_ETFS: tuple[str, ...] = tuple(sorted(set(TICKER_TO_SECTOR_ETF.values())))
VIX_SYMBOL = "^VIX"


def sector_etf_for(symbol: str) -> str | None:
    return TICKER_TO_SECTOR_ETF.get(symbol)
