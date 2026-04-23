# database.py
# =============================================================================
# SQLite persistence for the Top-Camera Palletiser.
#
# Tables
# ──────
#   custom_pallets        – one row per pallet session
#   custom_keg_locations  – one row per individual keg scan
#
# Removed from original schema (never read or written by this system):
#   beer_type, batch, filling_date, qr_generated, qr_data,
#   allocated_to, allocated_at, operator, notes,
#   source_locations (JSON), keg_data (JSON), total_kegs
#
# Recovery & safety
# ─────────────────
#   • WAL journal  – writers don't block readers; survives hard power-loss
#   • FULL sync    – fsync after every commit; no silent data corruption
#   • Busy timeout – waits up to DB_CONFIG['timeout'] s before raising
#   • _migrate()   – safe ALTER TABLE for cola_count / water_count so the
#                    app can be deployed over an existing DB without wiping it
#   • All writes use context-manager (auto-rollback on exception)
# =============================================================================

import sqlite3
import json
from typing import List, Dict, Any, Optional

from config import DB_PATH, DB_CONFIG, logger


# ── internal helpers ──────────────────────────────────────────────────────────

def _connect(db_path: str) -> sqlite3.Connection:
    """Open a connection with the standard safety pragmas."""
    conn = sqlite3.connect(db_path, timeout=DB_CONFIG['timeout'])
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA journal_mode=WAL;')
    conn.execute('PRAGMA synchronous=FULL;')
    conn.execute('PRAGMA foreign_keys=ON;')
    return conn


# =============================================================================
# DatabaseManager
# =============================================================================

class DatabaseManager:

    def __init__(self, db_path: str | None = None):
        self.db_path = str(db_path) if db_path else str(DB_PATH)
        self._init_schema()
        self._migrate()

    # =========================================================================
    # SCHEMA
    # =========================================================================

    def _init_schema(self) -> None:
        """Create tables and indexes if they don't exist yet."""
        pallet_table = DB_CONFIG['custom_pallet_table']
        keg_table    = DB_CONFIG['custom_keg_table']

        with _connect(self.db_path) as conn:
            conn.executescript(f"""
                CREATE TABLE IF NOT EXISTS {pallet_table} (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    pallet_id    TEXT    UNIQUE NOT NULL,
                    customer_name TEXT,
                    status        TEXT    NOT NULL DEFAULT 'assembling',
                    cola_count    INTEGER NOT NULL DEFAULT 0,
                    water_count   INTEGER NOT NULL DEFAULT 0,
                    created_at    TEXT    NOT NULL DEFAULT (datetime('now'))
                );

                CREATE TABLE IF NOT EXISTS {keg_table} (
                    id                INTEGER PRIMARY KEY AUTOINCREMENT,
                    custom_pallet_id  TEXT NOT NULL
                        REFERENCES {pallet_table}(pallet_id),
                    source_location   TEXT NOT NULL,
                    keg_count         INTEGER NOT NULL DEFAULT 1,
                    keg_qrs           TEXT NOT NULL DEFAULT '[]',
                    taken_at          TEXT NOT NULL DEFAULT (datetime('now'))
                );

                CREATE INDEX IF NOT EXISTS idx_pallet_status
                    ON {pallet_table}(status);

                CREATE INDEX IF NOT EXISTS idx_pallet_customer
                    ON {pallet_table}(customer_name);

                CREATE INDEX IF NOT EXISTS idx_keg_pallet
                    ON {keg_table}(custom_pallet_id);
            """)
        logger.info("Database schema ready.")

    def _migrate(self) -> None:
        """
        Non-destructive migration for deployments upgrading from the old schema.
        Adds cola_count / water_count if they are absent; ignores if present.
        """
        pallet_table = DB_CONFIG['custom_pallet_table']
        migrations = [
            f"ALTER TABLE {pallet_table} ADD COLUMN cola_count  INTEGER NOT NULL DEFAULT 0",
            f"ALTER TABLE {pallet_table} ADD COLUMN water_count INTEGER NOT NULL DEFAULT 0",
        ]
        with _connect(self.db_path) as conn:
            for sql in migrations:
                try:
                    conn.execute(sql)
                except sqlite3.OperationalError:
                    pass   # column already exists – fine
        logger.debug("DB migration check complete.")

    # =========================================================================
    # PALLET OPERATIONS
    # =========================================================================

    def create_pallet(self, pallet_id: str, customer_name: str | None = None) -> bool:
        """
        Insert a new pallet row with status='assembling'.
        Returns False (without raising) if the pallet_id already exists.
        """
        try:
            with _connect(self.db_path) as conn:
                conn.execute(
                    f"""INSERT INTO {DB_CONFIG['custom_pallet_table']}
                        (pallet_id, customer_name, status)
                        VALUES (?, ?, 'assembling')""",
                    (pallet_id, customer_name),
                )
            logger.info(f"DB: created pallet {pallet_id}")
            return True
        except sqlite3.IntegrityError:
            logger.warning(f"DB: pallet {pallet_id} already exists skipped")
            return False
        except Exception as exc:
            logger.error(f"DB create_pallet error: {exc}")
            return False

    def update_pallet_status(
        self,
        pallet_id: str,
        status: str,
        customer_name: str | None = None,
    ) -> bool:
        """Update pallet status and optionally the customer."""
        try:
            with _connect(self.db_path) as conn:
                if customer_name is not None:
                    conn.execute(
                        f"""UPDATE {DB_CONFIG['custom_pallet_table']}
                            SET status=?, customer_name=?
                            WHERE pallet_id=?""",
                        (status, customer_name, pallet_id),
                    )
                else:
                    conn.execute(
                        f"""UPDATE {DB_CONFIG['custom_pallet_table']}
                            SET status=?
                            WHERE pallet_id=?""",
                        (status, pallet_id),
                    )
            logger.info(f"DB: pallet {pallet_id} → {status}")
            return True
        except Exception as exc:
            logger.error(f"DB update_pallet_status error: {exc}")
            return False

    def update_product_counts(
        self, pallet_id: str, cola: int, water: int
    ) -> bool:
        """Persist cumulative cola / water pack counts for a session."""
        try:
            with _connect(self.db_path) as conn:
                conn.execute(
                    f"""UPDATE {DB_CONFIG['custom_pallet_table']}
                        SET cola_count=?, water_count=?
                        WHERE pallet_id=?""",
                    (cola, water, pallet_id),
                )
            logger.debug(f"DB: product counts updated cola={cola}, water={water}")
            return True
        except Exception as exc:
            logger.error(f"DB update_product_counts error: {exc}")
            return False

    def get_recent_pallets(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Return recent pallets ordered by creation time, newest first."""
        try:
            with _connect(self.db_path) as conn:
                rows = conn.execute(
                    f"""SELECT pallet_id, customer_name, status,
                               cola_count, water_count, created_at
                        FROM {DB_CONFIG['custom_pallet_table']}
                        ORDER BY created_at DESC
                        LIMIT ?""",
                    (limit,),
                ).fetchall()
            return [dict(r) for r in rows]
        except Exception as exc:
            logger.error(f"DB get_recent_pallets error: {exc}")
            return []

    # =========================================================================
    # KEG OPERATIONS
    # =========================================================================

    def add_keg_entry(
        self,
        pallet_id: str,
        location: str,
        qr_codes: List[str],
    ) -> bool:
        """
        Write one keg-scan row.  keg_count is always 1 (one QR = one keg).
        The caller is responsible for not passing duplicate QR codes.
        """
        try:
            with _connect(self.db_path) as conn:
                conn.execute(
                    f"""INSERT INTO {DB_CONFIG['custom_keg_table']}
                        (custom_pallet_id, source_location, keg_count, keg_qrs)
                        VALUES (?, ?, 1, ?)""",
                    (pallet_id, location, json.dumps(qr_codes)),
                )
            logger.debug(f"DB: keg entry added {qr_codes} → {pallet_id}")
            return True
        except Exception as exc:
            logger.error(f"DB add_keg_entry error: {exc}")
            return False

    def get_keg_entries(self, pallet_id: str) -> List[Dict[str, Any]]:
        """Return all keg rows for a pallet, newest first."""
        try:
            with _connect(self.db_path) as conn:
                rows = conn.execute(
                    f"""SELECT keg_qrs, source_location, taken_at
                        FROM {DB_CONFIG['custom_keg_table']}
                        WHERE custom_pallet_id=?
                        ORDER BY taken_at DESC""",
                    (pallet_id,),
                ).fetchall()
            result = []
            for r in rows:
                entry = dict(r)
                entry['keg_qrs'] = json.loads(entry['keg_qrs'] or '[]')
                result.append(entry)
            return result
        except Exception as exc:
            logger.error(f"DB get_keg_entries error: {exc}")
            return []



_db_instance: DatabaseManager | None = None


def get_database() -> DatabaseManager:
    global _db_instance
    if _db_instance is None:
        _db_instance = DatabaseManager()
    return _db_instance