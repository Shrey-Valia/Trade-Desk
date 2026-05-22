from pydantic import BaseModel


class McProbabilityLevel(BaseModel):
    label: str
    level: float
    prob_touch: float
    prob_close_above: float


class McResponse(BaseModel):
    symbol: str
    horizon_days: int
    n_paths: int
    sigma: float
    spot: float
    mean_close: float
    std_close: float
    ci_95: tuple[float, float]
    sample_paths: list[list[float]]                # 25 paths × (n_steps + 1)
    bands: dict[str, list[float]]                  # percentile → series
    probabilities: list[McProbabilityLevel]        # one entry per chart annotation level
