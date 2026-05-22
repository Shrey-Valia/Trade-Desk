from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    alpaca_api_key: str = ""
    alpaca_api_secret: str = ""
    alpaca_paper: bool = True
    alpaca_options_feed: str = "indicative"

    finnhub_api_key: str = ""
    fred_api_key: str = ""

    database_url: str = f"sqlite:///{PROJECT_ROOT / 'data' / 'dashboard.db'}"
    log_level: str = "INFO"

    # Hardcoded universe for Phase 1. Expand later via a tickers table or env var.
    watchlist_universe: tuple[str, ...] = (
        "NVDA", "TSLA", "AAPL", "AMD", "MSFT", "META", "AMZN", "GOOGL",
        "PLTR", "SMCI", "BA", "INTC", "F", "QQQ", "SPY",
    )

    # Trade Desk Phase 0 — names the symbol search autocomplete suggests
    # and the prewarm job keeps warm. Superset of watchlist_universe with
    # added high-volume optionable names so a demo viewer can type almost
    # any liquid ticker and land it cached. The hot subset (Hot Now +
    # Unusual Options) still warms FIRST inside the per-cycle budget so
    # most-clicked names are always prioritized.
    prewarm_liquid_universe: tuple[str, ...] = (
        # Mega-cap tech (also in watchlist)
        "AAPL", "MSFT", "NVDA", "TSLA", "AMD", "META", "AMZN", "GOOGL",
        "INTC", "MU", "AVGO", "CRM", "ORCL", "ADBE",
        # Index ETFs
        "SPY", "QQQ", "IWM",
        # Consumer / media
        "NFLX", "DIS", "SHOP", "UBER", "ABNB", "SNAP",
        # EVs + autos
        "RIVN", "LCID", "NIO", "F", "GM",
        # Banks / financials
        "JPM", "BAC", "GS", "MS", "C", "WFC", "V", "MA",
        # Speculative + retail favorites
        "PLTR", "SOFI", "COIN", "SMCI", "BA",
        # Energy
        "XOM", "CVX",
        # Retail / staples
        "WMT", "COST", "HD", "LOW", "KO", "PEP", "MCD",
        # Healthcare / pharma
        "JNJ", "PFE", "LLY", "UNH", "ABBV",
        # Apparel / brands
        "NKE", "SBUX",
    )

    # Names used for ML training data (Phase 6+). Most don't appear in the
    # watchlist UI. SPY/QQQ are also included here so the LSTM can predict
    # vol for the indices themselves — users want to see the market regime.
    # ETFs are skipped during the earnings backfill (no earnings prints).
    training_universe: tuple[str, ...] = (
        # Index ETFs (vol forecasting, no earnings)
        "SPY", "QQQ",
        # Mega-cap stable
        "JNJ", "PG", "KO", "WMT", "V", "MA", "COST", "UNH",
        # Mega-cap volatile
        "TSLA", "NFLX", "CRM", "ADBE", "ORCL",
        # Mid-cap with active options
        "COIN", "RBLX", "SNAP", "U", "RIVN", "AFRM",
        # Financials
        "JPM", "BAC", "GS", "MS", "C", "WFC",
        # Healthcare / Pharma
        "PFE", "MRK", "LLY", "ABBV", "BMY",
        # Industrials / Consumer
        "CAT", "DE", "HD", "LOW", "NKE", "SBUX",
    )


settings = Settings()
