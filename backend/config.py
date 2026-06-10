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

    # Simulated brokerage commission, $ per contract per side (entry and
    # exit each charge this × the position's contract count). The SINGLE
    # place to change the rate. Folded into cost basis / unrealized P&L in
    # the analytics endpoint and into realized P&L on close — display only;
    # the MLL/DLL engine reads net P&L separately (a later prompt).
    commission_per_contract: float = 0.65

    # ---------------------------------------------------------------------
    # Auth (multi-user prop-firm shell). bcrypt cost factor is 12 for
    # real use; tests drop it to 4 so signup-per-test stays fast.
    # cookie_secure stays False for local HTTP dev — flip on for HTTPS
    # deployment. The dev_user_* creds are ONLY used by the one-time
    # migration backfill that adopts a pre-multi-user database; a fresh
    # install never creates this user.
    bcrypt_rounds: int = 12
    cookie_secure: bool = False
    dev_user_email: str = "dev@local"
    dev_user_password: str = "devpassword"

    # ---------------------------------------------------------------------
    # 0DTE-eligible universe — the ONLY symbols Trade Desk allows users
    # to open positions on. Same-day-expiry options are limited to a
    # narrow set in practice; this allowlist gates the symbol search and
    # the chain panel so users can't pick a ticker they won't be able to
    # trade.
    #
    # Current contents (May 2026): index ETFs that list daily expirations
    # on Alpaca's options feed.
    #   - SPY  S&P 500 SPDR — daily 0DTE
    #   - QQQ  Nasdaq-100 — daily 0DTE
    #   - IWM  Russell 2000 — daily 0DTE
    #
    # Index options (SPX, XSP, NDX) are intentionally omitted: Alpaca's
    # free options feed does not list cash-settled index options, so
    # those contracts wouldn't actually be tradeable through this app.
    # Add them here when/if the data source supports them.
    #
    # Edit this list as the market changes — adding a name turns it on
    # everywhere (search, chain, opens) with no other code changes.
    zero_dte_universe: tuple[str, ...] = ("SPY", "QQQ", "IWM")

    # ---------------------------------------------------------------------
    # Demo seed used to auto-populate the journal on a fresh DB. OFF by
    # default — the app starts empty so users build their own paper-trade
    # history. Set SEED_TRADES=1 in .env (or environment) to opt back in
    # for demos / regression. The seed file (jobs/seed_trades.py) is
    # kept on disk regardless; this just gates when it runs.
    seed_trades: bool = False

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
