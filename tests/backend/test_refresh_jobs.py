import pytest
from utils.db import record_refresh_job_start, record_refresh_job_done, get_last_refresh_job, _ensure_investment_tables

def test_refresh_jobs():
    _ensure_investment_tables()
    job_id = record_refresh_job_start("test_job", source="test")
    assert job_id > 0
    
    job = get_last_refresh_job("test_job")
    assert job is not None
    assert job["status"] == "running"
    
    record_refresh_job_done(job_id, status="done", records_refreshed=10)
    
    job_done = get_last_refresh_job("test_job")
    assert job_done["status"] == "done"
    assert job_done["records_refreshed"] == 10
