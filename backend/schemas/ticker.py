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
