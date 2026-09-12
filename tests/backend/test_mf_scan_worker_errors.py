import logging

import pandas as pd

import mf_lab.logic as mf_logic


def test_scan_logs_worker_exception_and_keeps_scan_alive(monkeypatch, caplog):
    monkeypatch.setattr(mf_logic, "discover_all_funds", lambda limit=None: ["BAD123"])
    monkeypatch.setattr(
        mf_logic,
        "_get_benchmark_series",
        lambda ticker: pd.Series(dtype=float),
    )
    monkeypatch.setattr(mf_logic, "_bulk_preseed_nav_cache", lambda codes: {})

    def fail_for_fund(code, benchmark):
        raise IndexError("pop index out of range")

    monkeypatch.setattr(mf_logic, "_score_fund_fast", fail_for_fund)

    with caplog.at_level(logging.WARNING, logger="mf_lab.logic"):
        result = mf_logic.run_full_mf_scan(max_workers=1)

    assert result.empty
    assert "stage=score_fund scheme_code=BAD123" in caplog.text
    assert "pop index out of range" in caplog.text
