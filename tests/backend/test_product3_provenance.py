from utils.db import create_paper_trade, fetch_paper_trades


def test_paper_trade_persists_immutable_oracle_provenance():
    trade_id = create_paper_trade({
        'signal_id': 9201, 'source_type': 'ORACLE_SIGNAL',
        'oracle_version': 'oracle-v1', 'oracle_decision': 'POSITIVE',
        'source_scan_id': 77, 'symbol': 'PRODUCT3.NS',
        'entry_timestamp': '2026-01-01', 'entry_price': 100,
        'quantity': 1, 'notional': 100, 'stop_price': 90, 'target_price': 120,
    })
    row = fetch_paper_trades(signal_id=9201)[0]
    assert row['trade_id'] == trade_id
    assert row['source_type'] == 'ORACLE_SIGNAL'
    assert row['oracle_version'] == 'oracle-v1'
    assert row['oracle_decision'] == 'POSITIVE'
    assert row['source_scan_id'] == 77
