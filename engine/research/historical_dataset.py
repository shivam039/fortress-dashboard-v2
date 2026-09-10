"""Build point-in-time score datasets from archived input bundles."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sqlite3
import tempfile
from contextlib import closing
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

HORIZONS = (5, 10, 20, 60)
FILES = ('sessions', 'membership', 'runs', 'snapshots', 'prices')
SCORES = {
    'fortress_score': 'Score',
    'technical_score': 'Technical_Score',
    'fundamental_score': 'Fundamental_Score',
    'sentiment_score': 'Sentiment_Score',
    'context_score': 'Context_Score',
}
FEATURES = (
    'Price', 'RSI', 'RS_6M', 'RS_Composite', 'RS_Rank', 'RS_Score',
    'Avg_Value_20D_Cr', 'Market_Cap_Cr', 'Debt_To_Equity',
    'Vol_Surge_Ratio', 'Dist_52W_High_Pct', 'Extension_Pct', 'Is_Coiling',
    'Technical_Raw', 'Fundamental_Raw', 'Sentiment_Raw', 'Context_Raw',
    'Sector_Rotation_Bonus', 'Sector_RSI_Z', 'Sector_Conviction_Z',
    'Regime_Multiplier', 'India_VIX', 'Score_Pre_Regime', 'Black_Swan_Flag',
    'Avoid_Flag', 'Liquidity_Flag',
)
SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE sessions (date TEXT PRIMARY KEY, cutoff TEXT NOT NULL);
CREATE TABLE runs (run_id TEXT PRIMARY KEY, provenance_json TEXT NOT NULL);
CREATE TABLE prices (
    date TEXT NOT NULL REFERENCES sessions(date), symbol TEXT NOT NULL,
    close REAL, PRIMARY KEY (date, symbol)
);
CREATE TABLE observations (
    date TEXT NOT NULL REFERENCES sessions(date), symbol TEXT NOT NULL,
    membership_available_at TEXT NOT NULL,
    run_id TEXT REFERENCES runs(run_id), status TEXT NOT NULL,
    fortress_score REAL, technical_score REAL, fundamental_score REAL,
    sentiment_score REAL, context_score REAL,
    market_regime TEXT, sector TEXT, quality_gate_pass INTEGER,
    quality_gate_failures TEXT, features_json TEXT NOT NULL,
    PRIMARY KEY (date, symbol)
);
CREATE TABLE labels (
    date TEXT NOT NULL, symbol TEXT NOT NULL, horizon INTEGER NOT NULL,
    target_date TEXT REFERENCES sessions(date), forward_return REAL,
    status TEXT NOT NULL,
    PRIMARY KEY (date, symbol, horizon),
    FOREIGN KEY (date, symbol) REFERENCES observations(date, symbol)
);
"""


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=False, allow_nan=False)


def _reject_constant(value: str) -> None:
    raise ValueError('JSON numbers must be finite: ' + value)


def _object(pairs: list) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate JSON key: ' + key)
        result[key] = value
    return result


def _json(data: str) -> Any:
    return json.loads(data, parse_constant=_reject_constant,
                      object_pairs_hook=_object)


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(field + ' must be a nonempty string')
    return value


def _day(value: Any) -> str:
    _text(value, 'date')
    if date.fromisoformat(value).isoformat() != value:
        raise ValueError('date must be YYYY-MM-DD')
    return value


def _instant(value: Any) -> datetime:
    value = _text(value, 'timestamp')
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('timestamp requires an explicit timezone')
    return parsed.astimezone(timezone.utc)


def _number(value: Any, field: str) -> float | None:
    if value is None:
        return None
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(value)):
        raise ValueError(field + ' must be a finite number or null')
    return float(value)


def _unique(mapping: dict, key: Any, value: Any) -> None:
    if key in mapping:
        raise ValueError('duplicate key: ' + str(key))
    mapping[key] = value


def _load(bundle: Path) -> tuple:
    hashes, data = {}, {}
    for name in ('manifest.json', *(f'{n}.jsonl' for n in FILES)):
        payload = (bundle / name).read_bytes()
        hashes[name] = hashlib.sha256(payload).hexdigest()
        content = payload.decode('utf-8')
        data[name] = (_json(content) if name == 'manifest.json' else
                      [_json(line) for line in content.splitlines()
                       if line.strip()])
    manifest = data.pop('manifest.json')
    if manifest.get('schema_version') != 1:
        raise ValueError('unsupported schema_version')
    if manifest.get('price_convention') != 'unadjusted_close':
        raise ValueError('price_convention must be unadjusted_close')
    _text(manifest.get('calendar'), 'calendar')
    for name in ('sessions', 'membership', 'prices'):
        _text(manifest.get('sources', {}).get(name), 'source ' + name)
    return manifest, hashes, {n: data[n + '.jsonl'] for n in FILES}


def _validate(data: dict) -> tuple:
    sessions, members, runs, snapshots, prices = {}, {}, {}, {}, {}
    session_zones, run_symbols = {}, {}
    for row in data['sessions']:
        day = _day(row['date'])
        cutoff = _instant(row['cutoff'])
        # Compare the declared local session date before conversion to UTC.
        local = datetime.fromisoformat(row['cutoff'].replace('Z', '+00:00'))
        if local.date().isoformat() != day:
            raise ValueError('cutoff must belong to its local session date')
        _unique(sessions, day, cutoff)
        session_zones[day] = local.tzinfo
    if not sessions:
        raise ValueError('sessions cannot be empty')
    ordered = [sessions[d] for d in sorted(sessions)]
    if ordered != sorted(set(ordered)):
        raise ValueError('session cutoffs must be strictly increasing')
    for row in data['membership']:
        key = (_day(row['date']), _text(row['symbol'], 'symbol'))
        if key[0] not in sessions:
            raise ValueError('membership date is not a session')
        known = _instant(row['available_at'])
        if known > sessions[key[0]]:
            raise ValueError('membership available after cutoff')
        _unique(members, key, known.isoformat())
    for row in data['runs']:
        run_id = _text(row['run_id'], 'run_id')
        day = _day(row['date'])
        if day not in sessions:
            raise ValueError('run date is not a session')
        scored = _instant(row['scored_at'])
        # No assigning tomorrow's or yesterday's snapshot to today's session.
        zone = session_zones[day]
        if scored.astimezone(zone).date().isoformat() != day:
            raise ValueError('scored_at must belong to run session date')
        _text(row.get('scoring_revision'), 'scoring_revision')
        if not isinstance(row.get('scoring_config'), dict):
            raise TypeError('scoring_config must be an archived object')
        universe = row.get('universe')
        if not isinstance(universe, list) or not universe:
            raise ValueError('run universe must be a nonempty list')
        for symbol in universe:
            _text(symbol, 'universe symbol')
        if len(set(universe)) != len(universe):
            raise ValueError('duplicate run universe symbol')
        inputs = row.get('inputs')
        if not isinstance(inputs, list) or not inputs:
            raise ValueError('run inputs provenance is required')
        for source in inputs:
            _text(source.get('source'), 'input source')
            digest = source.get('sha256', '')
            if (not isinstance(digest, str) or len(digest) != 64
                    or any(c not in '0123456789abcdef' for c in digest)):
                raise ValueError('input sha256 must be a SHA-256 hex digest')
            if (_instant(source['available_at']) > scored
                    or _instant(source['observed_through']) > scored):
                raise ValueError('input timestamps exceed scored_at')
        _unique(runs, run_id, row)
        run_symbols[run_id] = set()
    for row in data['snapshots']:
        run_id, symbol = row['run_id'], _text(row['symbol'], 'symbol')
        if run_id not in runs:
            raise ValueError('snapshot references unknown run')
        if symbol not in runs[run_id]['universe']:
            raise ValueError('snapshot symbol absent from run universe')
        raw = row['raw_data']
        if not isinstance(raw, dict):
            raise TypeError('raw_data must be an object')
        # Reject nonfinite values even in unselected feature fields.
        canonical(raw)
        for field in SCORES.values():
            value = _number(raw.get(field), field)
            if value is not None and not 0 <= value <= 100:
                raise ValueError(field + ' must be within [0, 100]')
        gate = raw.get('Quality_Gate_Pass')
        if gate is not None and not isinstance(gate, bool):
            raise ValueError('Quality_Gate_Pass must be boolean or null')
        for field in ('Market_Regime', 'Sector', 'Quality_Gate_Failures'):
            if raw.get(field) is not None and not isinstance(raw[field], str):
                raise ValueError(field + ' must be string or null')
        _unique(snapshots, (run_id, symbol), raw)
        run_symbols[run_id].add(symbol)
    for run_id, run in runs.items():
        if run_symbols[run_id] != set(run['universe']):
            raise ValueError('snapshots must cover the complete run universe')
    for row in data['prices']:
        day, symbol = _day(row['date']), _text(row['symbol'], 'symbol')
        if day not in sessions:
            raise ValueError('price date is not a session')
        close = _number(row['close'], 'close')
        if close is not None and close <= 0:
            raise ValueError('close must be positive or null')
        _unique(prices, (day, symbol), close)
    return sessions, members, runs, snapshots, prices


def _label(days: list, index: int, symbol: str, horizon: int,
           prices: dict) -> tuple:
    if index + horizon >= len(days):
        return None, None, 'outside_calendar'
    target = days[index + horizon]
    base = prices.get((days[index], symbol))
    future = prices.get((target, symbol))
    if base is None:
        return target, None, 'missing_base_price'
    if future is None:
        return target, None, 'missing_target_price'
    value = future / base - 1
    if not math.isfinite(value):
        raise ValueError('forward return is not finite')
    return target, value, 'ok'


def build_dataset(bundle: Path, output: Path, start: str | None = None,
                  end: str | None = None) -> None:
    """Validate an immutable bundle and create a new SQLite dataset.

    start/end are inclusive observation bounds only. Future prices and sessions
    are retained for labels. Existing files are never overwritten.
    """
    bundle, output = Path(bundle), Path(output)
    if output.exists():
        raise FileExistsError(output)
    manifest, hashes, data = _load(bundle)
    sessions, members, runs, snapshots, prices = _validate(data)
    # Content-addressed archives bind provenance to the actual saved inputs.
    for digest in sorted({source['sha256'] for run in runs.values()
                          for source in run['inputs']}):
        archive = bundle / 'inputs' / digest
        with archive.open('rb') as stream:
            hasher = hashlib.sha256()
            for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                hasher.update(chunk)
        if hasher.hexdigest() != digest:
            raise ValueError('input archive SHA-256 mismatch: ' + digest)
        hashes['inputs/' + digest] = digest
    days = sorted(sessions)
    start, end = _day(start or days[0]), _day(end or days[-1])
    if start > end:
        raise ValueError('start must not exceed end')
    keys = sorted(k for k in members if start <= k[0] <= end)
    if not keys:
        raise ValueError('no membership observations within date bounds')
    candidates = {}
    for (run_id, symbol), raw in snapshots.items():
        run = runs[run_id]
        day, scored = run['date'], _instant(run['scored_at'])
        if scored <= sessions[day]:
            key = day, symbol
            rank = scored, run_id
            if key not in candidates or rank > candidates[key][0]:
                candidates[key] = rank, raw
    metadata = {
        'schema_version': 1, 'methodology': 'fortress-r1-snapshot-v1',
        'manifest': manifest, 'input_sha256': hashes,
        'builder_sha256': hashlib.sha256(
            Path(__file__).read_bytes()
        ).hexdigest(),
        'observation_start': start, 'observation_end': end,
        'horizons': HORIZONS,
        'return_convention': 'close[T+h]/close[T]-1; unadjusted; decimal',
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.fortress-r1-',
                                     dir=output.parent)
    os.close(fd)
    temp = Path(temporary)
    try:
        with closing(sqlite3.connect(temp)) as db, db:
            db.executescript(SCHEMA)
            db.executemany('INSERT INTO metadata VALUES (?, ?)',
                           [(k, canonical(v))
                            for k, v in sorted(metadata.items())])
            db.executemany('INSERT INTO sessions VALUES (?, ?)',
                           [(d, sessions[d].isoformat()) for d in days])
            used_runs = {candidates[k][0][1] for k in keys if k in candidates}
            db.executemany('INSERT INTO runs VALUES (?, ?)',
                           [(r, canonical(runs[r]))
                            for r in sorted(used_runs)])
            db.executemany('INSERT INTO prices VALUES (?, ?, ?)',
                           [(d, s, v) for (d, s), v in sorted(prices.items())])
            positions = {day: i for i, day in enumerate(days)}
            for day, symbol in keys:
                selected = candidates.get((day, symbol))
                run_id = selected[0][1] if selected else None
                raw = selected[1] if selected else {}
                status = ('missing_snapshot' if selected is None else
                          'missing_score' if raw.get('Score') is None else
                          'ok')
                values = (
                    day, symbol, members[(day, symbol)], run_id, status,
                    *(raw.get(f) for f in SCORES.values()),
                    raw.get('Market_Regime'), raw.get('Sector'),
                    raw.get('Quality_Gate_Pass'),
                    raw.get('Quality_Gate_Failures'),
                    canonical({f: raw[f] for f in FEATURES if f in raw}),
                )
                db.execute('INSERT INTO observations VALUES ('
                           + ','.join('?' for _ in values) + ')', values)
                for horizon in HORIZONS:
                    label = _label(days, positions[day], symbol, horizon,
                                   prices)
                    db.execute('INSERT INTO labels VALUES (?,?,?,?,?,?)',
                               (day, symbol, horizon, *label))
        # Same-directory hard link publishes the completed file atomically
        # and fails if another process has already created the destination.
        os.link(temp, output)
    finally:
        temp.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--start')
    parser.add_argument('--end')
    args = parser.parse_args()
    try:
        build_dataset(args.bundle, args.output, args.start, args.end)
    except (ValueError, KeyError, TypeError, OSError) as exc:
        parser.exit(2, f'Invalid dataset build: {exc}\n')
    print(f'Created {args.output}')


if __name__ == '__main__':
    main()
