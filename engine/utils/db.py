# AI agents modifying this file: see /AI_AGENT_PROTOCOL.md — log every change
# via engine/utils/ai_audit.py:log_ai_change().
import functools
import json
import logging
import math
import os
import random
import sqlite3
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

import pandas as pd
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

try:
    from sqlalchemy import create_engine, text
    from sqlalchemy.exc import InterfaceError, OperationalError, ProgrammingError
    from sqlalchemy.exc import TimeoutError as SATimeoutError
except (
    ModuleNotFoundError
):  # pragma: no cover - defensive fallback for local env bootstrapping

    def text(sql: str) -> str:
        return sql

    class OperationalError(Exception):
        pass

    class InterfaceError(Exception):
        pass

    class ProgrammingError(Exception):
        pass

    class SATimeoutError(Exception):
        pass


logger = logging.getLogger(__name__)

# Force DB_MODE detection early
DB_MODE = "postgres" if "DATABASE_URL" in os.environ else "sqlite"
logger.info(f"DB mode detected: {DB_MODE}")

DB_NAME = "fortress_history.db"


def _encrypt_token(value: str) -> str:
    from utils.token_encryption import encrypt_broker_token

    return encrypt_broker_token(value)


def _decrypt_token(value: str) -> str:
    from utils.token_encryption import decrypt_broker_token

    return decrypt_broker_token(value)


def _sqlite_connection():
    # When moving to Neon as the default backend, this SQLite connection remains fallback-only.
    return sqlite3.connect(DB_NAME, timeout=15.0)


def _sqlite_only_mode() -> bool:
    backend = os.getenv("FORTRESS_DB_BACKEND", "").strip().lower()
    return backend in {"sqlite", "local"}


def _get_neon_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if url:
        return url
    raise ValueError(
        "Neon DB URL not found. Set the DATABASE_URL environment variable."
    )


# Module-level singleton for the SQLAlchemy engine (replaces @st.cache_resource)
_engine_singleton = None
_engine_lock = __import__("threading").Lock()


def get_db_engine():
    """
    Creates a SQLAlchemy engine with connection pooling best practices for Neon/Postgres.
    pool_pre_ping=True is critical to prevent 'SSL connection closed unexpectedly' errors.
    Thread-safe singleton — replaces the former @st.cache_resource.
    """
    global _engine_singleton
    if _engine_singleton is None:
        with _engine_lock:
            if _engine_singleton is None:
                db_url = _get_neon_url()
                _engine_singleton = create_engine(
                    db_url,
                    pool_pre_ping=True,
                    pool_recycle=300,
                    pool_size=5,
                    max_overflow=10,
                    pool_timeout=30,
                )
    return _engine_singleton


def _should_retry_db_error(exc: Exception) -> bool:
    if isinstance(
        exc, (OperationalError, InterfaceError, SATimeoutError, TimeoutError)
    ):
        return True
    if isinstance(exc, ProgrammingError):
        message = str(exc).lower()
        return (
            "undefinedtable" in message
            or 'relation "scan_history_details" does not exist' in message
        )
    return False


@functools.lru_cache(maxsize=1)
def _can_use_neon() -> bool:
    if _sqlite_only_mode():
        return False
    try:
        # Verify configuration is present before trying to connect.
        _ = _get_neon_url()
    except Exception as exc:
        logger.info("Neon unavailable, falling back to SQLite: %s", exc)
        return False

    try:
        # Lazy connectivity check; cache the result to avoid repeated log spam.
        engine = get_db_engine()
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception as exc:
        logger.warning("Neon unavailable, falling back to SQLite: %s", exc)
        return False


def get_db_backend() -> str:
    return "neon" if _can_use_neon() else "sqlite"


def get_table_name_from_universe(u):
    if "Mutual Funds" == u:
        return "scan_mf"
    if "Commodities" == u:
        return "scan_commodities"
    return "scan_entries"


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=4),
    retry=retry_if_exception(_should_retry_db_error),
    reraise=True,
)
def _exec(sql: str, params: Optional[Dict[str, Any]] = None):
    if _can_use_neon():
        engine = get_db_engine()
        with engine.begin() as conn:
            conn.execute(text(sql), params or {})
        return
    with _sqlite_connection() as conn:
        conn.execute(sql, params or {})


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=4),
    retry=retry_if_exception(_should_retry_db_error),
    reraise=True,
)
def _query(sql: str, params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """Execute a query and return results as list of dicts."""
    if _can_use_neon():
        engine = get_db_engine()
        with engine.connect() as conn:
            result = conn.execute(text(sql), params or {}).fetchall()
            return [dict(row._mapping) for row in result]
    with _sqlite_connection() as conn:
        cursor = conn.execute(sql, params or {})
        columns = [desc[0] for desc in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=4),
    retry=retry_if_exception(_should_retry_db_error),
    reraise=True,
)
def _read_df_cached(sql: str, params: Optional[Dict[str, Any]] = None) -> pd.DataFrame:
    """Read query (cache removed — callers handle their own caching if needed)."""
    engine = get_db_engine()
    with engine.connect() as conn:
        return pd.read_sql_query(text(sql), conn, params=params or {})


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=4),
    retry=retry_if_exception(_should_retry_db_error),
    reraise=True,
)
def _read_df_uncached(
    sql: str, params: Optional[Dict[str, Any]] = None
) -> pd.DataFrame:
    """Direct read for schema checks and fresh data."""
    engine = get_db_engine()
    with engine.connect() as conn:
        return pd.read_sql_query(text(sql), conn, params=params or {})


def _read_df(
    sql: str, params: Optional[Dict[str, Any]] = None, ttl: Optional[str] = None
) -> pd.DataFrame:
    if _can_use_neon():
        # Dispatch based on TTL
        use_cache = True
        if ttl is not None:
            try:
                seconds = (
                    pd.Timedelta(ttl).total_seconds()
                    if isinstance(ttl, str)
                    else float(ttl)
                )
                # If TTL is very short (< 60s), assume fresh data required -> uncached
                if seconds < 60:
                    use_cache = False
            except Exception:
                pass  # Fallback to cache if parse fails

        if use_cache:
            return _read_df_cached(sql, params)
        else:
            return _read_df_uncached(sql, params)

    with _sqlite_connection() as conn:
        return pd.read_sql_query(sql, conn, params=params or {})


def _ensure_scan_history_table_neon():
    _exec("""
        CREATE TABLE IF NOT EXISTS scan_history (
            id BIGSERIAL PRIMARY KEY,
            scan_timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            symbol TEXT,
            conviction_score NUMERIC,
            regime TEXT,
            sub_scores JSONB,
            raw_data JSONB
        )
        """)
    _exec(
        "CREATE INDEX IF NOT EXISTS idx_scan_history_timestamp ON scan_history (scan_timestamp DESC)"
    )
    _exec("CREATE INDEX IF NOT EXISTS idx_scan_history_symbol ON scan_history (symbol)")


def _postgres_has_table(table_name: str) -> bool:
    query = text("""
        SELECT EXISTS (
            SELECT FROM information_schema.tables
            WHERE table_schema = 'public'
              AND table_name = :table_name
        )
        """)
    try:
        engine = get_db_engine()
        with engine.connect() as conn:
            exists = conn.execute(query, {"table_name": table_name.lower()}).scalar()
        return bool(exists)
    except Exception as e:
        if "does not exist" in str(e).lower() or "closed" in str(e).lower():
            return False
        raise


def _postgres_has_column(table_name: str, column_name: str) -> bool:
    if not _postgres_has_table(table_name):
        return False

    query = text("""
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = :table_name
          AND column_name = :column_name
        LIMIT 1
        """)

    engine = get_db_engine()
    with engine.connect() as conn:
        exists = conn.execute(
            query,
            {
                "table_name": table_name.lower(),
                "column_name": column_name.lower(),
            },
        ).scalar()
    return bool(exists)


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=4),
    retry=retry_if_exception(_should_retry_db_error),
    reraise=True,
)
def _ensure_scan_history_details_neon():
    logger.info("Ensuring scan_history_details table...")

    # OPTIMIZATION: Check if table exists first to avoid unnecessary CREATE calls
    # and to potentially skip column checks if we just created it.
    table_exists = _postgres_has_table("scan_history_details")

    if not table_exists:
        # 1. Create with Full Schema
        try:
            _exec("""
                CREATE TABLE IF NOT EXISTS scan_history_details (
                    id BIGSERIAL PRIMARY KEY,
                    scan_timestamp TIMESTAMPTZ DEFAULT NOW(),
                    symbol TEXT NOT NULL,
                    conviction_score NUMERIC,
                    regime TEXT,
                    sub_scores JSONB,
                    raw_data JSONB,
                    price REAL,
                    target_price REAL,
                    rsi REAL,
                    ema200 REAL,
                    analyst_target_mean REAL,
                    volume REAL,
                    quality_gate_pass BOOLEAN DEFAULT TRUE,
                    liquidity_flag TEXT,
                    sector TEXT,
                    mcap_cr REAL,
                    avg_volume_cr REAL,
                    debt_to_equity REAL,
                    scan_id BIGINT,
                    pick_type TEXT
                )
                """)
            # If we just created the table with full schema, we assume it has all columns.
            return
        except Exception as exc:
            logger.error(f"Schema create failed: {exc}")
            raise

    # 2. Validate Schema & Evolve (Handle missing columns)
    required_columns = {
        "scan_timestamp": "TIMESTAMPTZ DEFAULT NOW()",
        "symbol": "TEXT NOT NULL",
        "conviction_score": "NUMERIC",
        "regime": "TEXT",
        "sub_scores": "JSONB",
        "raw_data": "JSONB",
        "price": "REAL",
        "target_price": "REAL",
        "rsi": "REAL",
        "ema200": "REAL",
        "analyst_target_mean": "REAL",
        "volume": "REAL",
        "quality_gate_pass": "BOOLEAN DEFAULT TRUE",
        "liquidity_flag": "TEXT",
        "sector": "TEXT",
        "mcap_cr": "REAL",
        "avg_volume_cr": "REAL",
        "debt_to_equity": "REAL",
        "scan_id": "BIGINT",
        "pick_type": "TEXT",
    }

    added_cols = []
    for column_name, column_type in required_columns.items():
        # Check if column exists, if not ADD it
        if not _postgres_has_column("scan_history_details", column_name):
            try:
                _exec(
                    f"ALTER TABLE scan_history_details ADD COLUMN IF NOT EXISTS {column_name} {column_type}"
                )
                added_cols.append(column_name)
            except Exception as exc:
                logger.warning(
                    "Could not ensure column %s on scan_history_details: %s",
                    column_name,
                    exc,
                )

    if added_cols:
        logger.info(f"Added missing columns: {added_cols}")
        st.toast(f"Added missing columns: {added_cols}", icon="🛠️")


# Missing SQLite helper restored - checks column existence via PRAGMA
def _sqlite_has_column(
    conn: sqlite3.Connection, table_name: str, column_name: str
) -> bool:
    """Helper for SQLite fallback - checks if column exists in table."""
    columns = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return any(column[1] == column_name for column in columns)


def _ensure_ticker_metadata_neon():
    _exec("""
        CREATE TABLE IF NOT EXISTS ticker_metadata (
            symbol TEXT PRIMARY KEY,
            info_json JSONB,
            news_json JSONB,
            cal_json  JSONB,
            earn_json JSONB,
            updated_at TIMESTAMPTZ DEFAULT NOW()
        )
        """)


def _ensure_ticker_metadata_sqlite(conn) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS ticker_metadata (
            symbol TEXT PRIMARY KEY,
            info_json TEXT,
            news_json TEXT,
            cal_json TEXT,
            earn_json TEXT,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)


def bulk_fetch_metadata(symbols: list, max_age_hours=12):
    """Bulk-read cached ticker metadata (info/news/calendar/earnings) for
    every symbol in `symbols` that has an entry no older than `max_age_hours`.

    This is the DB-backed fallback/prefetch for `stock_scanner.logic`'s
    per-symbol yfinance metadata calls (`.info`/`.news`/`.calendar`/
    `.earnings_dates`) — see `stock_scanner.logic.prefetch_metadata()`, which
    calls this before a scan's per-ticker loop so tickers with fresh cached
    data skip the live yfinance call entirely, and tickers where the live
    call fails mid-scan still have *something* other than a hard blank to
    fall back to.

    Works on both backends (previously Neon-only — SQLite always returned
    `{}` immediately, which silently made this whole cache a no-op for local
    dev and for any deployment not using Neon).

    Returns:
        Dict keyed by symbol; only symbols with a fresh-enough cached row are
        present (never a value of ``None`` for a missing symbol).
    """
    if not symbols:
        return {}

    try:
        if _can_use_neon():
            engine = get_db_engine()
            placeholders = ", ".join([f":sym_{i}" for i in range(len(symbols))])
            params = {f"sym_{i}": sym for i, sym in enumerate(symbols)}

            query = f"""
            SELECT symbol, info_json, news_json, cal_json, earn_json
            FROM ticker_metadata
            WHERE symbol IN ({placeholders})
            AND updated_at >= NOW() - INTERVAL '{max_age_hours} hours'
            """

            with engine.connect() as conn:
                res = conn.execute(text(query), params).fetchall()

            return {
                row[0]: {
                    "info_json": row[1] if row[1] else {},
                    "news_json": row[2] if row[2] else [],
                    "cal_json": row[3],
                    "earn_json": row[4],
                }
                for row in res
            }

        # SQLite path
        with _sqlite_connection() as conn:
            _ensure_ticker_metadata_sqlite(conn)
            placeholders = ", ".join([f":sym_{i}" for i in range(len(symbols))])
            params = {f"sym_{i}": sym for i, sym in enumerate(symbols)}
            params["cutoff"] = f"-{int(max_age_hours)} hours"

            query = f"""
            SELECT symbol, info_json, news_json, cal_json, earn_json
            FROM ticker_metadata
            WHERE symbol IN ({placeholders})
            AND updated_at >= datetime('now', :cutoff)
            """
            rows = conn.execute(query, params).fetchall()

        result = {}
        for symbol, info_json, news_json, cal_json, earn_json in rows:
            result[symbol] = {
                "info_json": json.loads(info_json) if info_json else {},
                "news_json": json.loads(news_json) if news_json else [],
                "cal_json": json.loads(cal_json) if cal_json else None,
                "earn_json": json.loads(earn_json) if earn_json else None,
            }
        return result
    except Exception as e:
        logger.error(f"Error fetching bulk metadata: {e}")
        return {}


def upsert_ticker_metadata_cache(symbol, metadata_dict):
    """Persist ticker metadata (info/news/calendar/earnings) for `symbol` so
    a later scan can read it back via `bulk_fetch_metadata()` instead of
    hitting yfinance live again. Works on both backends (previously
    Neon-only — see `bulk_fetch_metadata()`'s docstring)."""
    payload = {
        "symbol": symbol,
        "info_json": json.dumps(metadata_dict.get("info_json", {})),
        "news_json": json.dumps(metadata_dict.get("news_json", [])),
        "cal_json": json.dumps(metadata_dict.get("cal_json", {})),
        "earn_json": json.dumps(metadata_dict.get("earn_json", {})),
    }
    try:
        if _can_use_neon():
            query = """
            INSERT INTO ticker_metadata (symbol, info_json, news_json, cal_json, earn_json, updated_at)
            VALUES (:symbol, CAST(:info_json AS JSONB), CAST(:news_json AS JSONB), CAST(:cal_json AS JSONB), CAST(:earn_json AS JSONB), NOW())
            ON CONFLICT (symbol) DO UPDATE SET
                info_json = EXCLUDED.info_json,
                news_json = EXCLUDED.news_json,
                cal_json = EXCLUDED.cal_json,
                earn_json = EXCLUDED.earn_json,
                updated_at = EXCLUDED.updated_at
            """
            _exec(query, payload)
            return

        # SQLite path
        with _sqlite_connection() as conn:
            _ensure_ticker_metadata_sqlite(conn)
            conn.execute(
                """
                INSERT INTO ticker_metadata (symbol, info_json, news_json, cal_json, earn_json, updated_at)
                VALUES (:symbol, :info_json, :news_json, :cal_json, :earn_json, CURRENT_TIMESTAMP)
                ON CONFLICT(symbol) DO UPDATE SET
                    info_json = excluded.info_json,
                    news_json = excluded.news_json,
                    cal_json = excluded.cal_json,
                    earn_json = excluded.earn_json,
                    updated_at = excluded.updated_at
                """,
                payload,
            )
    except Exception as e:
        logger.error(f"Error upserting metadata for {symbol}: {e}")


# ─────────────────────────────────────────────
# OHLCV time-series cache  (mf_lab + commodities)
# ─────────────────────────────────────────────


def _ensure_ohlcv_cache_neon():
    _exec("""
        CREATE TABLE IF NOT EXISTS ohlcv_cache (
            symbol       TEXT NOT NULL,
            period       TEXT NOT NULL,
            ohlcv_json   JSONB,
            updated_at   TIMESTAMPTZ DEFAULT NOW(),
            PRIMARY KEY (symbol, period)
        )
    """)


def _ensure_ohlcv_cache_sqlite(conn) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS ohlcv_cache (
            symbol       TEXT NOT NULL,
            period       TEXT NOT NULL,
            ohlcv_json   TEXT,
            updated_at   TEXT DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (symbol, period)
        )
    """)


def fetch_ohlcv_cache(
    symbol: str, period: str = "5y", max_age_hours: int = 20
) -> Optional[pd.DataFrame]:
    """Return a DataFrame from the cache if fresh, else None.

    Works on both backends. Previously SQLite always returned None here,
    which made this whole cache a no-op for local dev (FORTRESS_DB_BACKEND=
    sqlite, the documented default) — every mf_lab benchmark/OHLCV lookup
    hit yfinance live every single call, same bug pattern as the
    ticker_metadata cache that only worked on Neon before it was ported.
    """
    try:
        import io

        if _can_use_neon():
            engine = get_db_engine()
            with engine.connect() as conn:
                row = conn.execute(
                    text("""
                    SELECT ohlcv_json FROM ohlcv_cache
                    WHERE symbol = :sym AND period = :period
                      AND updated_at >= NOW() - INTERVAL :age_h
                    """),
                    {"sym": symbol, "period": period, "age_h": f"{max_age_hours} hours"},
                ).fetchone()
            if row and row[0]:
                df = pd.read_json(io.StringIO(json.dumps(row[0])), orient="split")
                df.index = pd.to_datetime(df.index)
                return df
            return None

        # SQLite path
        with _sqlite_connection() as conn:
            _ensure_ohlcv_cache_sqlite(conn)
            row = conn.execute(
                """
                SELECT ohlcv_json FROM ohlcv_cache
                WHERE symbol = :sym AND period = :period
                  AND updated_at >= datetime('now', :cutoff)
                """,
                {"sym": symbol, "period": period, "cutoff": f"-{int(max_age_hours)} hours"},
            ).fetchone()
        if row and row[0]:
            df = pd.read_json(io.StringIO(row[0]), orient="split")
            df.index = pd.to_datetime(df.index)
            return df
    except Exception as e:
        logger.error("ohlcv_cache fetch error for %s: %s", symbol, e)
    return None


def upsert_ohlcv_cache(symbol: str, period: str, df: "pd.DataFrame"):
    """Persist an OHLCV DataFrame into the cache for future cache hits.
    Works on both backends (previously Neon-only — see `fetch_ohlcv_cache`'s
    docstring)."""
    if df is None or df.empty:
        return
    try:
        payload = json.dumps(json.loads(df.to_json(date_format="iso", orient="split")))

        if _can_use_neon():
            _exec(
                """
                INSERT INTO ohlcv_cache (symbol, period, ohlcv_json, updated_at)
                VALUES (:sym, :period, CAST(:payload AS JSONB), NOW())
                ON CONFLICT (symbol, period) DO UPDATE
                  SET ohlcv_json = EXCLUDED.ohlcv_json,
                      updated_at = EXCLUDED.updated_at
                """,
                {"sym": symbol, "period": period, "payload": payload},
            )
            return

        # SQLite path
        with _sqlite_connection() as conn:
            _ensure_ohlcv_cache_sqlite(conn)
            conn.execute(
                """
                INSERT INTO ohlcv_cache (symbol, period, ohlcv_json, updated_at)
                VALUES (:sym, :period, :payload, CURRENT_TIMESTAMP)
                ON CONFLICT(symbol, period) DO UPDATE SET
                    ohlcv_json = excluded.ohlcv_json,
                    updated_at = excluded.updated_at
                """,
                {"sym": symbol, "period": period, "payload": payload},
            )
    except Exception as e:
        logger.error("ohlcv_cache upsert error for %s: %s", symbol, e)


# ─────────────────────────────────────────────
# Options chain snapshot cache  (options_algo)
# ─────────────────────────────────────────────


def _ensure_options_chain_cache_neon():
    _exec("""
        CREATE TABLE IF NOT EXISTS options_chain_cache (
            symbol      TEXT NOT NULL,
            expiry_date TEXT NOT NULL,
            chain_json  JSONB,
            spot        REAL,
            updated_at  TIMESTAMPTZ DEFAULT NOW(),
            PRIMARY KEY (symbol, expiry_date)
        )
    """)


def fetch_options_chain_cache(symbol: str, expiry: str, max_age_minutes: int = 5):
    """Return cached option-chain dict {chain_json, spot} if fresh, else None."""
    if not _can_use_neon():
        return None
    try:
        engine = get_db_engine()
        with engine.connect() as conn:
            row = conn.execute(
                text("""
                SELECT chain_json, spot FROM options_chain_cache
                WHERE symbol = :sym AND expiry_date = :expiry
                  AND updated_at >= NOW() - INTERVAL :age_m
                """),
                {
                    "sym": symbol,
                    "expiry": expiry,
                    "age_m": f"{max_age_minutes} minutes",
                },
            ).fetchone()
        if row and row[0]:
            import io

            import pandas as pd

            chain_df = pd.read_json(io.StringIO(json.dumps(row[0])), orient="split")
            return {"chain": chain_df, "spot": float(row[1] or 0)}
    except Exception as e:
        logger.error("options_chain_cache fetch error %s/%s: %s", symbol, expiry, e)
    return None


def upsert_options_chain_cache(
    symbol: str, expiry: str, chain_df: "pd.DataFrame", spot: float
):
    """Save an option-chain snapshot to Neon."""
    if not _can_use_neon() or chain_df is None or chain_df.empty:
        return
    try:
        payload = json.dumps(
            json.loads(chain_df.to_json(date_format="iso", orient="split"))
        )
        _exec(
            """
            INSERT INTO options_chain_cache (symbol, expiry_date, chain_json, spot, updated_at)
            VALUES (:sym, :expiry, CAST(:payload AS JSONB), :spot, NOW())
            ON CONFLICT (symbol, expiry_date) DO UPDATE
              SET chain_json = EXCLUDED.chain_json,
                  spot       = EXCLUDED.spot,
                  updated_at = EXCLUDED.updated_at
            """,
            {"sym": symbol, "expiry": expiry, "payload": payload, "spot": spot},
        )
    except Exception as e:
        logger.error("options_chain_cache upsert error %s/%s: %s", symbol, expiry, e)


def _ensure_mf_scheme_catalog_neon():
    """Create the MF scheme catalog table for monthly caching of 4000+ schemes."""
    _exec("""
        CREATE TABLE IF NOT EXISTS mf_scheme_catalog (
            scheme_code TEXT PRIMARY KEY,
            scheme_name TEXT NOT NULL,
            category TEXT,
            type TEXT,
            subcategory TEXT,
            amc_code TEXT,
            amc_name TEXT,
            isin_div_payout TEXT,
            isin_div_reinvest TEXT,
            isin_growth TEXT,
            cached_date DATE DEFAULT CURRENT_DATE
        )
        """)
    _exec("CREATE INDEX IF NOT EXISTS idx_mf_scheme_type ON mf_scheme_catalog (type)")
    _exec(
        "CREATE INDEX IF NOT EXISTS idx_mf_scheme_category ON mf_scheme_catalog (category)"
    )
    _exec(
        "CREATE INDEX IF NOT EXISTS idx_mf_scheme_cached_date ON mf_scheme_catalog (cached_date DESC)"
    )


def _ensure_mf_scheme_batches_neon():
    """Create the MF scheme batches table for pre-computed type/category statistics."""
    _exec("""
        CREATE TABLE IF NOT EXISTS mf_scheme_batches (
            type TEXT NOT NULL,
            category TEXT NOT NULL,
            scheme_count INT DEFAULT 0,
            amc_count INT DEFAULT 0,
            cached_date DATE DEFAULT CURRENT_DATE,
            PRIMARY KEY (type, category, cached_date)
        )
        """)
    _exec("CREATE INDEX IF NOT EXISTS idx_mf_batches_type ON mf_scheme_batches (type)")
    _exec(
        "CREATE INDEX IF NOT EXISTS idx_mf_batches_category ON mf_scheme_batches (category)"
    )
    _exec(
        "CREATE INDEX IF NOT EXISTS idx_mf_batches_cached_date ON mf_scheme_batches (cached_date DESC)"
    )


def _ensure_app_users_neon():
    _exec("""
        CREATE TABLE IF NOT EXISTS app_users (
            user_id BIGSERIAL PRIMARY KEY,
            username TEXT NOT NULL UNIQUE,
            full_name TEXT,
            email TEXT,
            phone TEXT,
            password_hash TEXT,
            account_status TEXT DEFAULT 'Active',
            created_at TIMESTAMPTZ DEFAULT NOW(),
            last_login_at TIMESTAMPTZ
        )
        """)
    _exec("CREATE INDEX IF NOT EXISTS idx_app_users_username ON app_users (username)")


def _ensure_user_broker_connections_neon():
    _exec("""
        CREATE TABLE IF NOT EXISTS user_broker_connections (
            connection_id BIGSERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL REFERENCES app_users(user_id) ON DELETE CASCADE,
            broker_name TEXT NOT NULL,
            broker_client_id TEXT,
            access_token_encrypted TEXT,
            refresh_token_encrypted TEXT,
            expires_at TIMESTAMPTZ,
            connected_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW(),
            is_active BOOLEAN DEFAULT TRUE,
            metadata_json JSONB,
            UNIQUE (user_id, broker_name)
        )
        """)
    _exec(
        "CREATE INDEX IF NOT EXISTS idx_broker_connections_user ON user_broker_connections (user_id)"
    )
    _exec(
        "CREATE INDEX IF NOT EXISTS idx_broker_connections_active ON user_broker_connections (is_active)"
    )


def _ensure_fortress_orders_neon():
    _exec("""
        CREATE TABLE IF NOT EXISTS fortress_orders (
            order_id BIGSERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL REFERENCES app_users(user_id) ON DELETE CASCADE,
            symbol TEXT NOT NULL,
            stock_name TEXT,
            order_type TEXT NOT NULL,
            quantity NUMERIC NOT NULL,
            price NUMERIC,
            status TEXT DEFAULT 'Pending',
            broker_name TEXT,
            broker_order_id TEXT,
            notes TEXT,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW()
        )
        """)
    _exec(
        "CREATE INDEX IF NOT EXISTS idx_fortress_orders_user ON fortress_orders (user_id)"
    )
    _exec(
        "CREATE INDEX IF NOT EXISTS idx_fortress_orders_status ON fortress_orders (status)"
    )
    _exec(
        "CREATE INDEX IF NOT EXISTS idx_fortress_orders_created_at ON fortress_orders (created_at DESC)"
    )


def _ensure_pick_outcomes_neon():
    _exec("""
        CREATE TABLE IF NOT EXISTS pick_outcomes (
            id              BIGSERIAL PRIMARY KEY,
            user_id         BIGINT NOT NULL REFERENCES app_users(user_id) ON DELETE CASCADE,
            symbol          TEXT NOT NULL,
            universe        TEXT,
            pick_date       TIMESTAMPTZ NOT NULL,
            entry_price     REAL NOT NULL,
            target_price    REAL NOT NULL,
            target_2_price  REAL,
            stop_loss       REAL NOT NULL,
            score           REAL,
            strategy        TEXT,
            sector          TEXT,
            outcome         TEXT DEFAULT 'TRAILING',
            outcome_date    TIMESTAMPTZ,
            outcome_price   REAL,
            max_price       REAL,
            min_price       REAL,
            pnl_pct         REAL,
            days_to_resolve INT,
            scan_id         BIGINT,
            created_at      TIMESTAMPTZ DEFAULT NOW(),
            updated_at      TIMESTAMPTZ DEFAULT NOW(),
            UNIQUE (user_id, symbol, pick_date)
        )
        """)
    _exec(
        "CREATE INDEX IF NOT EXISTS idx_pick_outcomes_user ON pick_outcomes (user_id)"
    )
    _exec(
        "CREATE INDEX IF NOT EXISTS idx_pick_outcomes_outcome ON pick_outcomes (outcome)"
    )


def upsert_pick_outcome(
    user_id: int,
    symbol: str,
    pick_date,
    entry_price: float,
    target_price: float,
    stop_loss: float,
    target_2_price: float = None,
    score: float = None,
    strategy: str = None,
    sector: str = None,
    universe: str = None,
    scan_id: int = None,
):
    """Insert or update a pick outcome record for a user."""
    _exec(
        """
        INSERT INTO pick_outcomes
            (user_id, symbol, universe, pick_date, entry_price, target_price, target_2_price,
             stop_loss, score, strategy, sector, outcome, max_price, min_price, scan_id)
        VALUES
            (:user_id, :symbol, :universe, :pick_date, :entry_price, :target_price, :target_2_price,
             :stop_loss, :score, :strategy, :sector, 'TRAILING', :entry_price, :entry_price, :scan_id)
        ON CONFLICT (user_id, symbol, pick_date) DO UPDATE SET
            entry_price = EXCLUDED.entry_price,
            target_price = EXCLUDED.target_price,
            target_2_price = EXCLUDED.target_2_price,
            stop_loss = EXCLUDED.stop_loss,
            score = EXCLUDED.score,
            strategy = EXCLUDED.strategy,
            sector = EXCLUDED.sector,
            updated_at = NOW()
        """,
        {
            "user_id": user_id,
            "symbol": symbol,
            "universe": universe,
            "pick_date": pick_date,
            "entry_price": entry_price,
            "target_price": target_price,
            "target_2_price": target_2_price,
            "stop_loss": stop_loss,
            "score": score,
            "strategy": strategy,
            "sector": sector,
            "scan_id": scan_id,
        },
    )


def get_user_picks(user_id: int, status: str = None) -> pd.DataFrame:
    """Fetch pick outcomes for a specific user, optionally filtered by outcome status."""
    if status:
        return _read_df(
            """
            SELECT * FROM pick_outcomes
            WHERE user_id = :user_id AND outcome = :status
            ORDER BY pick_date DESC
            """,
            {"user_id": user_id, "status": status},
        )
    return _read_df(
        """
        SELECT * FROM pick_outcomes
        WHERE user_id = :user_id
        ORDER BY pick_date DESC
        """,
        {"user_id": user_id},
    )


def get_all_trailing_picks() -> pd.DataFrame:
    """Fetch ALL users' trailing picks for bulk evaluation."""
    return _read_df("""
        SELECT * FROM pick_outcomes
        WHERE outcome = 'TRAILING'
        ORDER BY pick_date ASC
        """)


def update_pick_outcome(
    pick_id: int,
    outcome: str,
    outcome_price: float,
    outcome_date,
    pnl_pct: float,
    days_to_resolve: int,
    max_price: float = None,
    min_price: float = None,
):
    """Resolve a pick outcome (HIT_T1, HIT_T2, MISS, EXPIRED)."""
    _exec(
        """
        UPDATE pick_outcomes SET
            outcome = :outcome,
            outcome_price = :outcome_price,
            outcome_date = :outcome_date,
            pnl_pct = :pnl_pct,
            days_to_resolve = :days_to_resolve,
            max_price = COALESCE(:max_price, max_price),
            min_price = COALESCE(:min_price, min_price),
            updated_at = NOW()
        WHERE id = :pick_id
        """,
        {
            "pick_id": pick_id,
            "outcome": outcome,
            "outcome_price": outcome_price,
            "outcome_date": outcome_date,
            "pnl_pct": pnl_pct,
            "days_to_resolve": days_to_resolve,
            "max_price": max_price,
            "min_price": min_price,
        },
    )


def update_pick_trailing(
    pick_id: int, max_price: float, min_price: float, pnl_pct: float
):
    """Update max/min prices and unrealized P&L for a trailing pick."""
    _exec(
        """
        UPDATE pick_outcomes SET
            max_price = :max_price,
            min_price = :min_price,
            pnl_pct = :pnl_pct,
            updated_at = NOW()
        WHERE id = :pick_id
        """,
        {
            "pick_id": pick_id,
            "max_price": max_price,
            "min_price": min_price,
            "pnl_pct": pnl_pct,
        },
    )


def get_pick_outcome_summary(user_id: int) -> dict:
    """Return aggregated performance stats for a user's picks."""
    rows = _query(
        """
        SELECT
            COUNT(*) AS total,
            COUNT(*) FILTER (WHERE outcome IN ('HIT_T1', 'HIT_T2')) AS hits,
            COUNT(*) FILTER (WHERE outcome = 'MISS') AS misses,
            COUNT(*) FILTER (WHERE outcome = 'EXPIRED') AS expired,
            COUNT(*) FILTER (WHERE outcome = 'TRAILING') AS trailing,
            COALESCE(AVG(pnl_pct) FILTER (WHERE outcome != 'TRAILING'), 0) AS avg_pnl,
            COALESCE(AVG(days_to_resolve) FILTER (WHERE outcome != 'TRAILING'), 0) AS avg_days,
            COALESCE(MAX(pnl_pct), 0) AS best_pnl,
            COALESCE(MIN(pnl_pct) FILTER (WHERE outcome != 'TRAILING'), 0) AS worst_pnl
        FROM pick_outcomes
        WHERE user_id = :user_id
        """,
        {"user_id": user_id},
    )
    if rows:
        r = rows[0]
        total_resolved = r.get("hits", 0) + r.get("misses", 0) + r.get("expired", 0)
        hit_rate = (
            (r.get("hits", 0) / total_resolved * 100) if total_resolved > 0 else 0
        )
        return {
            "total": r.get("total", 0),
            "hits": r.get("hits", 0),
            "misses": r.get("misses", 0),
            "expired": r.get("expired", 0),
            "trailing": r.get("trailing", 0),
            "hit_rate": round(hit_rate, 1),
            "avg_pnl": round(r.get("avg_pnl", 0), 2),
            "avg_days": round(r.get("avg_days", 0), 1),
            "best_pnl": round(r.get("best_pnl", 0), 2),
            "worst_pnl": round(r.get("worst_pnl", 0), 2),
        }
    return {
        "total": 0,
        "hits": 0,
        "misses": 0,
        "expired": 0,
        "trailing": 0,
        "hit_rate": 0,
        "avg_pnl": 0,
        "avg_days": 0,
        "best_pnl": 0,
        "worst_pnl": 0,
    }


def get_user_id_by_username(username: str) -> Optional[int]:
    """Resolve a username to its user_id. Returns None if not found."""
    rows = _query(
        "SELECT user_id FROM app_users WHERE username = :username LIMIT 1",
        {"username": username},
    )
    return rows[0]["user_id"] if rows else None


def init_db():
    if _can_use_neon():
        # Postgres / Neon Path
        _ensure_app_users_neon()
        _ensure_user_broker_connections_neon()
        _ensure_fortress_orders_neon()
        _ensure_pick_outcomes_neon()
        _ensure_scan_history_table_neon()
        _ensure_scan_history_details_neon()
        _ensure_ticker_metadata_neon()
        _ensure_ohlcv_cache_neon()
        _ensure_reit_cache_neon()
        _ensure_options_chain_cache_neon()
        _ensure_mf_scheme_catalog_neon()
        _ensure_bhavcopy_eod_neon()
        _ensure_bhavcopy_fetch_log_neon()
        _ensure_app_settings_neon()

        try:
            _exec("ALTER TABLE app_users ADD COLUMN IF NOT EXISTS password_hash TEXT")
        except Exception:
            pass
        try:
            _exec(
                "ALTER TABLE user_broker_connections ADD COLUMN IF NOT EXISTS broker_client_id TEXT"
            )
        except Exception:
            pass

        try:
            _ensure_mf_scheme_batches_neon()
        except Exception as e:
            logger.warning("Failed to create mf_scheme_batches table: %s", e)

        try:
            _ensure_mf_nav_cache_neon()
        except Exception:
            pass

        _exec("""
            CREATE TABLE IF NOT EXISTS mf_scan_results (
                id          BIGSERIAL PRIMARY KEY,
                scheme_code TEXT NOT NULL,
                scheme_name TEXT,
                scan_date   DATE NOT NULL DEFAULT CURRENT_DATE,
                result_json JSONB,
                updated_at  TIMESTAMPTZ DEFAULT NOW(),
                UNIQUE (scheme_code, scan_date)
            )
        """)

        _exec("""
            CREATE TABLE IF NOT EXISTS scans (
                scan_id BIGSERIAL PRIMARY KEY,
                timestamp TIMESTAMPTZ NOT NULL,
                universe TEXT,
                scan_type TEXT,
                status TEXT
            )
        """)

        _exec("""
            CREATE TABLE IF NOT EXISTS scan_entries (
                id BIGSERIAL PRIMARY KEY,
                scan_id BIGINT,
                symbol TEXT,
                scheme_code TEXT,
                category TEXT,
                score NUMERIC,
                price NUMERIC,
                integrity_label TEXT,
                drift_status TEXT,
                drift_message TEXT,
                UNIQUE (scan_id, symbol, scheme_code)
            )
        """)

        _exec("""
            CREATE TABLE IF NOT EXISTS fund_metrics (
                id BIGSERIAL PRIMARY KEY,
                scan_id BIGINT,
                symbol TEXT,
                alpha NUMERIC, beta NUMERIC, te NUMERIC, sortino NUMERIC,
                max_dd NUMERIC, win_rate NUMERIC, upside NUMERIC, downside NUMERIC, cagr NUMERIC
            )
        """)

        _exec("""
            CREATE TABLE IF NOT EXISTS alerts (
                id BIGSERIAL PRIMARY KEY,
                scan_id BIGINT,
                symbol TEXT,
                alert_type TEXT,
                severity TEXT,
                message TEXT,
                timestamp TIMESTAMPTZ
            )
        """)

        _exec("""
            CREATE TABLE IF NOT EXISTS audit_logs (
                timestamp TIMESTAMPTZ,
                action TEXT,
                universe TEXT,
                details TEXT
            )
        """)

        _exec("""
            CREATE TABLE IF NOT EXISTS algo_trade_log (
                id BIGSERIAL PRIMARY KEY,
                timestamp TIMESTAMPTZ NOT NULL,
                strategy_name TEXT,
                symbol TEXT,
                action TEXT,
                details TEXT,
                status TEXT
            )
        """)
        return

    # SQLite / Fallback Path
    with _sqlite_connection() as conn:
        c = conn.cursor()

        # Identity & Auth
        c.execute("""CREATE TABLE IF NOT EXISTS app_users (
            user_id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            full_name TEXT, email TEXT, phone TEXT, password_hash TEXT,
            account_status TEXT DEFAULT 'Active',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            last_login_at TEXT
        )""")

        c.execute("""CREATE TABLE IF NOT EXISTS user_broker_connections (
            connection_id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            broker_name TEXT NOT NULL,
            broker_client_id TEXT,
            access_token_encrypted TEXT,
            refresh_token_encrypted TEXT,
            expires_at TEXT,
            connected_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            is_active INTEGER DEFAULT 1,
            metadata_json TEXT,
            UNIQUE (user_id, broker_name)
        )""")

        # Scans & Tracking
        c.execute("""CREATE TABLE IF NOT EXISTS scans (
            scan_id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            universe TEXT, scan_type TEXT, status TEXT
        )""")

        c.execute("""CREATE TABLE IF NOT EXISTS scan_entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scan_id INTEGER,
            symbol TEXT, scheme_code TEXT, category TEXT,
            score REAL, price REAL,
            integrity_label TEXT, drift_status TEXT, drift_message TEXT,
            UNIQUE (scan_id, symbol, scheme_code)
        )""")

        c.execute("""CREATE TABLE IF NOT EXISTS mf_scan_results (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            scheme_code TEXT NOT NULL,
            scheme_name TEXT,
            scan_date   TEXT NOT NULL DEFAULT CURRENT_DATE,
            result_json TEXT,
            updated_at  TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (scheme_code, scan_date)
        )""")

        c.execute("""CREATE TABLE IF NOT EXISTS algo_trade_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            strategy_name TEXT, symbol TEXT, action TEXT,
            details TEXT, status TEXT
        )""")

        c.execute("""CREATE TABLE IF NOT EXISTS audit_logs (
            timestamp TEXT, action TEXT, universe TEXT, details TEXT
        )""")

        c.execute("""CREATE TABLE IF NOT EXISTS scan_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scan_timestamp TEXT,
            symbol TEXT,
            conviction_score REAL,
            regime TEXT,
            sub_scores TEXT,
            raw_data TEXT
        )""")

        c.execute(
            "CREATE INDEX IF NOT EXISTS idx_scan_history_timestamp ON scan_history(scan_timestamp)"
        )
        c.execute(
            "CREATE INDEX IF NOT EXISTS idx_scan_history_symbol ON scan_history(symbol)"
        )

        # Migrations for existing DBs
        try:
            c.execute("ALTER TABLE app_users ADD COLUMN password_hash TEXT")
        except Exception:
            pass
        try:
            c.execute(
                "ALTER TABLE user_broker_connections ADD COLUMN broker_client_id TEXT"
            )
        except Exception:
            pass

        conn.commit()


def ensure_users_table() -> None:
    """Create feature-flagged `users` table if it does not already exist."""
    if _can_use_neon():
        _exec("""
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGSERIAL PRIMARY KEY,
                username TEXT NOT NULL UNIQUE,
                email TEXT NOT NULL UNIQUE,
                full_name TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                last_login TIMESTAMPTZ,
                is_active BOOLEAN NOT NULL DEFAULT TRUE
            )
            """)
        _exec(
            "CREATE INDEX IF NOT EXISTS idx_users_created_at ON users (created_at DESC)"
        )
        _exec("CREATE INDEX IF NOT EXISTS idx_users_is_active ON users (is_active)")
        return

    with _sqlite_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                email TEXT NOT NULL UNIQUE,
                full_name TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                last_login TEXT,
                is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1))
            )
            """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_users_created_at ON users (created_at DESC)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_users_is_active ON users (is_active)"
        )
        conn.commit()


def seed_dummy_users() -> int:
    """Seed five fixed dummy users into `app_users` table. Returns number of new rows inserted."""
    from utils.security import hash_password

    if _can_use_neon():
        _ensure_app_users_neon()
    password_hash = hash_password("password123")
    dummy_users = [
        {
            "username": "rahul",
            "email": "rahul.sharma@email.com",
            "full_name": "Rahul Sharma",
        },
        {
            "username": "priya",
            "email": "priya.patel@email.com",
            "full_name": "Priya Patel",
        },
        {
            "username": "amit",
            "email": "amit.kumar@email.com",
            "full_name": "Amit Kumar",
        },
        {
            "username": "sneha",
            "email": "sneha.gupta@email.com",
            "full_name": "Sneha Gupta",
        },
        {
            "username": "vikram",
            "email": "vikram.singh@email.com",
            "full_name": "Vikram Singh",
        },
    ]

    inserted = 0
    if _can_use_neon():
        for user in dummy_users:
            before = _query(
                "SELECT user_id FROM app_users WHERE username = :username OR email = :email LIMIT 1",
                {"username": user["username"], "email": user["email"]},
            )
            if before:
                continue
            _exec(
                """
                INSERT INTO app_users (username, email, full_name, password_hash)
                VALUES (:username, :email, :full_name, :password_hash)
                ON CONFLICT (username) DO NOTHING
                """,
                {**user, "password_hash": password_hash},
            )
            inserted += 1
        return inserted

    with _sqlite_connection() as conn:
        for user in dummy_users:
            row = conn.execute(
                "SELECT user_id FROM app_users WHERE username = :username OR email = :email LIMIT 1",
                {"username": user["username"], "email": user["email"]},
            ).fetchone()
            if row:
                continue
            conn.execute(
                """
                INSERT INTO app_users (username, email, full_name, password_hash)
                VALUES (:username, :email, :full_name, :password_hash)
                """,
                {**user, "password_hash": password_hash},
            )
            inserted += 1
        conn.commit()
    return inserted


def _serialize_json(value: Optional[Dict[str, Any]]) -> str:
    return json.dumps(value or {})


def _deserialize_json(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return json.loads(value)
        except Exception:
            return {}
    return {}


def upsert_app_user(
    username: str,
    full_name: str = "",
    email: str = "",
    phone: str = "",
    account_status: str = "Active",
    password: Optional[str] = None,
):
    from utils.security import hash_password

    if _can_use_neon():
        _ensure_app_users_neon()
    else:
        with _sqlite_connection() as conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS app_users (
                    user_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL UNIQUE,
                    full_name TEXT,
                    email TEXT,
                    phone TEXT,
                    password_hash TEXT,
                    account_status TEXT DEFAULT 'Active',
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    last_login_at TEXT
                )""")

    payload = {
        "username": username.strip(),
        "full_name": full_name,
        "email": email,
        "phone": phone,
        "account_status": account_status,
        "password_hash": hash_password(password) if password else None,
    }

    if _can_use_neon():
        password_sql = ", password_hash = :password_hash" if password else ""
        _exec(
            f"""
            INSERT INTO app_users (username, full_name, email, phone, account_status, password_hash)
            VALUES (:username, :full_name, :email, :phone, :account_status, :password_hash)
            ON CONFLICT (username) DO UPDATE SET
                full_name = EXCLUDED.full_name,
                email = EXCLUDED.email,
                phone = EXCLUDED.phone,
                account_status = EXCLUDED.account_status
                {password_sql}
            """,
            payload,
        )
        return

    with _sqlite_connection() as conn:
        password_sql = ", password_hash = :password_hash" if password else ""
        conn.execute(
            f"""
            INSERT INTO app_users (username, full_name, email, phone, account_status, password_hash)
            VALUES (:username, :full_name, :email, :phone, :account_status, :password_hash)
            ON CONFLICT (username) DO UPDATE SET
                full_name = excluded.full_name,
                email = excluded.email,
                phone = excluded.phone,
                account_status = excluded.account_status
                {password_sql}
            """,
            payload,
        )


def get_app_user(username: str) -> Dict[str, Any]:
    df = _read_df(
        "SELECT * FROM app_users WHERE username = :username LIMIT 1",
        {"username": username.strip()},
        ttl="30s",
    )
    if df.empty:
        return {}
    return df.iloc[0].to_dict()


def record_user_login(username: str):
    upsert_app_user(username=username)
    if _can_use_neon():
        _exec(
            "UPDATE app_users SET last_login_at = NOW() WHERE username = :username",
            {"username": username.strip()},
        )
        return

    with _sqlite_connection() as conn:
        conn.execute(
            "UPDATE app_users SET last_login_at = CURRENT_TIMESTAMP WHERE username = :username",
            {"username": username.strip()},
        )


def _get_user_id(username: str) -> Optional[int]:
    df = _read_df(
        "SELECT user_id FROM app_users WHERE username = :username LIMIT 1",
        {"username": username.strip()},
        ttl="30s",
    )
    if df.empty:
        return None
    return int(df.iloc[0]["user_id"])


def verify_user_credentials(username: str, password: str) -> bool:
    """Verify credentials with a single DB round-trip."""
    from utils.security import hash_password

    df = _read_df(
        "SELECT password_hash FROM app_users WHERE username = :username LIMIT 1",
        {"username": username.strip()},
        ttl="5s",
    )
    if df.empty:
        return False
    stored_hash = df.iloc[0].get("password_hash")
    if not stored_hash:
        return False
    return stored_hash == hash_password(password)


def delete_app_user(username: str) -> None:
    """Permanently deletes a user account and all associated data (broker connections, orders)."""
    user_id = _get_user_id(username)
    if user_id is None:
        return

    if _can_use_neon():
        _exec(
            "DELETE FROM user_broker_connections WHERE user_id = :uid", {"uid": user_id}
        )
        _exec("DELETE FROM fortress_orders WHERE user_id = :uid", {"uid": user_id})
        _exec("DELETE FROM app_users WHERE user_id = :uid", {"uid": user_id})
        return

    with _sqlite_connection() as conn:
        conn.execute(
            "DELETE FROM user_broker_connections WHERE user_id = :uid", {"uid": user_id}
        )
        conn.execute(
            "DELETE FROM fortress_orders WHERE user_id = :uid", {"uid": user_id}
        )
        conn.execute("DELETE FROM app_users WHERE user_id = :uid", {"uid": user_id})
        conn.commit()


def list_user_broker_connections(username: str) -> pd.DataFrame:
    if _can_use_neon():
        _ensure_user_broker_connections_neon()
    else:
        with _sqlite_connection() as conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS user_broker_connections (
                    connection_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    broker_name TEXT NOT NULL,
                    broker_client_id TEXT,
                    access_token_encrypted TEXT,
                    refresh_token_encrypted TEXT,
                    expires_at TEXT,
                    connected_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    is_active INTEGER DEFAULT 1,
                    metadata_json TEXT,
                    UNIQUE (user_id, broker_name)
                )""")
    user_id = _get_user_id(username)
    if user_id is None:
        return pd.DataFrame()

    df = _read_df(
        """
        SELECT connection_id, broker_name, expires_at, connected_at, updated_at, is_active, metadata_json
        FROM user_broker_connections
        WHERE user_id = :user_id
        ORDER BY connected_at DESC
        """,
        {"user_id": user_id},
        ttl="30s",
    )
    if df.empty:
        return df
    if "metadata_json" in df.columns:
        df["metadata_json"] = df["metadata_json"].apply(_deserialize_json)
    return df


def delete_user_broker_connection(username: str, broker_name: str) -> None:
    user_id = _get_user_id(username)
    if user_id is None:
        return
    _exec(
        "DELETE FROM user_broker_connections WHERE user_id = :user_id AND broker_name = :broker_name",
        {"user_id": user_id, "broker_name": broker_name},
    )


def upsert_user_broker_connection(
    username: str,
    broker_name: str,
    access_token: str,
    broker_client_id: str = "",
    expires_at: Optional[str] = None,
    refresh_token: str = "",
    is_active: bool = True,
    metadata: Optional[Dict[str, Any]] = None,
):
    upsert_app_user(username=username)
    user_id = _get_user_id(username)
    if user_id is None:
        return

    payload = {
        "user_id": user_id,
        "broker_name": broker_name,
        "broker_client_id": broker_client_id,
        "access_token_encrypted": _encrypt_token(access_token),
        "refresh_token_encrypted": _encrypt_token(refresh_token),
        "expires_at": expires_at,
        "is_active": is_active,
        "metadata_json": _serialize_json(metadata),
    }

    if _can_use_neon():
        _exec(
            """
            INSERT INTO user_broker_connections (
                user_id, broker_name, broker_client_id, access_token_encrypted, refresh_token_encrypted,
                expires_at, connected_at, updated_at, is_active, metadata_json
            )
            VALUES (
                :user_id, :broker_name, :broker_client_id, :access_token_encrypted, :refresh_token_encrypted,
                :expires_at, NOW(), NOW(), :is_active, CAST(:metadata_json AS JSONB)
            )
            ON CONFLICT (user_id, broker_name) DO UPDATE SET
                broker_client_id = EXCLUDED.broker_client_id,
                access_token_encrypted = EXCLUDED.access_token_encrypted,
                refresh_token_encrypted = EXCLUDED.refresh_token_encrypted,
                expires_at = EXCLUDED.expires_at,
                updated_at = NOW(),
                is_active = EXCLUDED.is_active,
                metadata_json = EXCLUDED.metadata_json
            """,
            payload,
        )
        return

    with _sqlite_connection() as conn:
        conn.execute(
            """
            INSERT INTO user_broker_connections (
                user_id, broker_name, broker_client_id, access_token_encrypted, refresh_token_encrypted,
                expires_at, is_active, metadata_json
            )
            VALUES (:user_id, :broker_name, :broker_client_id, :access_token_encrypted, :refresh_token_encrypted, :expires_at, :is_active, :metadata_json)
            ON CONFLICT (user_id, broker_name) DO UPDATE SET
                broker_client_id = excluded.broker_client_id,
                access_token_encrypted = excluded.access_token_encrypted,
                refresh_token_encrypted = excluded.refresh_token_encrypted,
                expires_at = excluded.expires_at,
                updated_at = CURRENT_TIMESTAMP,
                is_active = excluded.is_active,
                metadata_json = excluded.metadata_json
            """,
            payload,
        )


def deactivate_user_broker_connection(username: str, broker_name: str):
    user_id = _get_user_id(username)
    if user_id is None:
        return
    params = {"user_id": user_id, "broker_name": broker_name}
    if _can_use_neon():
        _exec(
            """
            UPDATE user_broker_connections
            SET is_active = FALSE, updated_at = NOW()
            WHERE user_id = :user_id AND broker_name = :broker_name
            """,
            params,
        )
        return
    with _sqlite_connection() as conn:
        conn.execute(
            """
            UPDATE user_broker_connections
            SET is_active = 0, updated_at = CURRENT_TIMESTAMP
            WHERE user_id = :user_id AND broker_name = :broker_name
            """,
            params,
        )


def get_broker_access_token(username: str, broker_name: str) -> str:
    user_id = _get_user_id(username)
    if user_id is None:
        return ""
    df = _read_df(
        """
        SELECT access_token_encrypted
        FROM user_broker_connections
        WHERE user_id = :user_id AND broker_name = :broker_name AND is_active = :is_active
        LIMIT 1
        """,
        {
            "user_id": user_id,
            "broker_name": broker_name,
            "is_active": True if _can_use_neon() else 1,
        },
        ttl="30s",
    )
    if df.empty:
        return ""
    return _decrypt_token(str(df.iloc[0]["access_token_encrypted"]))


def create_fortress_order(
    username: str,
    symbol: str,
    order_type: str,
    quantity: float,
    price: Optional[float],
    status: str,
    broker_name: str,
    stock_name: str = "",
    broker_order_id: str = "",
    notes: str = "",
):
    if _can_use_neon():
        _ensure_fortress_orders_neon()
    else:
        with _sqlite_connection() as conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS fortress_orders (
                    order_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    symbol TEXT NOT NULL,
                    stock_name TEXT,
                    order_type TEXT NOT NULL,
                    quantity REAL NOT NULL,
                    price REAL,
                    status TEXT DEFAULT 'Pending',
                    broker_name TEXT,
                    broker_order_id TEXT,
                    notes TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                )""")
    upsert_app_user(username=username)
    user_id = _get_user_id(username)
    if user_id is None:
        return
    payload = {
        "user_id": user_id,
        "symbol": symbol,
        "stock_name": stock_name or symbol,
        "order_type": order_type,
        "quantity": quantity,
        "price": price,
        "status": status,
        "broker_name": broker_name,
        "broker_order_id": broker_order_id,
        "notes": notes,
    }
    if _can_use_neon():
        _exec(
            """
            INSERT INTO fortress_orders (
                user_id, symbol, stock_name, order_type, quantity, price, status,
                broker_name, broker_order_id, notes, created_at, updated_at
            )
            VALUES (
                :user_id, :symbol, :stock_name, :order_type, :quantity, :price, :status,
                :broker_name, :broker_order_id, :notes, NOW(), NOW()
            )
            """,
            payload,
        )
        return
    with _sqlite_connection() as conn:
        conn.execute(
            """
            INSERT INTO fortress_orders (
                user_id, symbol, stock_name, order_type, quantity, price, status,
                broker_name, broker_order_id, notes
            )
            VALUES (
                :user_id, :symbol, :stock_name, :order_type, :quantity, :price, :status,
                :broker_name, :broker_order_id, :notes
            )
            """,
            payload,
        )


def fetch_fortress_orders(
    username: str,
    status: Optional[str] = None,
    broker_name: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
) -> pd.DataFrame:
    if _can_use_neon():
        _ensure_fortress_orders_neon()
    else:
        with _sqlite_connection() as conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS fortress_orders (
                    order_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    symbol TEXT NOT NULL,
                    stock_name TEXT,
                    order_type TEXT NOT NULL,
                    quantity REAL NOT NULL,
                    price REAL,
                    status TEXT DEFAULT 'Pending',
                    broker_name TEXT,
                    broker_order_id TEXT,
                    notes TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                )""")
    user_id = _get_user_id(username)
    if user_id is None:
        return pd.DataFrame()

    conditions = ["user_id = :user_id"]
    params: Dict[str, Any] = {"user_id": user_id}
    if status and status != "All":
        conditions.append("status = :status")
        params["status"] = status
    if broker_name and broker_name != "All":
        conditions.append("broker_name = :broker_name")
        params["broker_name"] = broker_name
    if date_from:
        conditions.append("created_at >= :date_from")
        params["date_from"] = date_from
    if date_to:
        conditions.append("created_at <= :date_to")
        params["date_to"] = date_to

    query = f"""
    SELECT order_id, symbol, stock_name, order_type, quantity, price, status, broker_name, broker_order_id, notes, created_at, updated_at
    FROM fortress_orders
    WHERE {' AND '.join(conditions)}
    ORDER BY created_at DESC
    """
    return _read_df(query, params, ttl="30s")


def _infer_sql_type(series):
    dtype = series.dtype
    if pd.api.types.is_float_dtype(dtype):
        return "REAL"
    if pd.api.types.is_integer_dtype(dtype):
        return "INTEGER"
    if pd.api.types.is_bool_dtype(dtype):
        return "BOOLEAN"
    if pd.api.types.is_datetime64_any_dtype(dtype):
        return "TIMESTAMP"
    if str(series.name).lower() == "sub_scores":
        return "JSONB"
    return "TEXT"


def log_scan_results(df, table_name="scan_results"):
    if df.empty:
        return

    # Bulk Schema Check & ALTER
    # Ensure all columns in df exist in the DB table before insertion
    try:
        if _can_use_neon():
            # Postgres / Neon Logic
            existing_cols_df = _read_df_uncached(
                "SELECT column_name FROM information_schema.columns WHERE table_name = :table_name",
                {"table_name": table_name},
            )
            # Only proceed if table exists (has columns)
            if not existing_cols_df.empty:
                existing_cols = set(
                    existing_cols_df["column_name"].str.lower().tolist()
                )
                # Identify missing columns
                missing_cols = [
                    col for col in df.columns if col.lower() not in existing_cols
                ]

                if missing_cols:
                    alter_stmts = []
                    for col in missing_cols:
                        # Map pandas types to SQL types
                        sql_type = (
                            "NUMERIC"
                            if pd.api.types.is_numeric_dtype(df[col])
                            else "TEXT"
                        )
                        # Quote column name to handle special chars/case
                        alter_stmts.append(f'ADD COLUMN "{col}" {sql_type}')

                    if alter_stmts:
                        # Postgres supports multiple ADD COLUMN in one statement
                        full_sql = f'ALTER TABLE {table_name} {", ".join(alter_stmts)}'
                        _exec(full_sql)

        else:
            # SQLite Logic
            with _sqlite_connection() as conn:
                # Check if table exists
                res = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                    (table_name,),
                ).fetchone()
                if res:
                    existing_info = conn.execute(
                        f"PRAGMA table_info({table_name})"
                    ).fetchall()
                    existing_cols = {info[1] for info in existing_info}
                    missing_cols = [
                        col for col in df.columns if col not in existing_cols
                    ]

                    if missing_cols:
                        # SQLite requires separate statements for ADD COLUMN (standard compliance)
                        for col in missing_cols:
                            sql_type = (
                                "REAL"
                                if pd.api.types.is_numeric_dtype(df[col])
                                else "TEXT"
                            )
                            conn.execute(
                                f'ALTER TABLE {table_name} ADD COLUMN "{col}" {sql_type}'
                            )
                        conn.commit()
    except Exception as e:
        logger.warning(f"Schema evolution failed for {table_name}: {e}")

    if _can_use_neon() and table_name == "scan_history":
        print(f"Logging {len(df)} rows to {table_name} in Neon")
        try:
            for row in df.to_dict(orient="records"):
                _exec(
                    """
                    INSERT INTO scan_history (scan_timestamp, symbol, conviction_score, regime, sub_scores, raw_data)
                    VALUES (COALESCE(:scan_timestamp, NOW()), :symbol, :conviction_score, :regime, CAST(:sub_scores AS JSONB), CAST(:raw_data AS JSONB))
                    """,
                    {
                        "scan_timestamp": row.get("scan_timestamp"),
                        "symbol": row.get("symbol") or row.get("Symbol"),
                        "conviction_score": row.get("conviction_score")
                        or row.get("Conviction Score")
                        or row.get("Score"),
                        "regime": row.get("regime") or row.get("Regime"),
                        "sub_scores": json.dumps(row.get("sub_scores", {})),
                        "raw_data": json.dumps(row),
                    },
                )
        except Exception as e:
            st.error(f"Neon log failed: {str(e)}")
        return

    if _can_use_neon():
        engine = get_db_engine()
        df.to_sql(table_name, engine, if_exists="append", index=False)
        return

    # SQLite fallback with retries and schema evolution
    max_retries = 3
    for attempt in range(1, max_retries + 1):
        conn = _sqlite_connection()
        try:
            ensure_table_exists(conn, table_name)

            c = conn.cursor()
            c.execute(f"PRAGMA table_info({table_name})")
            existing_cols = {row[1] for row in c.fetchall()}
            missing_cols = [col for col in df.columns if col not in existing_cols]

            if missing_cols:
                for col in missing_cols:
                    try:
                        sql_type = _infer_sql_type(df[col])
                        c.execute(
                            f'ALTER TABLE "{table_name}" ADD COLUMN "{col}" {sql_type}'
                        )
                    except Exception as e:
                        logger.error(f"Failed to add column {col}: {e}")

            df.to_sql(table_name, conn, if_exists="append", index=False, chunksize=1000)
            conn.commit()
            return
        except sqlite3.OperationalError as exc:
            conn.rollback()
            logger.error(
                "SQLite write failed for table '%s' (attempt %s/%s): %s",
                table_name,
                attempt,
                max_retries,
                exc,
            )
            if attempt == max_retries:
                raise
            time.sleep(random.uniform(1.0, 2.0))
        except Exception as exc:
            conn.rollback()
            logger.error("Unexpected error writing to '%s': %s", table_name, exc)
            raise
        finally:
            conn.close()


def ensure_table_exists(conn: sqlite3.Connection, table_name: str):
    table_check = pd.read_sql(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        conn,
        params=[table_name],
    )
    if not table_check.empty:
        return

    if table_name == "scan_history_details":
        conn.execute("""
            CREATE TABLE IF NOT EXISTS scan_history_details (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                scan_id INTEGER,
                symbol TEXT,
                conviction_score REAL,
                regime TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                sub_scores TEXT,
                raw_data TEXT
            )
            """)
        conn.commit()
        return

    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS {table_name} (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            raw_data TEXT
        )
        """)
    conn.commit()


def register_scan(
    timestamp, universe="Mutual Funds", scan_type="MF", status="In Progress"
):
    if _can_use_neon():
        engine = get_db_engine()
        with engine.begin() as conn:
            res = conn.execute(
                text("""
                    INSERT INTO scans (timestamp, universe, scan_type, status)
                    VALUES (:timestamp, :universe, :scan_type, :status)
                    RETURNING scan_id
                    """),
                {
                    "timestamp": timestamp,
                    "universe": universe,
                    "scan_type": scan_type,
                    "status": status,
                },
            )
            return int(res.scalar_one())

    with _sqlite_connection() as conn:
        cur = conn.execute(
            "INSERT INTO scans (timestamp, universe, scan_type, status) VALUES (?, ?, ?, ?)",
            (timestamp, universe, scan_type, status),
        )
        return cur.lastrowid


def save_scan_results(scan_id, df, scan_timestamp=None):
    if df.empty:
        return

    # Prepare list of dicts for insertion (common for both backends)
    records = []
    for row in df.to_dict(orient="records"):
        score = (
            row.get("conviction_score")
            or row.get("Conviction Score")
            or row.get("Score")
        )
        price = row.get("price") or row.get("Price")
        regime = row.get("regime") or row.get("Regime")

        # Make sure None is saved if Pandas converts to nan
        if pd.isna(score):
            score = None
        if pd.isna(price):
            price = None
        if pd.isna(regime):
            regime = None

        # Serialize the full row to JSON for raw_data column
        records.append(
            {
                "scan_id": scan_id,
                "scan_timestamp": scan_timestamp
                or row.get("scan_timestamp")
                or datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "symbol": row.get("symbol") or row.get("Symbol") or "UNKNOWN",
                "conviction_score": score,
                "price": price,
                "regime": regime,
                "raw_data": json.dumps(row),
            }
        )

    if _can_use_neon():
        # Neon: Explicit INSERT with properly typed values
        for rec in records:
            _exec(
                "INSERT INTO scan_history_details (scan_id, scan_timestamp, symbol, conviction_score, price, regime, raw_data) "
                "VALUES (:scan_id, :scan_timestamp, :symbol, :conviction_score, :price, :regime, CAST(:raw_data AS JSONB))",
                rec,
            )
        return

    # SQLite: Use to_sql but with the prepared simple DataFrame
    df_to_save = pd.DataFrame(records)
    log_scan_results(df_to_save, table_name="scan_history_details")


def update_scan_status(scan_id, status):
    _exec(
        "UPDATE scans SET status = :status WHERE scan_id = :scan_id",
        {"status": status, "scan_id": scan_id},
    )


def bulk_insert_results(results_df, metrics_df, alerts_df=None):
    if not results_df.empty:
        log_scan_results(results_df, table_name="scan_entries")
    if not metrics_df.empty:
        log_scan_results(metrics_df, table_name="fund_metrics")
    if alerts_df is not None and not alerts_df.empty:
        alerts_df = alerts_df.rename(columns={"type": "alert_type"})
        log_scan_results(alerts_df, table_name="alerts")


def get_cached_benchmark(ticker, start_date=None):
    query = "SELECT date, close, ret FROM benchmark_history WHERE ticker = :ticker"
    params = {"ticker": ticker}
    if start_date:
        query += " AND date >= :start_date"
        params["start_date"] = start_date
    query += " ORDER BY date"
    try:
        df = _read_df(query, params=params)
        if not df.empty:
            df["date"] = pd.to_datetime(df["date"])
            df = df.set_index("date")
        return df
    except Exception:
        return pd.DataFrame()


def save_benchmark_data(ticker, df):
    if df.empty:
        return
    if _can_use_neon():
        return
    rows = []
    for date, row in df.iterrows():
        # Handle NaN returns safely
        ret = row.get("ret", 0.0)
        if pd.isna(ret):
            ret = 0.0
        rows.append((ticker, date.strftime("%Y-%m-%d"), row.get("Close", 0.0), ret))
    with _sqlite_connection() as conn:
        conn.executemany(
            "INSERT OR REPLACE INTO benchmark_history (ticker, date, close, ret) VALUES (?, ?, ?, ?)",
            rows,
        )



def fetch_timestamps(table_name="scan_mf", scan_type=None):
    # 1. Try New Schema (Neon/Postgres or Unified SQLite)
    timestamps = []
    query = "SELECT timestamp FROM scans WHERE status='Completed'"
    params = {}
    if scan_type:
        query += " AND scan_type = :scan_type"
        params["scan_type"] = scan_type
    query += " ORDER BY timestamp DESC"

    try:
        df = _read_df(query, params=params, ttl="5m")
        if not df.empty:
            timestamps = df["timestamp"].tolist()
    except Exception as e:
        logger.warning(f"Error fetching timestamps from scans table: {e}")

    # 2. Legacy fallback from main - supports pre-Neon SQLite data
    # Only if timestamps list is empty or scan_type is legacy-compatible
    if not timestamps:
        try:
            # Attempt to read from legacy scan_mf table
            # We use _read_df to support reading this from Neon (if migrated) or SQLite
            df_legacy = _read_df(
                "SELECT DISTINCT timestamp FROM scan_mf ORDER BY timestamp DESC",
                ttl="5m",
            )
            if not df_legacy.empty:
                legacy = [
                    t for t in df_legacy["timestamp"].tolist() if t not in timestamps
                ]
                timestamps.extend(legacy)
        except Exception as e:
            # Legacy table might not exist
            logger.debug(
                f"Legacy scan_mf fetch failed (expected if fresh install): {e}"
            )

    # 3. Fallback to unified scan history tables used by the migrated app
    if not timestamps:
        fallback_queries = [
            "SELECT DISTINCT scan_timestamp AS timestamp FROM scan_history_details ORDER BY scan_timestamp DESC",
            "SELECT DISTINCT timestamp FROM scan_history ORDER BY timestamp DESC",
        ]
        for fallback_query in fallback_queries:
            try:
                df_fallback = _read_df(fallback_query, ttl="5m")
                if not df_fallback.empty and "timestamp" in df_fallback.columns:
                    fallback = [
                        t for t in df_fallback["timestamp"].tolist() if t not in timestamps
                    ]
                    timestamps.extend(fallback)
            except Exception as e:
                logger.debug(f"History timestamp fallback failed: {e}")

    # Ensure list is sorted
    timestamps.sort(reverse=True)
    return timestamps



def fetch_history_data(table_name, timestamp, scan_type=None):
    # 1. Try New Schema via scans table
    scan_info = _read_df(
        "SELECT scan_id, scan_type FROM scans WHERE timestamp = :timestamp",
        {"timestamp": timestamp},
        ttl="5m",
    )

    if not scan_info.empty:
        # int(...): scan_info.iloc[0]["scan_id"] comes back as numpy.int64
        # (pandas' integer dtype), which sqlite3's parameter binding does
        # not recognize as a native type. Passed straight through to
        # pd.read_sql_query on a raw sqlite3 connection, it silently binds
        # to a value that matches no rows — no exception, just an
        # always-empty result — instead of the intended scan_id lookup, so
        # the Scan History page could see a valid timestamp but always show
        # zero rows of data for it.
        scan_id = int(scan_info.iloc[0]["scan_id"])
        db_scan_type = scan_info.iloc[0].get("scan_type")

        if db_scan_type in ["STOCK", "OPTIONS", "COMMODITY"]:
            df = _read_df(
                "SELECT raw_data FROM scan_history_details WHERE scan_id = :scan_id",
                {"scan_id": scan_id},
                ttl="5m",
            )
            if "raw_data" in df.columns and not df.empty:
                return pd.json_normalize(
                    df["raw_data"].apply(
                        lambda x: x if isinstance(x, dict) else json.loads(x)
                    )
                )
            return df

        query = """
        SELECT
            r.symbol as Symbol,
            r.scheme_code as "Scheme Code",
            r.category as Category,
            r.score as Score,
            r.price as Price,
            r.integrity_label as Integrity,
            r.drift_status as "Drift Status",
            r.drift_message as "Drift Message",
            m.alpha as "Alpha (True)",
            m.beta as Beta,
            m.te as "Tracking Error",
            m.sortino as Sortino,
            m.max_dd as "Max Drawdown",
            m.win_rate as "Win Rate",
            m.upside as "Upside Cap",
            m.downside as "Downside Cap",
            m.cagr as cagr
        FROM scan_entries r
        LEFT JOIN fund_metrics m ON r.scan_id = m.scan_id AND r.symbol = m.symbol
        WHERE r.scan_id = :scan_id
        """
        df = _read_df(query, {"scan_id": scan_id}, ttl="5m")
        if not df.empty and "Score" in df.columns:
            df["Fortress Score"] = df["Score"]
        return df

    # 1b. Unified scan history fallback for migrated dashboard scans
    try:
        df_scan_history = _read_df(
            "SELECT * FROM scan_history_details WHERE scan_timestamp = :timestamp",
            {"timestamp": timestamp},
            ttl="5m",
        )
        if not df_scan_history.empty:
            if "raw_data" in df_scan_history.columns:
                return pd.json_normalize(
                    df_scan_history["raw_data"].apply(
                        lambda x: x if isinstance(x, dict) else json.loads(x)
                    )
                )
            return df_scan_history
    except Exception as e:
        logger.debug(f"Unified scan history fallback failed: {e}")

    # 2. Legacy fallback from main - supports pre-Neon SQLite data
    # If not found in 'scans', check 'scan_mf' directly
    try:
        df = _read_df(
            "SELECT * FROM scan_mf WHERE timestamp = :timestamp",
            {"timestamp": timestamp},
            ttl="5m",
        )
        return df
    except Exception as e:
        logger.debug(f"Legacy fetch_history_data failed: {e}")
        return pd.DataFrame()



def fetch_symbol_history(table_name, symbol):
    # Unified history fetch (New Schema)
    query = """
    SELECT s.timestamp, r.score as Score, r.price as Price, m.alpha as "Alpha (True)", m.beta as Beta, m.te as "Tracking Error"
    FROM scan_entries r
    JOIN scans s ON r.scan_id = s.scan_id
    LEFT JOIN fund_metrics m ON r.scan_id = m.scan_id AND r.symbol = m.symbol
    WHERE r.symbol = :symbol
    ORDER BY s.timestamp
    """
    try:
        df_new = _read_df(query, {"symbol": symbol}, ttl="5m")
    except Exception:
        df_new = pd.DataFrame()

    # Legacy Schema
    df_old = pd.DataFrame()
    try:
        # Columns might differ in legacy, selecting key ones
        df_old = _read_df(
            "SELECT timestamp, Score, Price, `Alpha (True)`, Beta, `Tracking Error` FROM scan_mf WHERE Symbol = :symbol",
            {"symbol": symbol},
            ttl="5m",
        )
    except Exception:
        pass

    if not df_new.empty and not df_old.empty:
        existing_ts = set(df_new["timestamp"])
        df_old = df_old[~df_old["timestamp"].isin(existing_ts)]
        return pd.concat([df_old, df_new]).sort_values("timestamp")
    elif not df_new.empty:
        return df_new
    elif not df_old.empty:
        return df_old

    return pd.DataFrame()


def log_audit(action, universe="Global", details=""):
    _exec(
        "INSERT INTO audit_logs (timestamp, action, universe, details) VALUES (:timestamp, :action, :universe, :details)",
        {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "action": action,
            "universe": universe,
            "details": details,
        },
    )


def log_algo_trade(strategy, symbol, action, details, status="Active"):
    _exec(
        """
        INSERT INTO algo_trade_log (timestamp, strategy_name, symbol, action, details, status)
        VALUES (:timestamp, :strategy, :symbol, :action, :details, :status)
        """,
        {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "strategy": strategy,
            "symbol": symbol,
            "action": action,
            "details": details,
            "status": status,
        },
    )


def fetch_active_trades():
    return _read_df("SELECT * FROM algo_trade_log WHERE status='Active'", ttl="5m")


def close_all_trades():
    _exec("UPDATE algo_trade_log SET status='Closed' WHERE status='Active'")


# ─────────────────────────────────────────────
#  Monthly MF Scan Persistence
# ─────────────────────────────────────────────


def _ensure_mf_scan_results_sqlite(conn) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS mf_scan_results (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            scheme_code TEXT NOT NULL,
            scheme_name TEXT,
            scan_date   TEXT NOT NULL DEFAULT CURRENT_DATE,
            result_json TEXT,
            updated_at  TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (scheme_code, scan_date)
        )
    """)


def fetch_mf_cached_results(max_age_days: int = 31) -> pd.DataFrame:
    """Return the latest monthly MF scan if one was persisted within
    `max_age_days`. Empty DataFrame if stale/missing, which callers should
    treat as "run a fresh scan".

    This is the DB-backed "run the MF scan once a month" mechanism —
    `/api/mf-analysis` checks this first and only runs the expensive full
    discover-and-score pass (`run_full_mf_scan()`, which discovers and scores
    essentially the whole direct-growth fund universe) when nothing fresh
    enough is on file.

    Works on both backends via `_read_df` (previously hard-gated to
    `if not _can_use_neon(): return pd.DataFrame()`, so on SQLite — local
    dev's default — this monthly cache was a complete no-op despite the
    schema and the write side (`upsert_mf_scan_results`) already existing;
    every scan re-ran the full discovery+scoring pass regardless of how
    recently it had last run).

    Each returned record is stamped with `last_updated` (the persisted
    `scan_date`) so the UI can show how stale the currently-displayed scan
    is, and a manual "Trigger Job" full refresh can be compared against it.
    """
    try:
        if _can_use_neon():
            df = _read_df(
                "SELECT scheme_code, scheme_name, scan_date, result_json "
                "FROM mf_scan_results "
                "WHERE scan_date >= CURRENT_DATE - INTERVAL :age "
                "ORDER BY scan_date DESC, scheme_code",
                {"age": f"{int(max_age_days)} days"},
            )
        else:
            with _sqlite_connection() as conn:
                _ensure_mf_scan_results_sqlite(conn)
                df = pd.read_sql_query(
                    "SELECT scheme_code, scheme_name, scan_date, result_json "
                    "FROM mf_scan_results "
                    "WHERE scan_date >= date('now', :cutoff) "
                    "ORDER BY scan_date DESC, scheme_code",
                    conn,
                    params={"cutoff": f"-{int(max_age_days)} days"},
                )
        if df.empty:
            return pd.DataFrame()
        rows = []
        for _, row in df.iterrows():
            rj = row["result_json"]
            if isinstance(rj, str):
                rj = json.loads(rj)
            if isinstance(rj, dict):
                rj.setdefault("last_updated", str(row["scan_date"]))
                rows.append(rj)
        return pd.DataFrame(rows) if rows else pd.DataFrame()
    except Exception as e:
        logger.error("fetch_mf_cached_results error: %s", e)
        return pd.DataFrame()


def fetch_top_mf_picks(max_age_days: int = 31) -> pd.DataFrame:
    """Return ONLY the Top 5 strongest schemes partitioned securely by Sub Category using DB engine logic."""
    if not _can_use_neon():
        # SQLite Fallback Window Function (SQLite 3.25+)
        sql = f"""
            SELECT result_json FROM (
                SELECT result_json,
                       ROW_NUMBER() OVER(
                           PARTITION BY json_extract(result_json, '$.Category'), json_extract(result_json, '$."Sub Category"') 
                           ORDER BY CAST(json_extract(result_json, '$."Conviction Score"') AS NUMERIC) DESC
                       ) as rn
                FROM mf_scan_results
                WHERE scan_date >= date('now', '-{max_age_days} days')
            ) sub
            WHERE rn <= 5
        """
        try:
            df = _read_df(sql)
            if df.empty:
                return pd.DataFrame()
            rows = [
                json.loads(r) if isinstance(r, str) else r for r in df["result_json"]
            ]
            return pd.DataFrame(rows)
        except Exception as e:
            logger.error("SQLite top picks failed (maybe old SQLite version): %s", e)
            return pd.DataFrame()

    # Postgres Neon
    try:
        sql = f"""
            SELECT result_json FROM (
                SELECT result_json,
                       ROW_NUMBER() OVER(
                           PARTITION BY result_json->>'Category', result_json->>'Sub Category' 
                           ORDER BY CAST(result_json->>'Conviction Score' AS NUMERIC) DESC
                       ) as rn
                FROM mf_scan_results
                WHERE scan_date >= CURRENT_DATE - INTERVAL '{max_age_days} days'
            ) sub
            WHERE rn <= 5
        """
        df = _read_df(sql)
        if df.empty:
            return pd.DataFrame()
        rows = [json.loads(r) if isinstance(r, str) else r for r in df["result_json"]]
        return pd.DataFrame(rows)
    except Exception as e:
        logger.error("fetch_top_mf_picks error: %s", e)
        return pd.DataFrame()


def upsert_mf_scan_results(df: pd.DataFrame):
    """Persist a full MF scan result DataFrame (one row per scheme, monthly
    UPSERT keyed on scheme_code + today's date) so `fetch_mf_cached_results`
    can serve it back without re-running the full scan.

    Works on both backends (previously Neon-only — see
    `fetch_mf_cached_results`'s docstring for why that made the "once a
    month" scan cache a no-op on local dev)."""
    if df is None or df.empty:
        return

    def _sanitized_records():
        for _, row in df.iterrows():
            record = row.to_dict()
            # Sanitize NaN and Infinity values (invalid in JSON/JSONB)
            sanitized = {}
            for k, v in record.items():
                if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
                    sanitized[k] = None
                else:
                    sanitized[k] = v
            code = str(sanitized.get("Scheme Code") or sanitized.get("scheme_code") or "UNKNOWN")
            name = str(sanitized.get("Scheme") or sanitized.get("scheme_name") or "")
            yield code, name, json.dumps(sanitized, default=str)

    try:
        if _can_use_neon():
            for code, name, payload in _sanitized_records():
                _exec(
                    "INSERT INTO mf_scan_results (scheme_code, scheme_name, scan_date, result_json, updated_at) "
                    "VALUES (:code, :name, CURRENT_DATE, CAST(:payload AS JSONB), NOW()) "
                    "ON CONFLICT (scheme_code, scan_date) DO UPDATE "
                    "SET result_json=EXCLUDED.result_json, scheme_name=EXCLUDED.scheme_name, updated_at=EXCLUDED.updated_at",
                    {"code": code, "name": name, "payload": payload},
                )
        else:
            with _sqlite_connection() as conn:
                _ensure_mf_scan_results_sqlite(conn)
                for code, name, payload in _sanitized_records():
                    conn.execute(
                        "INSERT INTO mf_scan_results (scheme_code, scheme_name, scan_date, result_json, updated_at) "
                        "VALUES (:code, :name, CURRENT_DATE, :payload, CURRENT_TIMESTAMP) "
                        "ON CONFLICT(scheme_code, scan_date) DO UPDATE SET "
                        "result_json = excluded.result_json, "
                        "scheme_name = excluded.scheme_name, "
                        "updated_at = excluded.updated_at",
                        {"code": code, "name": name, "payload": payload},
                    )

        logger.info("upsert_mf_scan_results: saved %d rows", len(df))
    except Exception as e:
        logger.error("upsert_mf_scan_results error: %s", e)


# ─────────────────────────────────────────────
#  MF NAV History Cache  (per scheme, 1-day TTL)
# ─────────────────────────────────────────────


def _ensure_mf_nav_cache_neon():
    _exec("""
        CREATE TABLE IF NOT EXISTS mf_nav_cache (
            scheme_code TEXT PRIMARY KEY,
            nav_json    JSONB,
            updated_at  TIMESTAMPTZ DEFAULT NOW()
        )
    """)


def _ensure_mf_nav_cache_sqlite(conn) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS mf_nav_cache (
            scheme_code TEXT PRIMARY KEY,
            nav_json    TEXT,
            updated_at  TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)


def fetch_mf_nav_cache(scheme_code: str, max_age_hours: int = 20) -> pd.DataFrame:
    """Return cached NAV history DataFrame if fresh, else None.

    Works on both backends. Previously SQLite always returned None here
    (same no-op-on-SQLite bug as `fetch_ohlcv_cache`/the ticker_metadata
    cache), which means a full MF scan on local dev re-downloaded NAV
    history from mfapi.in live for every single scheme on every scan —
    the single biggest reason MF scans are slow, since `run_full_mf_scan`
    with no `limit` discovers essentially the whole direct-growth fund
    universe (well into the hundreds/low thousands of schemes) and none of
    that work was ever actually being cached locally.
    """
    try:
        import io

        if _can_use_neon():
            engine = get_db_engine()
            with engine.connect() as conn:
                row = conn.execute(
                    text("""
                        SELECT nav_json FROM mf_nav_cache
                        WHERE scheme_code = :code
                          AND updated_at >= NOW() - INTERVAL :age
                    """),
                    {"code": str(scheme_code), "age": f"{max_age_hours} hours"},
                ).fetchone()
            if row and row[0]:
                df = pd.read_json(io.StringIO(json.dumps(row[0])), orient="split")
                df.index = pd.to_datetime(df.index)
                return df
            return None

        # SQLite path
        with _sqlite_connection() as conn:
            _ensure_mf_nav_cache_sqlite(conn)
            row = conn.execute(
                """
                SELECT nav_json FROM mf_nav_cache
                WHERE scheme_code = :code
                  AND updated_at >= datetime('now', :cutoff)
                """,
                {"code": str(scheme_code), "cutoff": f"-{int(max_age_hours)} hours"},
            ).fetchone()
        if row and row[0]:
            df = pd.read_json(io.StringIO(row[0]), orient="split")
            df.index = pd.to_datetime(df.index)
            return df
    except Exception as e:
        logger.debug("fetch_mf_nav_cache miss %s: %s", scheme_code, e)
    return None


def upsert_mf_nav_cache(scheme_code: str, df: pd.DataFrame):
    """Persist NAV history DataFrame for future cache hits. Works on both
    backends (previously Neon-only — see `fetch_mf_nav_cache`'s docstring)."""
    if df is None or df.empty:
        return
    try:
        payload = json.dumps(json.loads(df.to_json(date_format="iso", orient="split")))

        if _can_use_neon():
            _exec(
                "INSERT INTO mf_nav_cache (scheme_code, nav_json, updated_at) "
                "VALUES (:code, CAST(:payload AS JSONB), NOW()) "
                "ON CONFLICT (scheme_code) DO UPDATE "
                "SET nav_json=EXCLUDED.nav_json, updated_at=EXCLUDED.updated_at",
                {"code": str(scheme_code), "payload": payload},
            )
            return

        # SQLite path
        with _sqlite_connection() as conn:
            _ensure_mf_nav_cache_sqlite(conn)
            conn.execute(
                """
                INSERT INTO mf_nav_cache (scheme_code, nav_json, updated_at)
                VALUES (:code, :payload, CURRENT_TIMESTAMP)
                ON CONFLICT(scheme_code) DO UPDATE SET
                    nav_json = excluded.nav_json,
                    updated_at = excluded.updated_at
                """,
                {"code": str(scheme_code), "payload": payload},
            )
    except Exception as e:
        logger.debug("upsert_mf_nav_cache %s: %s", scheme_code, e)

# ═══════════════════════════════════════════════════════════════════════════════
#  NEW: Watchlist, Portfolio, Refresh Jobs — added for REITs/US Investing
# ═══════════════════════════════════════════════════════════════════════════════

def _ensure_investment_tables():
    """
    Create watchlist, portfolio_holdings, and refresh_jobs tables if absent.
    Works for both SQLite and Neon.
    """
    if _can_use_neon():
        # ── watchlist ──
        _exec("""
            CREATE TABLE IF NOT EXISTS watchlist (
                id          BIGSERIAL PRIMARY KEY,
                username    TEXT NOT NULL,
                symbol      TEXT NOT NULL,
                asset_class TEXT NOT NULL,
                name        TEXT,
                added_at    TIMESTAMPTZ DEFAULT NOW(),
                notes       TEXT,
                UNIQUE (username, symbol)
            )
        """)
        # ── portfolio_holdings ──
        _exec("""
            CREATE TABLE IF NOT EXISTS portfolio_holdings (
                id             BIGSERIAL PRIMARY KEY,
                username       TEXT NOT NULL,
                symbol         TEXT NOT NULL,
                asset_class    TEXT NOT NULL,
                name           TEXT,
                quantity       REAL NOT NULL DEFAULT 0,
                avg_price      REAL NOT NULL DEFAULT 0,
                currency       TEXT NOT NULL DEFAULT 'INR',
                allocation_pct REAL,
                notes          TEXT,
                updated_at     TIMESTAMPTZ DEFAULT NOW(),
                UNIQUE (username, symbol)
            )
        """)
        # ── refresh_jobs ──
        _exec("""
            CREATE TABLE IF NOT EXISTS refresh_jobs (
                id                BIGSERIAL PRIMARY KEY,
                job_type          TEXT NOT NULL,
                source            TEXT,
                started_at        TIMESTAMPTZ DEFAULT NOW(),
                finished_at       TIMESTAMPTZ,
                status            TEXT DEFAULT 'pending',
                error_detail      TEXT,
                records_refreshed INTEGER
            )
        """)
    else:
        # SQLite fallback
        _sqlite_exec("""
            CREATE TABLE IF NOT EXISTS watchlist (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                username    TEXT NOT NULL,
                symbol      TEXT NOT NULL,
                asset_class TEXT NOT NULL,
                name        TEXT,
                added_at    TEXT DEFAULT (datetime('now')),
                notes       TEXT,
                UNIQUE (username, symbol)
            )
        """)
        _sqlite_exec("""
            CREATE TABLE IF NOT EXISTS portfolio_holdings (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                username       TEXT NOT NULL,
                symbol         TEXT NOT NULL,
                asset_class    TEXT NOT NULL,
                name           TEXT,
                quantity       REAL NOT NULL DEFAULT 0,
                avg_price      REAL NOT NULL DEFAULT 0,
                currency       TEXT NOT NULL DEFAULT 'INR',
                allocation_pct REAL,
                notes          TEXT,
                updated_at     TEXT DEFAULT (datetime('now')),
                UNIQUE (username, symbol)
            )
        """)
        _sqlite_exec("""
            CREATE TABLE IF NOT EXISTS refresh_jobs (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                job_type          TEXT NOT NULL,
                source            TEXT,
                started_at        TEXT DEFAULT (datetime('now')),
                finished_at       TEXT,
                status            TEXT DEFAULT 'pending',
                error_detail      TEXT,
                records_refreshed INTEGER
            )
        """)


def _sqlite_exec(sql: str, params: dict = None):
    """Execute a statement on the SQLite connection."""
    import sqlite3
    db_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "fortress_history.db")
    con = sqlite3.connect(db_path)
    try:
        if params:
            con.execute(sql, params)
        else:
            con.execute(sql)
        con.commit()
    finally:
        con.close()


def _sqlite_query(sql: str, params: dict = None) -> list:
    """Query from the SQLite connection, return list of dicts."""
    import sqlite3
    db_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "fortress_history.db")
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    try:
        cur = con.execute(sql, params or {})
        return [dict(row) for row in cur.fetchall()]
    finally:
        con.close()


# ── Watchlist ──────────────────────────────────────────────────────────────────

def get_watchlist(username: str) -> list:
    try:
        _ensure_investment_tables()
        if _can_use_neon():
            rows = _query(
                "SELECT id, username, symbol, asset_class, name, added_at::text, notes "
                "FROM watchlist WHERE username = :u ORDER BY added_at DESC",
                {"u": username},
            )
            return [dict(r) for r in rows] if rows else []
        else:
            return _sqlite_query(
                "SELECT id, username, symbol, asset_class, name, added_at, notes "
                "FROM watchlist WHERE username = :u ORDER BY added_at DESC",
                {"u": username},
            )
    except Exception as exc:
        logger.error("get_watchlist: %s", exc)
        return []


def add_to_watchlist(username: str, symbol: str, asset_class: str, name: str = None, notes: str = None):
    _ensure_investment_tables()
    if _can_use_neon():
        _exec(
            "INSERT INTO watchlist (username, symbol, asset_class, name, notes) "
            "VALUES (:u, :s, :ac, :n, :notes) ON CONFLICT (username, symbol) DO NOTHING",
            {"u": username, "s": symbol, "ac": asset_class, "n": name, "notes": notes},
        )
    else:
        _sqlite_exec(
            "INSERT OR IGNORE INTO watchlist (username, symbol, asset_class, name, notes) "
            "VALUES (:u, :s, :ac, :n, :notes)",
            {"u": username, "s": symbol, "ac": asset_class, "n": name, "notes": notes},
        )


def remove_from_watchlist(username: str, symbol: str) -> bool:
    _ensure_investment_tables()
    try:
        if _can_use_neon():
            result = _query(
                "DELETE FROM watchlist WHERE username = :u AND symbol = :s RETURNING id",
                {"u": username, "s": symbol},
            )
            return bool(result)
        else:
            _sqlite_exec(
                "DELETE FROM watchlist WHERE username = :u AND symbol = :s",
                {"u": username, "s": symbol},
            )
            return True
    except Exception as exc:
        logger.error("remove_from_watchlist: %s", exc)
        return False


# ── Portfolio ──────────────────────────────────────────────────────────────────

def get_portfolio(username: str) -> list:
    try:
        _ensure_investment_tables()
        if _can_use_neon():
            rows = _query(
                "SELECT id, username, symbol, asset_class, name, quantity, avg_price, "
                "currency, allocation_pct, notes, updated_at::text "
                "FROM portfolio_holdings WHERE username = :u ORDER BY symbol",
                {"u": username},
            )
            return [dict(r) for r in rows] if rows else []
        else:
            return _sqlite_query(
                "SELECT id, username, symbol, asset_class, name, quantity, avg_price, "
                "currency, allocation_pct, notes, updated_at "
                "FROM portfolio_holdings WHERE username = :u ORDER BY symbol",
                {"u": username},
            )
    except Exception as exc:
        logger.error("get_portfolio: %s", exc)
        return []


def upsert_portfolio_holding(
    username: str, symbol: str, asset_class: str,
    quantity: float, avg_price: float, currency: str = "INR",
    allocation_pct: float = None, notes: str = None, name: str = None,
):
    _ensure_investment_tables()
    if _can_use_neon():
        _exec(
            "INSERT INTO portfolio_holdings "
            "(username, symbol, asset_class, name, quantity, avg_price, currency, allocation_pct, notes, updated_at) "
            "VALUES (:u, :s, :ac, :n, :qty, :price, :cur, :alloc, :notes, NOW()) "
            "ON CONFLICT (username, symbol) DO UPDATE SET "
            "quantity=EXCLUDED.quantity, avg_price=EXCLUDED.avg_price, currency=EXCLUDED.currency, "
            "allocation_pct=EXCLUDED.allocation_pct, notes=EXCLUDED.notes, updated_at=NOW()",
            {"u": username, "s": symbol, "ac": asset_class, "n": name,
             "qty": quantity, "price": avg_price, "cur": currency,
             "alloc": allocation_pct, "notes": notes},
        )
    else:
        _sqlite_exec(
            "INSERT OR REPLACE INTO portfolio_holdings "
            "(username, symbol, asset_class, name, quantity, avg_price, currency, allocation_pct, notes, updated_at) "
            "VALUES (:u, :s, :ac, :n, :qty, :price, :cur, :alloc, :notes, datetime('now'))",
            {"u": username, "s": symbol, "ac": asset_class, "n": name,
             "qty": quantity, "price": avg_price, "cur": currency,
             "alloc": allocation_pct, "notes": notes},
        )


def remove_portfolio_holding(username: str, symbol: str) -> bool:
    _ensure_investment_tables()
    try:
        if _can_use_neon():
            result = _query(
                "DELETE FROM portfolio_holdings WHERE username = :u AND symbol = :s RETURNING id",
                {"u": username, "s": symbol},
            )
            return bool(result)
        else:
            _sqlite_exec(
                "DELETE FROM portfolio_holdings WHERE username = :u AND symbol = :s",
                {"u": username, "s": symbol},
            )
            return True
    except Exception as exc:
        logger.error("remove_portfolio_holding: %s", exc)
        return False


# ── Refresh jobs ───────────────────────────────────────────────────────────────

def record_refresh_job_start(job_type: str, source: str = None) -> int:
    """Insert a new refresh_jobs row and return its ID."""
    _ensure_investment_tables()
    try:
        if _can_use_neon():
            row = _query(
                "INSERT INTO refresh_jobs (job_type, source, status) "
                "VALUES (:jt, :src, 'running') RETURNING id",
                {"jt": job_type, "src": source},
            )
            return row[0]["id"] if row else 0
        else:
            import sqlite3
            db_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "fortress_history.db")
            con = sqlite3.connect(db_path)
            cur = con.execute(
                "INSERT INTO refresh_jobs (job_type, source, status) VALUES (?, ?, 'running')",
                (job_type, source),
            )
            job_id = cur.lastrowid
            con.commit()
            con.close()
            return job_id
    except Exception as exc:
        logger.debug("record_refresh_job_start: %s", exc)
        return 0


def record_refresh_job_done(job_id: int, status: str = "done", records_refreshed: int = 0, error_detail: str = None):
    if not job_id:
        return
    _ensure_investment_tables()
    try:
        if _can_use_neon():
            _exec(
                "UPDATE refresh_jobs SET status=:s, finished_at=NOW(), records_refreshed=:cnt, error_detail=:err "
                "WHERE id=:id",
                {"s": status, "cnt": records_refreshed, "err": error_detail, "id": job_id},
            )
        else:
            _sqlite_exec(
                "UPDATE refresh_jobs SET status=:s, finished_at=datetime('now'), "
                "records_refreshed=:cnt, error_detail=:err WHERE id=:id",
                {"s": status, "cnt": records_refreshed, "err": error_detail, "id": job_id},
            )
    except Exception as exc:
        logger.debug("record_refresh_job_done: %s", exc)


def get_last_refresh_job(job_type: str) -> dict:
    try:
        _ensure_investment_tables()
        if _can_use_neon():
            rows = _query(
                "SELECT id, job_type, source, started_at::text, finished_at::text, "
                "status, error_detail, records_refreshed "
                "FROM refresh_jobs WHERE job_type=:jt ORDER BY id DESC LIMIT 1",
                {"jt": job_type},
            )
            return dict(rows[0]) if rows else None
        else:
            rows = _sqlite_query(
                "SELECT id, job_type, source, started_at, finished_at, status, "
                "error_detail, records_refreshed "
                "FROM refresh_jobs WHERE job_type=:jt ORDER BY id DESC LIMIT 1",
                {"jt": job_type},
            )
            return rows[0] if rows else None
    except Exception:
        return None


def get_all_refresh_jobs() -> list:
    try:
        _ensure_investment_tables()
        sql = (
            "SELECT DISTINCT ON (job_type) id, job_type, source, started_at::text as started_at, "
            "finished_at::text as finished_at, status, error_detail, records_refreshed "
            "FROM refresh_jobs ORDER BY job_type, id DESC"
        )
        if _can_use_neon():
            rows = _query(sql, {})
            return [dict(r) for r in rows] if rows else []
        else:
            rows = _sqlite_query(
                "SELECT id, job_type, source, started_at, finished_at, status, "
                "error_detail, records_refreshed FROM refresh_jobs "
                "GROUP BY job_type ORDER BY id DESC",
                {},
            )
            return rows
    except Exception:
        return []


def _ensure_reit_cache_neon():
    _exec("""
        CREATE TABLE IF NOT EXISTS reit_cache (
            symbol       TEXT PRIMARY KEY,
            payload_json JSONB,
            updated_at   TIMESTAMPTZ DEFAULT NOW()
        )
    """)


def _ensure_reit_cache_sqlite(conn) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS reit_cache (
            symbol       TEXT PRIMARY KEY,
            payload_json TEXT,
            updated_at   TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)


def fetch_reit_cache(max_age_hours: int = 4) -> list:
    """Return cached REIT/InvIT records fresher than max_age_hours, or []
    if there's no fresh cache. The router only uses this cache when it
    covers the *whole* configured universe (see routers/reit_invits.py) —
    a partial or empty result here just means "go do a live fetch".

    Previously this cache didn't exist at all (`upsert_reit_cache` was a
    literal no-op placeholder), so every request rebuilt the whole universe
    live from yfinance — 6-11 symbols each doing an OHLCV download plus two
    more `.info`/`.dividends` calls apiece. Combined with the route being
    declared `async def` around that synchronous work (see
    routers/reit_invits.py), that's what made the REIT/InvIT tab feel like
    it "keeps loading": every visit re-did the full slow fetch, and while
    it ran it froze request handling for the rest of the app too.
    """
    try:
        if _can_use_neon():
            engine = get_db_engine()
            with engine.connect() as conn:
                rows = conn.execute(
                    text("""
                    SELECT payload_json FROM reit_cache
                    WHERE updated_at >= NOW() - INTERVAL :age_h
                    """),
                    {"age_h": f"{max_age_hours} hours"},
                ).fetchall()
            return [r[0] for r in rows if r[0]]

        with _sqlite_connection() as conn:
            _ensure_reit_cache_sqlite(conn)
            rows = conn.execute(
                """
                SELECT payload_json FROM reit_cache
                WHERE updated_at >= datetime('now', :cutoff)
                """,
                {"cutoff": f"-{int(max_age_hours)} hours"},
            ).fetchall()
        return [json.loads(r[0]) for r in rows if r[0]]
    except Exception as e:
        logger.error("reit_cache fetch error: %s", e)
        return []


def upsert_reit_cache(records: list):
    """Persist scored REIT/InvIT records so they survive process restarts
    and repeat requests don't force a live re-fetch. Works on both
    backends. See `fetch_reit_cache` for why this mattered."""
    if not records:
        return
    try:
        if _can_use_neon():
            for r in records:
                symbol = r.get("symbol")
                if not symbol:
                    continue
                payload = json.dumps(r, default=str)
                _exec(
                    """
                    INSERT INTO reit_cache (symbol, payload_json, updated_at)
                    VALUES (:sym, CAST(:payload AS JSONB), NOW())
                    ON CONFLICT (symbol) DO UPDATE
                      SET payload_json = EXCLUDED.payload_json,
                          updated_at = EXCLUDED.updated_at
                    """,
                    {"sym": symbol, "payload": payload},
                )
            return

        with _sqlite_connection() as conn:
            _ensure_reit_cache_sqlite(conn)
            for r in records:
                symbol = r.get("symbol")
                if not symbol:
                    continue
                payload = json.dumps(r, default=str)
                conn.execute(
                    """
                    INSERT INTO reit_cache (symbol, payload_json, updated_at)
                    VALUES (:sym, :payload, CURRENT_TIMESTAMP)
                    ON CONFLICT(symbol) DO UPDATE SET
                        payload_json = excluded.payload_json,
                        updated_at = excluded.updated_at
                    """,
                    {"sym": symbol, "payload": payload},
                )
    except Exception as e:
        logger.error("reit_cache upsert error: %s", e)


def upsert_us_cache(records: list):
    """Placeholder — US data cached in-memory for now; add Neon persistence if needed."""
    pass


# ─────────────────────────────────────────────
# NSE Bhav Copy EOD price history + fetch dedup log
# ─────────────────────────────────────────────
#
# bhavcopy_eod accumulates one row per (symbol, trade_date) from NSE's daily
# EOD file — this is what lets market_data_provider.get_ohlcv() answer "last
# N days" once enough days have accumulated (or been backfilled), unlike
# ohlcv_cache above which stores one whole-period JSON blob per symbol and
# can't be sliced.
#
# bhavcopy_fetch_log is a *separate* table from bhavcopy_eod on purpose: it's
# the actual "don't re-fetch today's file" guard the daily refresh job
# checks before making any network call. bhavcopy_eod's own
# PRIMARY KEY (symbol, trade_date) upsert makes repeat writes safe, but does
# nothing to stop a repeat job run from re-downloading and re-parsing the
# whole market file — that's what bhavcopy_fetch_log prevents.

_BHAVCOPY_EOD_COLUMNS = [
    "open",
    "high",
    "low",
    "close",
    "volume",
    "turnover",
    "deliv_qty",
    "deliv_pct",
]


def _ensure_bhavcopy_eod_neon():
    _exec("""
        CREATE TABLE IF NOT EXISTS bhavcopy_eod (
            symbol      TEXT NOT NULL,
            trade_date  DATE NOT NULL,
            open        DOUBLE PRECISION,
            high        DOUBLE PRECISION,
            low         DOUBLE PRECISION,
            close       DOUBLE PRECISION,
            volume      BIGINT,
            turnover    DOUBLE PRECISION,
            deliv_qty   BIGINT,
            deliv_pct   DOUBLE PRECISION,
            updated_at  TIMESTAMPTZ DEFAULT NOW(),
            PRIMARY KEY (symbol, trade_date)
        )
    """)
    _exec(
        "CREATE INDEX IF NOT EXISTS idx_bhavcopy_eod_symbol_date "
        "ON bhavcopy_eod (symbol, trade_date DESC)"
    )


def _ensure_bhavcopy_eod_sqlite(conn) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS bhavcopy_eod (
            symbol      TEXT NOT NULL,
            trade_date  TEXT NOT NULL,
            open        REAL,
            high        REAL,
            low         REAL,
            close       REAL,
            volume      INTEGER,
            turnover    REAL,
            deliv_qty   INTEGER,
            deliv_pct   REAL,
            updated_at  TEXT DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (symbol, trade_date)
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_bhavcopy_eod_symbol_date "
        "ON bhavcopy_eod (symbol, trade_date DESC)"
    )


def _ensure_bhavcopy_fetch_log_neon():
    _exec("""
        CREATE TABLE IF NOT EXISTS bhavcopy_fetch_log (
            trade_date    DATE PRIMARY KEY,
            status        TEXT NOT NULL,
            symbol_count  INTEGER,
            fetched_at    TIMESTAMPTZ DEFAULT NOW(),
            error_detail  TEXT
        )
    """)


def _ensure_bhavcopy_fetch_log_sqlite(conn) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS bhavcopy_fetch_log (
            trade_date    TEXT PRIMARY KEY,
            status        TEXT NOT NULL,
            symbol_count  INTEGER,
            fetched_at    TEXT DEFAULT CURRENT_TIMESTAMP,
            error_detail  TEXT
        )
    """)


def get_bhavcopy_fetch_status(trade_date: str) -> Optional[str]:
    """Return the recorded status ('done' | 'not_yet_published' | 'error') for
    trade_date ("YYYY-MM-DD"), or None if no attempt has been logged yet.

    The daily refresh job calls this BEFORE doing any network call to NSE —
    a status of "done" means skip the fetch entirely.
    """
    try:
        if _can_use_neon():
            engine = get_db_engine()
            with engine.connect() as conn:
                row = conn.execute(
                    text("SELECT status FROM bhavcopy_fetch_log WHERE trade_date = :d"),
                    {"d": trade_date},
                ).fetchone()
            return row[0] if row else None

        with _sqlite_connection() as conn:
            _ensure_bhavcopy_fetch_log_sqlite(conn)
            row = conn.execute(
                "SELECT status FROM bhavcopy_fetch_log WHERE trade_date = :d",
                {"d": trade_date},
            ).fetchone()
        return row[0] if row else None
    except Exception as e:
        logger.error("bhavcopy_fetch_log read error for %s: %s", trade_date, e)
        return None


def record_bhavcopy_fetch(
    trade_date: str,
    status: str,
    symbol_count: int = 0,
    error_detail: Optional[str] = None,
):
    """Upsert today's fetch attempt outcome. Recording status='done' is what
    makes the next job invocation skip the network call (see
    get_bhavcopy_fetch_status). A "not_yet_published" or "error" status is
    deliberately NOT treated as a reason to skip — the next scheduled run
    should retry."""
    try:
        if _can_use_neon():
            _exec(
                """
                INSERT INTO bhavcopy_fetch_log (trade_date, status, symbol_count, fetched_at, error_detail)
                VALUES (:d, :s, :cnt, NOW(), :err)
                ON CONFLICT (trade_date) DO UPDATE SET
                    status = EXCLUDED.status,
                    symbol_count = EXCLUDED.symbol_count,
                    fetched_at = EXCLUDED.fetched_at,
                    error_detail = EXCLUDED.error_detail
                """,
                {"d": trade_date, "s": status, "cnt": symbol_count, "err": error_detail},
            )
            return

        with _sqlite_connection() as conn:
            _ensure_bhavcopy_fetch_log_sqlite(conn)
            conn.execute(
                """
                INSERT INTO bhavcopy_fetch_log (trade_date, status, symbol_count, fetched_at, error_detail)
                VALUES (:d, :s, :cnt, CURRENT_TIMESTAMP, :err)
                ON CONFLICT(trade_date) DO UPDATE SET
                    status = excluded.status,
                    symbol_count = excluded.symbol_count,
                    fetched_at = excluded.fetched_at,
                    error_detail = excluded.error_detail
                """,
                {"d": trade_date, "s": status, "cnt": symbol_count, "err": error_detail},
            )
    except Exception as e:
        logger.error("bhavcopy_fetch_log write error for %s: %s", trade_date, e)


def upsert_bhavcopy_rows(df: "pd.DataFrame", trade_date: str) -> int:
    """Bulk upsert one day's parsed Bhav Copy rows into bhavcopy_eod.

    `df` must have a "symbol" column plus any subset of
    `_BHAVCOPY_EOD_COLUMNS` — missing ones are written as NULL. Returns the
    number of rows written. Idempotent: re-running for the same trade_date
    overwrites rather than duplicating, via PRIMARY KEY (symbol, trade_date).
    """
    if df is None or df.empty:
        return 0

    cols = _BHAVCOPY_EOD_COLUMNS
    col_list = ", ".join(cols)
    written = 0
    try:
        if _can_use_neon():
            placeholders = ", ".join(f":{c}" for c in cols)
            update_set = ", ".join(f"{c} = EXCLUDED.{c}" for c in cols)
            sql = f"""
                INSERT INTO bhavcopy_eod (symbol, trade_date, {col_list}, updated_at)
                VALUES (:sym, :d, {placeholders}, NOW())
                ON CONFLICT (symbol, trade_date) DO UPDATE SET
                    {update_set},
                    updated_at = EXCLUDED.updated_at
            """
            for _, row in df.iterrows():
                symbol = row.get("symbol")
                if not symbol:
                    continue
                params = {"sym": symbol, "d": trade_date}
                params.update(
                    {c: (row.get(c) if pd.notna(row.get(c)) else None) for c in cols}
                )
                _exec(sql, params)
                written += 1
            return written

        with _sqlite_connection() as conn:
            _ensure_bhavcopy_eod_sqlite(conn)
            placeholders = ", ".join(f":{c}" for c in cols)
            update_set = ", ".join(f"{c} = excluded.{c}" for c in cols)
            sql = f"""
                INSERT INTO bhavcopy_eod (symbol, trade_date, {col_list}, updated_at)
                VALUES (:sym, :d, {placeholders}, CURRENT_TIMESTAMP)
                ON CONFLICT(symbol, trade_date) DO UPDATE SET
                    {update_set},
                    updated_at = excluded.updated_at
            """
            for _, row in df.iterrows():
                symbol = row.get("symbol")
                if not symbol:
                    continue
                params = {"sym": symbol, "d": trade_date}
                params.update(
                    {c: (row.get(c) if pd.notna(row.get(c)) else None) for c in cols}
                )
                conn.execute(sql, params)
                written += 1
        return written
    except Exception as e:
        logger.error("bhavcopy_eod upsert error for %s: %s", trade_date, e)
        return written


def fetch_bhavcopy_ohlcv(
    symbol: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> "pd.DataFrame":
    """Return OHLCV history for `symbol` from bhavcopy_eod, shaped like the
    DataFrame market_data_provider.get_ohlcv() callers already expect:
    columns ["Open", "High", "Low", "Close", "Volume"] and a DatetimeIndex.

    start_date/end_date are inclusive "YYYY-MM-DD" strings; omit either for
    an open-ended bound. Translating a yfinance-style period string (e.g.
    "1y") into start_date is the caller's job (market_data_provider.py), to
    keep that domain-level concern out of this DB-access layer — see
    _period_to_ms there for the existing period-parsing convention.

    Returns an empty DataFrame if nothing is cached yet (e.g. backfill
    hasn't run, or a recent listing with no history).
    """
    try:
        where = ["symbol = :sym"]
        params: Dict[str, Any] = {"sym": symbol}
        if start_date:
            where.append("trade_date >= :start_d")
            params["start_d"] = start_date
        if end_date:
            where.append("trade_date <= :end_d")
            params["end_d"] = end_date
        where_sql = " AND ".join(where)

        sql = f"""
            SELECT trade_date, open, high, low, close, volume
            FROM bhavcopy_eod
            WHERE {where_sql}
            ORDER BY trade_date ASC
        """

        if _can_use_neon():
            df = _read_df_uncached(sql, params)
        else:
            with _sqlite_connection() as conn:
                _ensure_bhavcopy_eod_sqlite(conn)
                df = pd.read_sql_query(sql, conn, params=params)

        if df.empty:
            return pd.DataFrame()

        df["trade_date"] = pd.to_datetime(df["trade_date"])
        df = df.set_index("trade_date").rename(
            columns={
                "open": "Open",
                "high": "High",
                "low": "Low",
                "close": "Close",
                "volume": "Volume",
            }
        )
        df.index.name = "Date"
        return df[["Open", "High", "Low", "Close", "Volume"]]
    except Exception as e:
        logger.error("bhavcopy_eod fetch error for %s: %s", symbol, e)
        return pd.DataFrame()


def fetch_bhavcopy_ohlcv_batch(
    symbols: List[str],
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> Dict[str, "pd.DataFrame"]:
    """Same as fetch_bhavcopy_ohlcv but for many symbols in one query,
    for market_data_provider.get_batch_ohlcv()'s bhavcopy tier — this is a
    single local DB read (indexed on (symbol, trade_date)), not a network
    call, so it's cheap even for the full scan universe (~150-200 symbols)
    in a way per-symbol INDstocks calls are not.

    Returns a dict of symbol -> DataFrame, same shape as get_batch_ohlcv():
    symbols with no cached rows are simply absent from the dict.
    """
    if not symbols:
        return {}
    try:
        placeholders = ", ".join(f":sym{i}" for i in range(len(symbols)))
        params: Dict[str, Any] = {f"sym{i}": s for i, s in enumerate(symbols)}
        where = [f"symbol IN ({placeholders})"]
        if start_date:
            where.append("trade_date >= :start_d")
            params["start_d"] = start_date
        if end_date:
            where.append("trade_date <= :end_d")
            params["end_d"] = end_date
        where_sql = " AND ".join(where)

        sql = f"""
            SELECT symbol, trade_date, open, high, low, close, volume
            FROM bhavcopy_eod
            WHERE {where_sql}
            ORDER BY symbol ASC, trade_date ASC
        """

        if _can_use_neon():
            df = _read_df_uncached(sql, params)
        else:
            with _sqlite_connection() as conn:
                _ensure_bhavcopy_eod_sqlite(conn)
                df = pd.read_sql_query(sql, conn, params=params)

        if df.empty:
            return {}

        df["trade_date"] = pd.to_datetime(df["trade_date"])
        result: Dict[str, pd.DataFrame] = {}
        for symbol, group in df.groupby("symbol"):
            sub = group.set_index("trade_date").rename(
                columns={
                    "open": "Open",
                    "high": "High",
                    "low": "Low",
                    "close": "Close",
                    "volume": "Volume",
                }
            )
            sub.index.name = "Date"
            result[symbol] = sub[["Open", "High", "Low", "Close", "Volume"]]
        return result
    except Exception as e:
        logger.error("bhavcopy_eod batch fetch error: %s", e)
        return {}


def get_bhavcopy_coverage_summary() -> Dict[str, Any]:
    """Return how much Bhav Copy history is actually stored right now:
    {"trading_days_covered": int, "symbol_count": int,
     "earliest_date": "YYYY-MM-DD"|None, "latest_date": "YYYY-MM-DD"|None}.

    Exists so a caller (e.g. GET /api/bhavcopy/status) can show real
    progress during/after a backfill_bhavcopy() run without needing to poll
    bhavcopy_fetch_log row-by-row for every date in the range.
    """
    empty = {
        "trading_days_covered": 0,
        "symbol_count": 0,
        "earliest_date": None,
        "latest_date": None,
    }
    try:
        sql = """
            SELECT COUNT(DISTINCT trade_date) AS trading_days,
                   COUNT(DISTINCT symbol) AS symbols,
                   MIN(trade_date) AS earliest,
                   MAX(trade_date) AS latest
            FROM bhavcopy_eod
        """
        # _query() itself branches on the backend (Neon vs SQLite) and
        # returns [] on a missing table via the surrounding try/except below
        # — no data yet is a completely normal state before the first
        # refresh/backfill has ever run.
        rows = _query(sql)

        if not rows or rows[0]["trading_days"] is None:
            return empty

        row = rows[0]
        return {
            "trading_days_covered": int(row["trading_days"] or 0),
            "symbol_count": int(row["symbols"] or 0),
            "earliest_date": str(row["earliest"])[:10] if row["earliest"] else None,
            "latest_date": str(row["latest"])[:10] if row["latest"] else None,
        }
    except Exception as e:
        logger.error("bhavcopy coverage summary error: %s", e)
        return empty


# ─────────────────────────────────────────────
# Generic key/value app settings (single-operator tool — no per-user scope)
# ─────────────────────────────────────────────


def _ensure_app_settings_neon():
    _exec("""
        CREATE TABLE IF NOT EXISTS app_settings (
            key         TEXT PRIMARY KEY,
            value       TEXT,
            updated_at  TIMESTAMPTZ DEFAULT NOW()
        )
    """)


def _ensure_app_settings_sqlite(conn) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS app_settings (
            key         TEXT PRIMARY KEY,
            value       TEXT,
            updated_at  TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)


def get_setting(key: str, default: Optional[str] = None) -> Optional[str]:
    """Read one app_settings value, or `default` if unset."""
    try:
        if _can_use_neon():
            engine = get_db_engine()
            with engine.connect() as conn:
                row = conn.execute(
                    text("SELECT value FROM app_settings WHERE key = :k"), {"k": key}
                ).fetchone()
            return row[0] if row else default

        with _sqlite_connection() as conn:
            _ensure_app_settings_sqlite(conn)
            row = conn.execute(
                "SELECT value FROM app_settings WHERE key = :k", {"k": key}
            ).fetchone()
        return row[0] if row else default
    except Exception as e:
        logger.error("app_settings read error for %s: %s", key, e)
        return default


def set_setting(key: str, value: str) -> None:
    """Upsert one app_settings value."""
    try:
        if _can_use_neon():
            _exec(
                """
                INSERT INTO app_settings (key, value, updated_at)
                VALUES (:k, :v, NOW())
                ON CONFLICT (key) DO UPDATE SET
                    value = EXCLUDED.value, updated_at = EXCLUDED.updated_at
                """,
                {"k": key, "v": value},
            )
            return

        with _sqlite_connection() as conn:
            _ensure_app_settings_sqlite(conn)
            conn.execute(
                """
                INSERT INTO app_settings (key, value, updated_at)
                VALUES (:k, :v, CURRENT_TIMESTAMP)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value, updated_at = excluded.updated_at
                """,
                {"k": key, "v": value},
            )
    except Exception as e:
        logger.error("app_settings write error for %s: %s", key, e)
