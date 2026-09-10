"""Synthetic fixtures test methodology, not trading performance."""

import hashlib
import json
import sqlite3
from datetime import date, timedelta

import pytest
from research.historical_dataset import build_dataset


def write_jsonl(path, rows):
    path.write_text(''.join(json.dumps(row) + '\n' for row in rows))


@pytest.fixture
def bundle(tmp_path):
    days = []
    current = date(2025, 1, 2)
    while len(days) < 62:
        if current.weekday() < 5 and current != date(2025, 1, 8):
            days.append(current.isoformat())
        current += timedelta(days=1)
    archive = b'Synthetic input evidence, for tests only.\n'
    digest = hashlib.sha256(archive).hexdigest()
    (tmp_path / 'inputs').mkdir()
    (tmp_path / 'inputs' / digest).write_bytes(archive)
    rows = {
        'sessions': [
            {'date': day, 'cutoff': day + 'T16:00:00+05:30'}
            for day in days
        ],
        'membership': [
            {'date': day, 'symbol': 'TEST',
             'available_at': day + 'T09:00:00+05:30'}
            for day in days[:2]
        ],
        'runs': [{
            'run_id': 'run-1', 'date': days[0],
            'scored_at': days[0] + 'T15:59:00+05:30',
            'scoring_revision': 'archived-revision',
            'scoring_config': {'weights': {'technical': 0.5}},
            'universe': ['TEST'],
            'inputs': [{
                'source': 'immutable archive object',
                'sha256': digest,
                'available_at': days[0] + 'T15:58:00+05:30',
                'observed_through': days[0] + 'T15:58:00+05:30',
            }],
        }],
        'snapshots': [{
            'run_id': 'run-1', 'symbol': 'TEST',
            'raw_data': {
                'Score': 0, 'Technical_Score': 65.5,
                'Fundamental_Score': 42, 'Sentiment_Score': 50,
                'Context_Score': 23, 'Market_Regime': 'Range',
                'Sector': 'Synthetic', 'RSI': 55,
                'Quality_Gate_Pass': False,
                'Quality_Gate_Failures': 'Price<50',
            },
        }],
        'prices': [
            {'date': day, 'symbol': 'TEST', 'close': 100 + i}
            for i, day in enumerate(days)
        ],
    }
    manifest = {
        'schema_version': 1, 'calendar': 'synthetic-test-calendar',
        'price_convention': 'unadjusted_close',
        'sources': {
            'sessions': 'synthetic', 'membership': 'synthetic',
            'prices': 'synthetic',
        },
    }
    (tmp_path / 'manifest.json').write_text(json.dumps(manifest))
    for name, values in rows.items():
        write_jsonl(tmp_path / (name + '.jsonl'), values)
    return tmp_path, days, rows


def build(bundle, **kwargs):
    root, _, rows = bundle
    for name, values in rows.items():
        write_jsonl(root / (name + '.jsonl'), values)
    output = root / 'dataset.sqlite'
    build_dataset(root, output, **kwargs)
    conn = sqlite3.connect(output)
    conn.row_factory = sqlite3.Row
    return conn


def test_returns_use_exchange_sessions_and_preserve_scores(bundle):
    with build(bundle) as db:
        obs = db.execute('select * from observations order by date').fetchall()
        assert obs[0]['fortress_score'] == 0
        assert obs[0]['technical_score'] == 65.5
        assert obs[0]['quality_gate_pass'] == 0
        assert json.loads(obs[0]['features_json']) == {'RSI': 55}
        assert obs[1]['status'] == 'missing_snapshot'
        assert obs[1]['fortress_score'] is None
        labels = db.execute(
            'select * from labels where date=? order by horizon',
            (bundle[1][0],),
        ).fetchall()
        assert [r['horizon'] for r in labels] == [5, 10, 20, 60]
        for row in labels:
            assert row['target_date'] == bundle[1][row['horizon']]
            assert row['forward_return'] == pytest.approx(row['horizon'] / 100)
            assert row['status'] == 'ok'


def test_inclusive_date_bounds_do_not_truncate_future_prices(bundle):
    day = bundle[1][0]
    with build(bundle, start=day, end=day) as db:
        count = db.execute('select count(*) from observations').fetchone()[0]
        assert count == 1
        assert db.execute(
            'select forward_return from labels where horizon=60'
        ).fetchone()[0] == pytest.approx(0.6)


def test_missing_target_does_not_shift_to_next_available_price(bundle):
    bundle[2]['prices'].pop(5)
    with build(bundle) as db:
        row = db.execute(
            'select * from labels where date=? and horizon=5',
            (bundle[1][0],),
        ).fetchone()
        assert row['forward_return'] is None
        assert row['status'] == 'missing_target_price'
        assert row['target_date'] == bundle[1][5]


def test_missing_base_and_calendar_end(bundle):
    _root, days, rows = bundle
    rows['membership'].append({
        'date': days[-1], 'symbol': 'TEST',
        'available_at': days[-1] + 'T09:00:00+05:30',
    })
    rows['prices'].pop(0)
    with build(bundle) as db:
        assert db.execute(
            'select status from labels where date=? and horizon=5',
            (days[0],),
        ).fetchone()[0] == 'missing_base_price'
        row = db.execute(
            'select * from labels where date=? and horizon=5', (days[-1],)
        ).fetchone()
        assert row['status'] == 'outside_calendar'
        assert row['target_date'] is None
        assert row['forward_return'] is None


@pytest.mark.parametrize('field', ['available_at', 'observed_through'])
def test_future_input_is_rejected(bundle, field):
    bundle[2]['runs'][0]['inputs'][0][field] = (
        bundle[1][1] + 'T09:00:00+05:30'
    )
    with pytest.raises(ValueError, match='input.*scored_at'):
        build(bundle)
    assert not (bundle[0] / 'dataset.sqlite').exists()


def test_after_cutoff_run_not_backdated_or_carried_forward(bundle):
    bundle[2]['runs'][0]['scored_at'] = (
        bundle[1][0] + 'T16:00:01+05:30'
    )
    with build(bundle) as db:
        assert {r[0] for r in db.execute(
            'select status from observations'
        )} == {'missing_snapshot'}


def test_exact_cutoff_and_offset_equivalence(bundle):
    bundle[2]['runs'][0]['scored_at'] = bundle[1][0] + 'T10:30:00Z'
    with build(bundle) as db:
        assert db.execute(
            'select fortress_score from observations order by date'
        ).fetchone()[0] == 0


@pytest.mark.parametrize('mutation, message', [
    ('naive', 'timezone'), ('duplicate', 'duplicate'),
    ('membership_future', 'membership'), ('no_inputs', 'inputs'),
    ('bad_price', 'close'), ('nan', 'finite'),
    ('unknown_run', 'run'), ('partial_run', 'universe'),
])
def test_invalid_inputs_fail_closed(bundle, mutation, message):
    rows = bundle[2]
    if mutation == 'naive':
        rows['runs'][0]['scored_at'] = bundle[1][0] + 'T15:59:00'
    elif mutation == 'duplicate':
        rows['prices'].append(rows['prices'][0])
    elif mutation == 'membership_future':
        rows['membership'][0]['available_at'] = (
            bundle[1][1] + 'T09:00:00+05:30'
        )
    elif mutation == 'no_inputs':
        rows['runs'][0]['inputs'] = []
    elif mutation == 'bad_price':
        rows['prices'][0]['close'] = 0
    elif mutation == 'nan':
        rows['snapshots'][0]['raw_data']['Score'] = float('nan')
    elif mutation == 'unknown_run':
        rows['snapshots'][0]['run_id'] = 'absent'
    else:
        rows['runs'][0]['universe'].append('MISSING')
    with pytest.raises(ValueError, match=message):
        build(bundle)
    assert not (bundle[0] / 'dataset.sqlite').exists()


def test_latest_eligible_run_and_stable_tie_break(bundle):
    rows = bundle[2]
    newer = dict(rows['runs'][0], run_id='run-2')
    rows['runs'].append(newer)
    rows['snapshots'].append({
        'run_id': 'run-2', 'symbol': 'TEST', 'raw_data': {'Score': 82},
    })
    with build(bundle) as db:
        assert db.execute(
            'select fortress_score from observations order by date'
        ).fetchone()[0] == 82


def test_reproducible_bytes_manifest_and_no_overwrite(bundle):
    with build(bundle) as db:
        manifest = dict(db.execute('select key, value from metadata'))
        hashes = json.loads(manifest['input_sha256'])
        assert hashes['prices.jsonl'] == hashlib.sha256(
            (bundle[0] / 'prices.jsonl').read_bytes()
        ).hexdigest()
    second = bundle[0] / 'second.sqlite'
    build_dataset(bundle[0], second)
    assert second.read_bytes() == (bundle[0] / 'dataset.sqlite').read_bytes()
    before = second.read_bytes()
    with pytest.raises(FileExistsError):
        build_dataset(bundle[0], second)
    assert second.read_bytes() == before


@pytest.mark.parametrize('start,end', [
    ('2025-02-01', '2025-01-01'), ('2025-01-04', '2025-01-04'),
])
def test_invalid_or_empty_bounds(bundle, start, end):
    with pytest.raises(ValueError):
        build(bundle, start=start, end=end)


def test_negative_return_symbol_isolation_and_null_price(bundle):
    rows = bundle[2]
    rows['prices'][5]['close'] = 90
    rows['prices'][10]['close'] = None
    rows['prices'].append({
        'date': bundle[1][10], 'symbol': 'OTHER', 'close': 150,
    })
    with build(bundle) as db:
        labels = dict(db.execute(
            'select horizon, forward_return from labels where date=?',
            (bundle[1][0],),
        ))
        assert labels[5] == pytest.approx(-0.1)
        assert labels[10] is None
        assert db.execute('pragma integrity_check').fetchone()[0] == 'ok'
        assert db.execute('pragma foreign_key_check').fetchall() == []


def test_future_run_and_prices_cannot_change_past_score(bundle):
    with build(bundle) as db:
        before = tuple(db.execute(
            'select * from observations order by date'
        ).fetchone())
    (bundle[0] / 'dataset.sqlite').unlink()
    rows = bundle[2]
    rows['prices'][5]['close'] = 500
    rows['runs'].append(dict(
        rows['runs'][0], run_id='future', date=bundle[1][1],
        scored_at=bundle[1][1] + 'T15:59:00+05:30',
    ))
    rows['snapshots'].append({
        'run_id': 'future', 'symbol': 'TEST', 'raw_data': {'Score': 100},
    })
    with build(bundle) as db:
        assert tuple(db.execute(
            'select * from observations order by date'
        ).fetchone()) == before
        assert db.execute(
            'select forward_return from labels where date=? and horizon=5',
            (bundle[1][0],),
        ).fetchone()[0] == 4.0


def test_missing_components_are_null_and_not_live_defaults(bundle):
    bundle[2]['snapshots'][0]['raw_data'] = {'RSI': 53}
    with build(bundle) as db:
        obs = db.execute(
            'select * from observations order by date'
        ).fetchone()
        assert obs['status'] == 'missing_score'
        for field in ('fortress_score', 'fundamental_score', 'sector',
                      'market_regime', 'quality_gate_pass'):
            assert obs[field] is None


def test_cli_regeneration(bundle):
    import subprocess
    import sys

    output = bundle[0] / 'cli.sqlite'
    result = subprocess.run(
        [sys.executable, '-m', 'engine.research.historical_dataset',
         '--bundle', str(bundle[0]), '--output', str(output),
         '--start', bundle[1][0], '--end', bundle[1][0]],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    with sqlite3.connect(output) as db:
        assert db.execute('select count(*) from labels').fetchone()[0] == 4


def test_tampered_input_archive_rejected(bundle):
    digest = bundle[2]['runs'][0]['inputs'][0]['sha256']
    (bundle[0] / 'inputs' / digest).write_bytes(b'changed')
    with pytest.raises(ValueError, match='SHA-256 mismatch'):
        build(bundle)
    assert not (bundle[0] / 'dataset.sqlite').exists()
