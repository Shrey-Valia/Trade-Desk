"""chain_availability — has_zero_dte cache + bulk + failure modes."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from services import chain_availability
from services.cache import cache


@pytest.fixture(autouse=True)
def _clean_cache():
    """Each test starts with an empty TTL cache so the per-symbol
    cache lines from prior tests don't bleed in."""
    # The TTLCache module exposes a shared `cache` singleton. Reset
    # its internal store directly — simpler than introspecting key
    # patterns.
    cache._store.clear()  # noqa: SLF001
    yield
    cache._store.clear()  # noqa: SLF001


def _stub_response(num_contracts: int):
    """Build a fake OptionContractsResponse with `num_contracts`
    rows. The has_zero_dte path only counts the list length."""

    class _R:
        option_contracts = list(range(num_contracts))

    return _R()


class _StubClient:
    """Records every get_option_contracts call so tests can assert
    on the call pattern (and override the response)."""

    def __init__(self, response):
        self.calls = []
        self._response = response

    def get_option_contracts(self, request):
        self.calls.append(request)
        return self._response


def test_has_zero_dte_true_when_contracts_exist():
    stub = _StubClient(_stub_response(num_contracts=1))
    with patch.object(chain_availability, "_trading_client", return_value=stub):
        assert chain_availability.has_zero_dte("SPY") is True


def test_has_zero_dte_false_when_no_contracts():
    stub = _StubClient(_stub_response(num_contracts=0))
    with patch.object(chain_availability, "_trading_client", return_value=stub):
        assert chain_availability.has_zero_dte("XYZQ") is False


def test_has_zero_dte_caches_result():
    stub = _StubClient(_stub_response(num_contracts=1))
    with patch.object(chain_availability, "_trading_client", return_value=stub):
        chain_availability.has_zero_dte("SPY")
        chain_availability.has_zero_dte("SPY")
        chain_availability.has_zero_dte("SPY")
    assert len(stub.calls) == 1  # second + third calls served from cache


def test_has_zero_dte_caches_false_too():
    """Negative results should cache so a flaky path doesn't get
    hammered by every search keystroke."""
    stub = _StubClient(_stub_response(num_contracts=0))
    with patch.object(chain_availability, "_trading_client", return_value=stub):
        chain_availability.has_zero_dte("XYZQ")
        chain_availability.has_zero_dte("XYZQ")
    assert len(stub.calls) == 1


def test_has_zero_dte_caches_per_day():
    """Cache key includes today's date so the answer doesn't
    survive across the NY day boundary."""
    stub = _StubClient(_stub_response(num_contracts=1))
    with patch.object(chain_availability, "_trading_client", return_value=stub):
        chain_availability.has_zero_dte("SPY")
        # Simulate tomorrow without actually waiting — overwrite
        # the cache-key date suffix.
        cache._store.clear()  # noqa: SLF001
        chain_availability.has_zero_dte("SPY")
    assert len(stub.calls) == 2


def test_has_zero_dte_returns_false_on_exception():
    """If Alpaca raises, return False (no badge) and log — never
    propagate the exception to the request handler."""

    class _RaisingClient:
        def get_option_contracts(self, _req):
            raise RuntimeError("alpaca down")

    with patch.object(chain_availability, "_trading_client", return_value=_RaisingClient()):
        assert chain_availability.has_zero_dte("SPY") is False


def test_has_zero_dte_empty_symbol_short_circuits():
    """No symbol → False, no Alpaca call attempted."""
    stub = _StubClient(_stub_response(num_contracts=1))
    with patch.object(chain_availability, "_trading_client", return_value=stub):
        assert chain_availability.has_zero_dte("") is False
        assert chain_availability.has_zero_dte("   ") is False
    assert stub.calls == []


def test_bulk_returns_per_symbol_results():
    """has_zero_dte_bulk(syms) returns a dict keyed by symbol."""

    def fake_single(sym: str) -> bool:
        return sym in {"SPY", "QQQ"}

    with patch.object(chain_availability, "has_zero_dte", side_effect=fake_single):
        result = chain_availability.has_zero_dte_bulk(["SPY", "QQQ", "AAPL"])
    assert result == {"SPY": True, "QQQ": True, "AAPL": False}


@pytest.mark.network
def test_bulk_uses_cache_for_known_symbols():
    """If a symbol is already cached, bulk shouldn't call
    has_zero_dte for it (cached fast-path).

    Environment-dependent: keys on the live NY date via
    ``_today_et_iso()`` and the bulk fast-path's cache state, so it
    passes warm / at market-hours but flakes cold / offline. Marked
    ``network`` so CI deselects it (``-m "not network"``); it still
    runs in a normal local ``pytest`` invocation."""
    # Use the SAME NY date the production code keys on (_today_et_iso) so
    # the cache hit is deterministic regardless of the runner's local
    # timezone — previously this used date.today() and flaked late-evening
    # PT once the ET date had rolled over.
    today_iso = chain_availability._today_et_iso()
    cache.set(f"has_0dte:SPY:{today_iso}", True, ttl_seconds=60)
    cache.set(f"has_0dte:QQQ:{today_iso}", False, ttl_seconds=60)

    seen: list[str] = []

    def fake_single(sym: str) -> bool:
        seen.append(sym)
        return False

    with patch.object(chain_availability, "has_zero_dte", side_effect=fake_single):
        result = chain_availability.has_zero_dte_bulk(["SPY", "QQQ", "AAPL"])

    # AAPL was the only cold-miss; SPY/QQQ resolved from cache.
    assert seen == ["AAPL"]
    assert result["SPY"] is True
    assert result["QQQ"] is False
    assert result["AAPL"] is False


def test_bulk_empty_list_short_circuits():
    assert chain_availability.has_zero_dte_bulk([]) == {}
