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


@pytest.fixture(autouse=True)
def _reset_ohlcv_source_call_counts():
    """mdp._ohlcv_source_call_counts is a module-level cumulative counter
    dict (see get_ohlcv_source_call_counts) — reset it before/after every
    test so one test's get_ohlcv()/get_batch_ohlcv() calls don't leak into
    the next test's assertions. Same rationale as the fixture above, and the
    same class of bug already hit once this session with a hardcoded-key
    SQLite dedup test (see .agent-room/anti-patterns.md)."""
    mdp.reset_ohlcv_source_call_counts()
    yield
    mdp.reset_ohlcv_source_call_counts()


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


def _full_year_bhavcopy_df(n=260):
    """A Bhav Copy OHLCV DataFrame with enough rows to clear
    _bhavcopy_has_sufficient_coverage's bar for a "1y" period request (~260
    trading days expected; 260 rows clears even a 100% bar with room for
    weekday/holiday slack in the real bdate_range comparison). Tests that
    only care about "Bhav Copy has an answer" (not the coverage-threshold
    behavior itself, which has its own dedicated tests below) should use
    this instead of a handful of _sample_candles rows, which now reads as
    "mid-backfill / insufficient" and falls through to the next tier."""
    return mdp._candles_to_df(_sample_candles(n))[["Open", "High", "Low", "Close", "Volume"]]


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

    bhav_df = _full_year_bhavcopy_df()
    monkeypatch.setattr(
        "utils.db.fetch_bhavcopy_ohlcv", lambda symbol, start_date=None, end_date=None: bhav_df
    )

    def _boom(*a, **k):
        raise AssertionError("INDstocks/yfinance should not be tried when Bhav Copy has data")

    monkeypatch.setattr(mdp, "_ohlcv_indstocks", _boom)
    monkeypatch.setattr(mdp, "_ohlcv_yfinance", _boom)

    result = mdp.get_ohlcv("RELIANCE.NS", period="1y")
    assert len(result) == len(bhav_df)


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

    bhav_df = _full_year_bhavcopy_df()
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
    assert len(result["RELIANCE.NS"]) == len(bhav_df)
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


# ---------------------------------------------------------------------------
# _ohlcv_source_call_counts / get_ohlcv_source_call_counts /
# reset_ohlcv_source_call_counts — the "real proof" counters surfaced via
# GET /api/bhavcopy/status.ohlcv_calls_by_source. These are cumulative,
# in-process, and independent of the *preference setting* (which
# provider_status()["ohlcv_source"] reflects) — see the module docstring
# note above test_provider_status_reports_ohlcv_source_independently_of_primary.
# ---------------------------------------------------------------------------


def test_ohlcv_source_call_counts_start_at_zero():
    assert mdp.get_ohlcv_source_call_counts() == {"bhavcopy": 0, "indstocks": 0, "yfinance": 0}


def test_get_ohlcv_source_call_counts_returns_a_copy():
    counts = mdp.get_ohlcv_source_call_counts()
    counts["bhavcopy"] = 999
    # Mutating the returned dict must not mutate module state.
    assert mdp.get_ohlcv_source_call_counts()["bhavcopy"] == 0


def test_reset_ohlcv_source_call_counts_zeroes_all_keys(monkeypatch):
    monkeypatch.setattr("utils.db.get_setting", lambda key, default=None: "bhavcopy")
    bhav_df = _full_year_bhavcopy_df()
    monkeypatch.setattr(
        "utils.db.fetch_bhavcopy_ohlcv", lambda symbol, start_date=None, end_date=None: bhav_df
    )
    mdp.get_ohlcv("RELIANCE.NS", period="1y")
    assert mdp.get_ohlcv_source_call_counts()["bhavcopy"] == 1

    mdp.reset_ohlcv_source_call_counts()
    assert mdp.get_ohlcv_source_call_counts() == {"bhavcopy": 0, "indstocks": 0, "yfinance": 0}


def test_get_ohlcv_increments_bhavcopy_count_on_success(monkeypatch):
    monkeypatch.setattr("utils.db.get_setting", lambda key, default=None: "bhavcopy")
    bhav_df = _full_year_bhavcopy_df()
    monkeypatch.setattr(
        "utils.db.fetch_bhavcopy_ohlcv", lambda symbol, start_date=None, end_date=None: bhav_df
    )

    mdp.get_ohlcv("RELIANCE.NS", period="1y")
    mdp.get_ohlcv("TCS.NS", period="1y")

    counts = mdp.get_ohlcv_source_call_counts()
    assert counts["bhavcopy"] == 2
    assert counts["indstocks"] == 0
    assert counts["yfinance"] == 0


def test_get_ohlcv_increments_indstocks_count_when_bhavcopy_falls_through(monkeypatch):
    monkeypatch.setenv("INDSTOCKS_TOKEN", "fake-token")
    monkeypatch.setattr("utils.db.get_setting", lambda key, default=None: "bhavcopy")
    monkeypatch.setattr(
        "utils.db.fetch_bhavcopy_ohlcv",
        lambda symbol, start_date=None, end_date=None: __import__("pandas").DataFrame(),
    )
    indstocks_df = mdp._candles_to_df(_sample_candles(2))[["Open", "High", "Low", "Close", "Volume"]]
    monkeypatch.setattr(mdp, "_ohlcv_indstocks", lambda symbol, period: indstocks_df)

    mdp.get_ohlcv("RELIANCE.NS", period="1y")

    counts = mdp.get_ohlcv_source_call_counts()
    assert counts["bhavcopy"] == 0
    assert counts["indstocks"] == 1
    assert counts["yfinance"] == 0


def test_get_ohlcv_increments_yfinance_count_as_last_resort(monkeypatch):
    monkeypatch.setattr("utils.db.get_setting", lambda key, default=None: "indstocks")

    yfinance_df = mdp._candles_to_df(_sample_candles(2))[["Open", "High", "Low", "Close", "Volume"]]
    monkeypatch.setattr(mdp, "_ohlcv_yfinance", lambda symbol, period: yfinance_df)

    mdp.get_ohlcv("RELIANCE.NS", period="1y")

    counts = mdp.get_ohlcv_source_call_counts()
    assert counts["bhavcopy"] == 0
    assert counts["indstocks"] == 0
    assert counts["yfinance"] == 1


def test_get_ohlcv_does_not_increment_any_count_on_total_failure(monkeypatch):
    monkeypatch.setattr("utils.db.get_setting", lambda key, default=None: "indstocks")
    empty_df = __import__("pandas").DataFrame()
    monkeypatch.setattr(mdp, "_ohlcv_yfinance", lambda symbol, period: empty_df)

    result = mdp.get_ohlcv("RELIANCE.NS", period="1y")

    assert result.empty
    assert mdp.get_ohlcv_source_call_counts() == {"bhavcopy": 0, "indstocks": 0, "yfinance": 0}


def test_get_batch_ohlcv_increments_counts_by_number_of_symbols_served(monkeypatch):
    monkeypatch.setenv("INDSTOCKS_TOKEN", "fake-token")
    monkeypatch.setattr("utils.db.get_setting", lambda key, default=None: "bhavcopy")

    bhav_df = _full_year_bhavcopy_df()
    monkeypatch.setattr(
        "utils.db.fetch_bhavcopy_ohlcv_batch",
        lambda symbols, start_date=None, end_date=None: {"RELIANCE.NS": bhav_df},
    )
    mapping = {"TCS.NS": "NSE_11536"}
    fake_cache = _FakeInstrumentsCache(mapping)
    fake_client = _FakeClient({"NSE_11536": _sample_candles(4)})
    monkeypatch.setattr("utils.instruments_cache.get_instruments_cache", lambda: fake_cache)
    monkeypatch.setattr("utils.indstocks_client.get_client", lambda: fake_client)

    mdp.get_batch_ohlcv(["RELIANCE.NS", "TCS.NS"], period="1y")

    counts = mdp.get_ohlcv_source_call_counts()
    # One symbol served by each tier — counts track number of symbols, not
    # number of get_batch_ohlcv() calls.
    assert counts["bhavcopy"] == 1
    assert counts["indstocks"] == 1
    assert counts["yfinance"] == 0


# ---------------------------------------------------------------------------
# _bhavcopy_has_sufficient_coverage() — the mid-backfill fall-through guard.
#
# Found live: right after the backfill first ran, Bhav Copy had only ~16
# trading days of history. The old check was just "is the DataFrame
# non-empty", so get_ohlcv()/get_batch_ohlcv() served that 16-row history
# outright for period="1y" scan requests — which then silently failed
# stock_scanner.logic.check_institutional_fortress's own `len(data) < 210`
# gate for every symbol, so a full scan came back with 0 results and no
# error anywhere in the chain. These tests pin down the fix: Bhav Copy only
# "counts" once it covers a real fraction of the requested period's trading
# days, otherwise the tier falls through like it would for no data at all.
# ---------------------------------------------------------------------------


def test_bhavcopy_coverage_accepts_a_full_years_history():
    df = _full_year_bhavcopy_df()
    assert mdp._bhavcopy_has_sufficient_coverage(df, "1y") is True


def test_bhavcopy_coverage_rejects_sixteen_days_against_a_one_year_request():
    # The exact scenario found live: 16 trading days backfilled, period="1y".
    df = mdp._candles_to_df(_sample_candles(16))[["Open", "High", "Low", "Close", "Volume"]]
    assert mdp._bhavcopy_has_sufficient_coverage(df, "1y") is False


def test_bhavcopy_coverage_accepts_a_short_period_with_matching_short_history():
    # A "1mo" request only expects ~22 trading days — 16 rows should clear
    # that bar even though it fails the "1y" bar above with the same data.
    df = mdp._candles_to_df(_sample_candles(16))[["Open", "High", "Low", "Close", "Volume"]]
    assert mdp._bhavcopy_has_sufficient_coverage(df, "1mo") is True


def test_bhavcopy_coverage_rejects_203_days_against_a_one_year_request():
    # Found live (2026-08-23): a real mid-backfill state where Bhav Copy had
    # 203 trading days of history. That clears the 0.5 *ratio* bar on its
    # own (203 >= ~260*0.5), so the ratio-only check accepted it as "covered"
    # — but 203 rows is still short of the scanner's own hard `len(data) <
    # 210` gate in stock_scanner.logic.check_institutional_fortress, so
    # every one of those symbols got marked "served by Bhav Copy" here, never
    # fell through to INDstocks/yfinance, and then silently failed the 210
    # gate downstream — a full scan came back with 0 results (49 symbols
    # "served" by Bhav Copy, 0 by INDstocks, 0 by yfinance) with no error
    # anywhere in the chain. This pins down the absolute-floor fix.
    df = mdp._candles_to_df(_sample_candles(203))[["Open", "High", "Low", "Close", "Volume"]]
    assert mdp._bhavcopy_has_sufficient_coverage(df, "1y") is False


def test_bhavcopy_coverage_accepts_210_days_against_a_one_year_request():
    # The absolute floor is MIN_SCAN_HISTORY_ROWS (210) exactly, not a
    # rounded-up ratio bar — 210 rows must clear it.
    df = mdp._candles_to_df(_sample_candles(210))[["Open", "High", "Low", "Close", "Volume"]]
    assert mdp._bhavcopy_has_sufficient_coverage(df, "1y") is True


def test_bhavcopy_coverage_absolute_floor_does_not_apply_to_short_periods():
    # The 210-row absolute floor must only bite once the period's own
    # expected trading-day count could plausibly reach it (~"1y" and up).
    # A "6mo" request (~130 expected trading days) can never reach 210
    # trading days no matter how complete Bhav Copy's history is, so it must
    # stay governed by the ratio bar alone, not be held to the scanner's 1y
    # minimum it was never trying to satisfy.
    df = mdp._candles_to_df(_sample_candles(100))[["Open", "High", "Low", "Close", "Volume"]]
    assert mdp._bhavcopy_has_sufficient_coverage(df, "6mo") is True


def test_bhavcopy_coverage_accepts_unrecognised_period_with_no_bound_to_compare():
    df = mdp._candles_to_df(_sample_candles(1))[["Open", "High", "Low", "Close", "Volume"]]
    assert mdp._bhavcopy_has_sufficient_coverage(df, "garbage-period") is True


def test_get_ohlcv_falls_through_to_indstocks_when_bhavcopy_coverage_is_thin(monkeypatch):
    """Bhav Copy returns real, non-empty data (16 rows) but not enough of
    it for a "1y" request — must fall through to INDstocks rather than
    serving the thin history outright, and the call must be recorded as
    served by indstocks, not bhavcopy."""
    monkeypatch.setenv("INDSTOCKS_TOKEN", "fake-token")
    monkeypatch.setattr("utils.db.get_setting", lambda key, default=None: "bhavcopy")

    thin_bhav_df = mdp._candles_to_df(_sample_candles(16))[["Open", "High", "Low", "Close", "Volume"]]
    monkeypatch.setattr(
        "utils.db.fetch_bhavcopy_ohlcv",
        lambda symbol, start_date=None, end_date=None: thin_bhav_df,
    )
    indstocks_df = mdp._candles_to_df(_sample_candles(2))[["Open", "High", "Low", "Close", "Volume"]]
    monkeypatch.setattr(mdp, "_ohlcv_indstocks", lambda symbol, period: indstocks_df)

    result = mdp.get_ohlcv("RELIANCE.NS", period="1y")

    assert len(result) == 2  # the INDstocks data, not the thin Bhav Copy data
    counts = mdp.get_ohlcv_source_call_counts()
    assert counts["bhavcopy"] == 0
    assert counts["indstocks"] == 1


def test_get_batch_ohlcv_rolls_thin_bhavcopy_symbol_to_indstocks(monkeypatch):
    """Batch equivalent: one symbol has full Bhav Copy coverage, the other
    only has thin (mid-backfill) coverage — the thin one must roll over to
    the INDstocks tier rather than being served as-is."""
    monkeypatch.setenv("INDSTOCKS_TOKEN", "fake-token")
    monkeypatch.setattr("utils.db.get_setting", lambda key, default=None: "bhavcopy")

    full_df = _full_year_bhavcopy_df()
    thin_df = mdp._candles_to_df(_sample_candles(16))[["Open", "High", "Low", "Close", "Volume"]]
    monkeypatch.setattr(
        "utils.db.fetch_bhavcopy_ohlcv_batch",
        lambda symbols, start_date=None, end_date=None: {
            "RELIANCE.NS": full_df,
            "TCS.NS": thin_df,
        },
    )
    mapping = {"TCS.NS": "NSE_11536"}
    fake_cache = _FakeInstrumentsCache(mapping)
    fake_client = _FakeClient({"NSE_11536": _sample_candles(4)})
    monkeypatch.setattr("utils.instruments_cache.get_instruments_cache", lambda: fake_cache)
    monkeypatch.setattr("utils.indstocks_client.get_client", lambda: fake_client)

    result = mdp.get_batch_ohlcv(["RELIANCE.NS", "TCS.NS"], period="1y")

    assert len(result["RELIANCE.NS"]) == len(full_df)
    assert len(result["TCS.NS"]) == 4  # served by INDstocks, not the thin Bhav Copy frame
    assert fake_client.calls == [["NSE_11536"]]
    counts = mdp.get_ohlcv_source_call_counts()
    assert counts["bhavcopy"] == 1
    assert counts["indstocks"] == 1


def test_period_to_start_date_unknown_period_returns_none():
    assert mdp._period_to_start_date("garbage-period") is None


def test_period_to_start_date_known_period_returns_a_date_string():
    result = mdp._period_to_start_date("1y")
    assert result is not None
    assert len(result) == 10  # "YYYY-MM-DD"
