"""Tests for engine/utils/market_data_provider.py.

Focus areas:
  1. Regression test for the TOTP-availability bug: `_indstocks_available()`
     used to only check `INDSTOCKS_TOKEN`, which meant a fully-configured
     TOTP setup (INDSTOCKS_CLIENT_ID + INDSTOCKS_MPIN + INDSTOCKS_TOTP_SECRET,
     the "preferred" auth mode per the docs) was never detected and the
     provider silently fell back to yfinance forever.
  2. `provider_status()` reporting (primary/fallback/auth_mode/primary_label),
     since the frontend now surfaces this directly as a "data source" badge.
  3. `get_batch_ohlcv()` — the new INDstocks batch historical path used by
     the screener's bulk scan.

No live network calls: INDstocks/instruments-cache internals are mocked per
`docs/market-data.md`'s "Adding a New Data Source" guidance ("Mock the new
client in unit tests — no live API calls in tests").
"""


import pytest

from engine.utils import market_data_provider as mdp

_ENV_KEYS = (
    "INDSTOCKS_TOKEN",
    "INDSTOCKS_CLIENT_ID",
    "INDSTOCKS_MPIN",
    "INDSTOCKS_TOTP_SECRET",
)


@pytest.fixture(autouse=True)
def _clean_indstocks_env(monkeypatch):
    """Ensure no INDstocks env vars leak in from the real environment/other tests."""
    for key in _ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    yield


@pytest.fixture(autouse=True)
def _reset_ohlcv_preference_cache():
    """mdp._preference_cache is a module-level short-TTL cache (see
    get_ohlcv_provider_preference) — reset it before/after every test so one
    test's monkeypatched utils.db.get_setting doesn't leak into the next via
    the cache outliving the monkeypatch."""
    mdp.invalidate_ohlcv_provider_preference_cache()
    yield
    mdp.invalidate_ohlcv_provider_preference_cache()


# ---------------------------------------------------------------------------
# _indstocks_available() / provider_status()
# ---------------------------------------------------------------------------


def test_unavailable_with_no_credentials():
    assert mdp._indstocks_available() is False
    status = mdp.provider_status()
    assert status["primary"] == "yfinance"
    assert status["primary_label"] == "Yahoo Finance"
    assert status["fallback"] == "none"
    assert status["auth_mode"] == "none"


def test_available_with_static_token_only(monkeypatch):
    monkeypatch.setenv("INDSTOCKS_TOKEN", "eyJ.fake.token")
    assert mdp._indstocks_available() is True
    status = mdp.provider_status()
    assert status["primary"] == "indstocks"
    assert status["primary_label"] == "INDmoney"
    assert status["fallback"] == "yfinance"
    assert status["auth_mode"] == "static_token"


def test_available_with_totp_trio_only_and_no_static_token(monkeypatch):
    """Regression test: this is the "preferred" documented setup and must
    make the provider available even though INDSTOCKS_TOKEN is unset."""
    monkeypatch.setenv("INDSTOCKS_CLIENT_ID", "client123")
    monkeypatch.setenv("INDSTOCKS_MPIN", "1234")
    monkeypatch.setenv("INDSTOCKS_TOTP_SECRET", "BASE32SECRET")
    monkeypatch.delenv("INDSTOCKS_TOKEN", raising=False)

    assert mdp._indstocks_available() is True
    status = mdp.provider_status()
    assert status["primary"] == "indstocks"
    assert status["primary_label"] == "INDmoney"
    assert status["auth_mode"] == "totp"


def test_unavailable_with_partial_totp_creds(monkeypatch):
    """Missing even one of the three TOTP env vars must not count as configured."""
    monkeypatch.setenv("INDSTOCKS_CLIENT_ID", "client123")
    monkeypatch.setenv("INDSTOCKS_MPIN", "1234")
    # INDSTOCKS_TOTP_SECRET intentionally left unset
    assert mdp._indstocks_available() is False
    assert mdp.provider_status()["auth_mode"] == "none"


# ---------------------------------------------------------------------------
# get_batch_ohlcv()
# ---------------------------------------------------------------------------


class _FakeInstrumentsCache:
    def __init__(self, mapping):
        self._mapping = mapping

    def get_scrip_code(self, symbol):
        return self._mapping.get(symbol)


class _FakeClient:
    def __init__(self, candles_by_scrip):
        self._candles_by_scrip = candles_by_scrip
        self.calls = []

    def get_historical(self, scrip_codes, interval, start_ms, end_ms):
        self.calls.append(list(scrip_codes))
        return {
            code: {"candles": self._candles_by_scrip[code]}
            for code in scrip_codes
            if code in self._candles_by_scrip
        }


def _sample_candles(n=5, base_ts=1_700_000_000):
    return [
        {
            "ts": base_ts + i * 86400,
            "o": 100.0 + i,
            "h": 101.0 + i,
            "l": 99.0 + i,
            "c": 100.5 + i,
            "v": 1000 + i,
        }
        for i in range(n)
    ]


def test_get_batch_ohlcv_empty_when_unavailable():
    # No env vars set -> _indstocks_available() is False -> short-circuit.
    assert mdp.get_batch_ohlcv(["RELIANCE.NS", "TCS.NS"]) == {}


def test_get_batch_ohlcv_full_coverage(monkeypatch):
    monkeypatch.setenv("INDSTOCKS_TOKEN", "fake-token")

    mapping = {"RELIANCE.NS": "NSE_2885", "TCS.NS": "NSE_11536"}
    fake_cache = _FakeInstrumentsCache(mapping)
    fake_client = _FakeClient(
        {
            "NSE_2885": _sample_candles(),
            "NSE_11536": _sample_candles(),
        }
    )

    monkeypatch.setattr(
        "utils.instruments_cache.get_instruments_cache", lambda: fake_cache
    )
    monkeypatch.setattr("utils.indstocks_client.get_client", lambda: fake_client)

    result = mdp.get_batch_ohlcv(["RELIANCE.NS", "TCS.NS"], period="1y")

    assert set(result.keys()) == {"RELIANCE.NS", "TCS.NS"}
    for df in result.values():
        assert list(df.columns) == ["Open", "High", "Low", "Close", "Volume"]
        assert len(df) == 5
    # One batched call, not one per symbol.
    assert len(fake_client.calls) == 1
    assert set(fake_client.calls[0]) == {"NSE_2885", "NSE_11536"}


def test_get_batch_ohlcv_partial_coverage_omits_missing_symbols(monkeypatch):
    monkeypatch.setenv("INDSTOCKS_TOKEN", "fake-token")

    mapping = {"RELIANCE.NS": "NSE_2885", "DELISTEDX.NS": "NSE_99999"}
    fake_cache = _FakeInstrumentsCache(mapping)
    # DELISTEDX resolves to a scrip code but INDstocks returns no candles for it.
    fake_client = _FakeClient({"NSE_2885": _sample_candles()})

    monkeypatch.setattr(
        "utils.instruments_cache.get_instruments_cache", lambda: fake_cache
    )
    monkeypatch.setattr("utils.indstocks_client.get_client", lambda: fake_client)

    result = mdp.get_batch_ohlcv(["RELIANCE.NS", "DELISTEDX.NS"], period="1y")

    assert set(result.keys()) == {"RELIANCE.NS"}


def test_get_batch_ohlcv_chunks_large_symbol_lists(monkeypatch):
    """`_BATCH_CHUNK_SIZE` is currently 5 — determined empirically by probing
    the live INDstocks API, since /market/historical rejects 6+ scrip codes
    per call with a generic (and misleading) "Invalid scrip codes" error
    that doesn't mention it's a size limit. This test derives its expected
    chunk sizes from the constant itself rather than hard-coding 5, so a
    future (deliberate, re-verified) change to the limit doesn't silently
    desync the test."""
    monkeypatch.setenv("INDSTOCKS_TOKEN", "fake-token")

    total = 3 * mdp._BATCH_CHUNK_SIZE + 2  # a couple of chunk sizes plus a remainder
    symbols = [f"SYM{i}.NS" for i in range(total)]
    mapping = {s: f"NSE_{i}" for i, s in enumerate(symbols)}
    fake_cache = _FakeInstrumentsCache(mapping)
    fake_client = _FakeClient({scrip: _sample_candles(2) for scrip in mapping.values()})

    monkeypatch.setattr(
        "utils.instruments_cache.get_instruments_cache", lambda: fake_cache
    )
    monkeypatch.setattr("utils.indstocks_client.get_client", lambda: fake_client)

    result = mdp.get_batch_ohlcv(symbols, period="1y")

    assert len(result) == total
    expected_calls = -(-total // mdp._BATCH_CHUNK_SIZE)  # ceil division
    assert len(fake_client.calls) == expected_calls
    assert all(len(c) <= mdp._BATCH_CHUNK_SIZE for c in fake_client.calls)
    assert sum(len(c) for c in fake_client.calls) == total


def test_get_batch_ohlcv_unsupported_period_short_circuits(monkeypatch):
    monkeypatch.setenv("INDSTOCKS_TOKEN", "fake-token")
    # "2y" is beyond what INDstocks daily candles support (see _period_to_ms).
    assert mdp.get_batch_ohlcv(["RELIANCE.NS"], period="2y") == {}


# ---------------------------------------------------------------------------
# _candles_to_df()
# ---------------------------------------------------------------------------


def test_candles_to_df_empty_input():
    assert mdp._candles_to_df([]).empty


def test_candles_to_df_shape_and_columns():
    df = mdp._candles_to_df(_sample_candles(3))
    assert list(df.columns) == ["Open", "High", "Low", "Close", "Volume"]
    assert len(df) == 3
    assert df.index.name == "Date"
    assert str(df.index.tz) != "None"


# ---------------------------------------------------------------------------
# OHLCV/scan data-source preference toggle (Bhav Copy vs INDstocks)
# ---------------------------------------------------------------------------


def test_ohlcv_provider_preference_defaults_to_bhavcopy(monkeypatch):
    monkeypatch.setattr("utils.db.get_setting", lambda key, default=None: default)
    assert mdp.get_ohlcv_provider_preference() == "bhavcopy"


def test_ohlcv_provider_preference_reads_stored_setting(monkeypatch):
    monkeypatch.setattr(
        "utils.db.get_setting", lambda key, default=None: "indstocks"
    )
    assert mdp.get_ohlcv_provider_preference() == "indstocks"


def test_ohlcv_provider_preference_falls_back_to_default_on_bogus_value(monkeypatch):
    # A corrupted/unexpected app_settings row shouldn't wedge the provider —
    # fall back to the documented default rather than propagating garbage.
    monkeypatch.setattr(
        "utils.db.get_setting", lambda key, default=None: "not-a-real-provider"
    )
    assert mdp.get_ohlcv_provider_preference() == "bhavcopy"


def test_ohlcv_provider_preference_is_cached_until_invalidated(monkeypatch):
    calls = {"n": 0}

    def _get_setting(key, default=None):
        calls["n"] += 1
        return "indstocks"

    monkeypatch.setattr("utils.db.get_setting", _get_setting)

    assert mdp.get_ohlcv_provider_preference() == "indstocks"
    assert mdp.get_ohlcv_provider_preference() == "indstocks"
    assert calls["n"] == 1  # second call served from the in-process cache

    mdp.invalidate_ohlcv_provider_preference_cache()
    assert mdp.get_ohlcv_provider_preference() == "indstocks"
    assert calls["n"] == 2  # cache invalidation forces a fresh DB read


def test_get_ohlcv_tries_bhavcopy_first_when_preferred(monkeypatch):
    monkeypatch.setattr("utils.db.get_setting", lambda key, default=None: "bhavcopy")

    bhav_df = mdp._candles_to_df(_sample_candles(3))[["Open", "High", "Low", "Close", "Volume"]]
    monkeypatch.setattr(
        "utils.db.fetch_bhavcopy_ohlcv", lambda symbol, start_date=None, end_date=None: bhav_df
    )

    def _boom(*a, **k):
        raise AssertionError("INDstocks/yfinance should not be tried when Bhav Copy has data")

    monkeypatch.setattr(mdp, "_ohlcv_indstocks", _boom)
    monkeypatch.setattr(mdp, "_ohlcv_yfinance", _boom)

    result = mdp.get_ohlcv("RELIANCE.NS", period="1y")
    assert len(result) == 3


def test_get_ohlcv_falls_through_to_indstocks_when_bhavcopy_has_no_data(monkeypatch):
    monkeypatch.setenv("INDSTOCKS_TOKEN", "fake-token")
    monkeypatch.setattr("utils.db.get_setting", lambda key, default=None: "bhavcopy")
    monkeypatch.setattr(
        "utils.db.fetch_bhavcopy_ohlcv",
        lambda symbol, start_date=None, end_date=None: __import__("pandas").DataFrame(),
    )

    indstocks_df = mdp._candles_to_df(_sample_candles(2))[["Open", "High", "Low", "Close", "Volume"]]
    monkeypatch.setattr(mdp, "_ohlcv_indstocks", lambda symbol, period: indstocks_df)

    result = mdp.get_ohlcv("RELIANCE.NS", period="1y")
    assert len(result) == 2


def test_get_ohlcv_skips_bhavcopy_entirely_when_preference_is_indstocks(monkeypatch):
    monkeypatch.setenv("INDSTOCKS_TOKEN", "fake-token")
    monkeypatch.setattr("utils.db.get_setting", lambda key, default=None: "indstocks")

    def _boom(*a, **k):
        raise AssertionError("Bhav Copy tier should not be consulted at all")

    monkeypatch.setattr("utils.db.fetch_bhavcopy_ohlcv", _boom)

    indstocks_df = mdp._candles_to_df(_sample_candles(2))[["Open", "High", "Low", "Close", "Volume"]]
    monkeypatch.setattr(mdp, "_ohlcv_indstocks", lambda symbol, period: indstocks_df)

    result = mdp.get_ohlcv("RELIANCE.NS", period="1y")
    assert len(result) == 2


def test_get_batch_ohlcv_bhavcopy_covers_some_indstocks_covers_rest(monkeypatch):
    monkeypatch.setenv("INDSTOCKS_TOKEN", "fake-token")
    monkeypatch.setattr("utils.db.get_setting", lambda key, default=None: "bhavcopy")

    bhav_df = mdp._candles_to_df(_sample_candles(3))[["Open", "High", "Low", "Close", "Volume"]]
    monkeypatch.setattr(
        "utils.db.fetch_bhavcopy_ohlcv_batch",
        lambda symbols, start_date=None, end_date=None: {"RELIANCE.NS": bhav_df},
    )

    mapping = {"TCS.NS": "NSE_11536"}
    fake_cache = _FakeInstrumentsCache(mapping)
    fake_client = _FakeClient({"NSE_11536": _sample_candles(4)})
    monkeypatch.setattr(
        "utils.instruments_cache.get_instruments_cache", lambda: fake_cache
    )
    monkeypatch.setattr("utils.indstocks_client.get_client", lambda: fake_client)

    result = mdp.get_batch_ohlcv(["RELIANCE.NS", "TCS.NS"], period="1y")

    assert set(result.keys()) == {"RELIANCE.NS", "TCS.NS"}
    assert len(result["RELIANCE.NS"]) == 3
    assert len(result["TCS.NS"]) == 4
    # INDstocks was only asked for the symbol Bhav Copy didn't cover.
    assert fake_client.calls == [["NSE_11536"]]


def test_provider_status_reports_ohlcv_source_independently_of_primary(monkeypatch):
    monkeypatch.setenv("INDSTOCKS_TOKEN", "fake-token")
    monkeypatch.setattr("utils.db.get_setting", lambda key, default=None: "bhavcopy")

    status = mdp.provider_status()
    assert status["ohlcv_source"] == "bhavcopy"
    assert status["ohlcv_source_label"] == "NSE Bhav Copy"
    # Live-price primary is untouched by the OHLCV preference.
    assert status["primary"] == "indstocks"
    assert status["primary_label"] == "INDmoney"


def test_period_to_start_date_unknown_period_returns_none():
    assert mdp._period_to_start_date("garbage-period") is None


def test_period_to_start_date_known_period_returns_a_date_string():
    result = mdp._period_to_start_date("1y")
    assert result is not None
    assert len(result) == 10  # "YYYY-MM-DD"
