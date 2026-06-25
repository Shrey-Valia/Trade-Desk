from typing import Literal

from pydantic import BaseModel


class TickerDetailOut(BaseModel):
    symbol: str
    price: float
    change_dollar: float
    change_pct: float
    day_high: float
    day_low: float
    fifty_two_week_high: float
    fifty_two_week_low: float
    volume: int
    avg_volume_20d: int
    next_earnings_date: str | None = None
    days_to_earnings: int | None = None


class BarPoint(BaseModel):
    t: str  # ISO timestamp
    o: float
    h: float
    l: float
    c: float
    v: int


class WallLevel(BaseModel):
    strike: float
    oi: int


class ChartAnnotations(BaseModel):
    expected_move_upper: float | None = None
    expected_move_lower: float | None = None
    call_wall: WallLevel | None = None
    put_wall: WallLevel | None = None
    max_pain: float | None = None
    gamma_flip: float | None = None
    earnings_date: str | None = None
    # Auto support/resistance from swing structure (calculations/levels.py).
    # Price-ordered, relative to the latest close; rendered as dotted price
    # lines behind the same annotations toggle as the EM/wall overlays.
    support_levels: list[float] = []
    resistance_levels: list[float] = []


class ChartResponse(BaseModel):
    symbol: str
    timeframe: str
    bars: list[BarPoint]
    annotations: ChartAnnotations
    # Free-tier indicative feed has no open_interest; we substitute daily
    # volume per contract as a proxy. UI surfaces this for transparency.
    oi_source: str  # "open_interest" or "volume_proxy"


class MetricsResponse(BaseModel):
    iv_rank: float | None = None
    iv_rank_status: str | None = None
    vrp: float | None = None
    skew_25d: float | None = None
    pc_ratio: float | None = None
    max_pain: float | None = None


class IndicatorSeries(BaseModel):
    """One technical-indicator overlay, aligned 1:1 with `times`.

    `values` is the same length as the chart's bar array; warm-up bars
    (insufficient lookback) are `None` so the frontend can plot a
    LineSeries against the same timestamps with no index juggling.

    `pane` tells the UI where the series belongs:
      - "price": shares the main price scale (SMA / EMA / VWAP / Bollinger)
      - "oscillator": its own 0–100 pane (RSI / Stochastic)
      - "volatility": its own absolute-value pane (ATR)
      - "macd": MACD's own zero-centred pane (line / signal / histogram)

    `kind` tells the UI how to draw the series:
      - "line": a LineSeries (the default — every overlay except below)
      - "histogram": a HistogramSeries (MACD histogram bars)
    """

    key: str          # e.g. "sma20", "ema50", "vwap", "rsi14", "atr14"
    label: str        # human label, e.g. "SMA 20"
    pane: str         # "price" | "oscillator" | "volatility" | "macd"
    kind: Literal["line", "histogram"] = "line"
    values: list[float | None]


class IndicatorsResponse(BaseModel):
    symbol: str
    timeframe: str
    # ISO timestamps for each bar — identical to /chart and /bars so the
    # frontend can align overlays without a second bars fetch.
    times: list[str]
    series: list[IndicatorSeries]
