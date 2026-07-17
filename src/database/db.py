"""Conexão e schema do banco SQLite.

Conexões são criadas por chamada (`get_connection`) — sqlite3 não permite
compartilhar conexões entre threads, e o pipeline roda em worker thread.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from typing import Iterator

from src.config.constants import DATABASE_FILE
from src.utils.logger import get_logger

logger = get_logger("database")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    title       TEXT NOT NULL,
    source_path TEXT NOT NULL,
    source_url  TEXT,
    duration    REAL NOT NULL DEFAULT 0,
    status      TEXT NOT NULL DEFAULT 'new',
    created_at  TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS cuts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id  INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    title       TEXT NOT NULL,
    description TEXT,
    hashtags    TEXT,
    category    TEXT,
    start       REAL NOT NULL,
    end         REAL NOT NULL,
    score       INTEGER NOT NULL DEFAULT 0,
    reason      TEXT,
    output_path TEXT,
    status      TEXT NOT NULL DEFAULT 'pending'
);

CREATE TABLE IF NOT EXISTS app_settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE INDEX IF NOT EXISTS idx_cuts_project ON cuts(project_id);
"""


def init_database() -> None:
    """Cria as tabelas se não existirem (idempotente)."""
    with get_connection() as conn:
        conn.executescript(_SCHEMA)
    logger.info("Banco de dados pronto: %s", DATABASE_FILE)


@contextmanager
def get_connection() -> Iterator[sqlite3.Connection]:
    """Context manager: abre conexão com FK ativas, commita e fecha."""
    conn = sqlite3.connect(DATABASE_FILE)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
