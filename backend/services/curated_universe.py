"""Curated 0DTE-tradeable ticker universe.

Replaces the prior 10K-symbol live-Alpaca catalog with a small,
hand-curated list of names that:
  - have liquid 0DTE option chains on Alpaca's free tier, or
  - are high-volume single-name equities that retail Trade Desk users
    actively trade.

The Phase-1 search rework swapped a 16-symbol hardcoded list for the
full Alpaca asset universe (~13K symbols). That was the right move
for "real search", but real users on a 0DTE-focused product don't
need to search 13K symbols — 99% of selections land on a small set
of liquid names. A curated universe also sidesteps the
non-tradeable-symbol problem (delisted issues, halted tickers, weird
ADRs that 404 the chart) without per-symbol exclusion lists.

The denylist for cash-settled indices (SPX / NDX / VIX / RUT etc.)
in `symbol_catalog._INDEX_DENYLIST` remains in place as defense in
depth — even if an index name accidentally lands here, search will
still filter it out.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

CuratedCategory = Literal["etf", "equity"]


@dataclass(frozen=True)
class CuratedEntry:
    symbol: str
    name: str
    category: CuratedCategory


# 30 tickers — broad ETFs + the most liquid 0DTE-capable single names.
# No indices: SPX / NDX / VIX are cash-settled CBOE products with no
# bars endpoint on Alpaca's free tier (see yesterday's index-filter
# commit `f9bd590`).
CURATED_UNIVERSE: tuple[CuratedEntry, ...] = (
    # Broad-market ETFs
    CuratedEntry("SPY", "SPDR S&P 500 ETF", "etf"),
    CuratedEntry("QQQ", "Invesco QQQ Trust", "etf"),
    CuratedEntry("IWM", "iShares Russell 2000 ETF", "etf"),
    CuratedEntry("DIA", "SPDR Dow Jones Industrial Average ETF", "etf"),
    # Mega-cap tech
    CuratedEntry("AAPL", "Apple Inc.", "equity"),
    CuratedEntry("MSFT", "Microsoft Corporation", "equity"),
    CuratedEntry("NVDA", "NVIDIA Corporation", "equity"),
    CuratedEntry("TSLA", "Tesla, Inc.", "equity"),
    CuratedEntry("AMD", "Advanced Micro Devices, Inc.", "equity"),
    CuratedEntry("GOOGL", "Alphabet Inc. (Class A)", "equity"),
    CuratedEntry("AMZN", "Amazon.com, Inc.", "equity"),
    CuratedEntry("META", "Meta Platforms, Inc.", "equity"),
    CuratedEntry("NFLX", "Netflix, Inc.", "equity"),
    CuratedEntry("AVGO", "Broadcom Inc.", "equity"),
    # Crypto-adjacent + high-beta retail names
    CuratedEntry("COIN", "Coinbase Global, Inc.", "equity"),
    CuratedEntry("MSTR", "MicroStrategy Incorporated", "equity"),
    CuratedEntry("PLTR", "Palantir Technologies Inc.", "equity"),
    CuratedEntry("SMCI", "Super Micro Computer, Inc.", "equity"),
    CuratedEntry("MU", "Micron Technology, Inc.", "equity"),
    CuratedEntry("INTC", "Intel Corporation", "equity"),
    CuratedEntry("BABA", "Alibaba Group Holding Limited", "equity"),
    # Crypto miners
    CuratedEntry("MARA", "Marathon Digital Holdings, Inc.", "equity"),
    CuratedEntry("RIOT", "Riot Platforms, Inc.", "equity"),
    # Memes
    CuratedEntry("GME", "GameStop Corp.", "equity"),
    CuratedEntry("AMC", "AMC Entertainment Holdings, Inc.", "equity"),
    # Other liquid single names
    CuratedEntry("ARM", "Arm Holdings plc", "equity"),
    CuratedEntry("SOFI", "SoFi Technologies, Inc.", "equity"),
    CuratedEntry("F", "Ford Motor Company", "equity"),
    CuratedEntry("BAC", "Bank of America Corporation", "equity"),
    CuratedEntry("ORCL", "Oracle Corporation", "equity"),
)


# Curated "popular" — 8 names surfaced as a quick-pick row in the new
# search modal. Highest-volume 0DTE-capable tickers; algorithmic
# replacement lives in `ticker_analytics.get_popular_tickers()` and
# can be flipped on once selection-tracking has enough signal.
POPULAR_TICKERS: tuple[str, ...] = (
    "SPY", "QQQ", "IWM", "AAPL", "NVDA", "TSLA", "MSFT", "AMD",
)


def _index_by_symbol() -> dict[str, CuratedEntry]:
    return {e.symbol: e for e in CURATED_UNIVERSE}


_BY_SYMBOL: dict[str, CuratedEntry] = _index_by_symbol()


def get_all() -> tuple[CuratedEntry, ...]:
    """Snapshot of the curated universe — preserves declaration order."""
    return CURATED_UNIVERSE


def lookup(symbol: str) -> CuratedEntry | None:
    return _BY_SYMBOL.get((symbol or "").strip().upper())


def is_in_universe(symbol: str) -> bool:
    return (symbol or "").strip().upper() in _BY_SYMBOL


def get_popular() -> tuple[CuratedEntry, ...]:
    """Curated popular slate — eight names. Falls back to omitting any
    that somehow drift out of `CURATED_UNIVERSE` so the response never
    references a symbol the lookup wouldn't recognize."""
    out: list[CuratedEntry] = []
    for sym in POPULAR_TICKERS:
        e = _BY_SYMBOL.get(sym)
        if e is not None:
            out.append(e)
    return tuple(out)
