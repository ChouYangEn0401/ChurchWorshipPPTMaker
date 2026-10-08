"""SQLite 資料庫：一個檔案裝下歌詞庫、歌單、背景、排版與匯出紀錄。

- 每次操作開一條短連線（WAL 模式，網頁同時有人讀寫也不會卡住）。
- 寫入一律走 tx()，在同一把鎖底下 BEGIN IMMEDIATE，避免兩個人同時存檔互相覆蓋一半。
- 資料表結構用 MIGRATIONS 管理：只能往後加，不能改舊的；目前版本記在 PRAGMA user_version。
"""

from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

MIGRATIONS: list[tuple[int, str]] = [
    (1, """
CREATE TABLE kv (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE images (
    id         TEXT PRIMARY KEY,
    name       TEXT NOT NULL,
    ext        TEXT NOT NULL,
    width      INTEGER NOT NULL DEFAULT 0,
    height     INTEGER NOT NULL DEFAULT 0,
    bytes      INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    created_by TEXT NOT NULL DEFAULT ''
);

CREATE TABLE themes (
    id         INTEGER PRIMARY KEY,
    name       TEXT NOT NULL,
    image_id   TEXT REFERENCES images(id) ON DELETE SET NULL,
    bg_color   TEXT NOT NULL DEFAULT '#000000',
    overlay    REAL NOT NULL DEFAULT 0,
    tags       TEXT NOT NULL DEFAULT '',
    archived   INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE styles (
    id         INTEGER PRIMARY KEY,
    name       TEXT NOT NULL,
    data       TEXT NOT NULL,
    archived   INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE songs (
    id         INTEGER PRIMARY KEY,
    title      TEXT NOT NULL,
    title_key  TEXT NOT NULL UNIQUE,
    aliases    TEXT NOT NULL DEFAULT '',
    song_key   TEXT NOT NULL DEFAULT '',
    lyrics     TEXT NOT NULL DEFAULT '',
    sequence   TEXT NOT NULL DEFAULT '',
    theme_id   INTEGER REFERENCES themes(id) ON DELETE SET NULL,
    style_id   INTEGER REFERENCES styles(id) ON DELETE SET NULL,
    notes      TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    updated_by TEXT NOT NULL DEFAULT ''
);

CREATE TABLE song_revisions (
    id         INTEGER PRIMARY KEY,
    song_id    INTEGER NOT NULL REFERENCES songs(id) ON DELETE CASCADE,
    lyrics     TEXT NOT NULL,
    sequence   TEXT NOT NULL,
    reason     TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    created_by TEXT NOT NULL DEFAULT ''
);
CREATE INDEX song_revisions_song ON song_revisions(song_id, id);

CREATE TABLE services (
    id              INTEGER PRIMARY KEY,
    date            TEXT NOT NULL,
    name            TEXT NOT NULL,
    team            TEXT NOT NULL DEFAULT '',
    slide_size      TEXT NOT NULL DEFAULT '4:3',
    follow_sequence INTEGER NOT NULL DEFAULT 1,
    source_url      TEXT NOT NULL DEFAULT '',
    notes           TEXT NOT NULL DEFAULT '',
    version         INTEGER NOT NULL DEFAULT 1,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    updated_by      TEXT NOT NULL DEFAULT ''
);
CREATE INDEX services_date ON services(date);

CREATE TABLE service_items (
    id         INTEGER PRIMARY KEY,
    service_id INTEGER NOT NULL REFERENCES services(id) ON DELETE CASCADE,
    position   INTEGER NOT NULL,
    song_id    INTEGER REFERENCES songs(id) ON DELETE SET NULL,
    title      TEXT NOT NULL DEFAULT '',
    song_key   TEXT NOT NULL DEFAULT '',
    lyrics     TEXT NOT NULL DEFAULT '',
    sequence   TEXT NOT NULL DEFAULT '',
    theme_id   INTEGER REFERENCES themes(id) ON DELETE SET NULL,
    style_id   INTEGER REFERENCES styles(id) ON DELETE SET NULL,
    version    INTEGER NOT NULL DEFAULT 1,
    updated_at TEXT NOT NULL,
    updated_by TEXT NOT NULL DEFAULT ''
);
CREATE INDEX service_items_service ON service_items(service_id, position);
CREATE INDEX service_items_song ON service_items(song_id);

CREATE TABLE exports (
    id           INTEGER PRIMARY KEY,
    service_id   INTEGER REFERENCES services(id) ON DELETE SET NULL,
    service_name TEXT NOT NULL,
    service_date TEXT NOT NULL,
    filename     TEXT NOT NULL,
    file         TEXT NOT NULL,
    slides       INTEGER NOT NULL,
    bytes        INTEGER NOT NULL,
    snapshot     TEXT NOT NULL,
    warnings     TEXT NOT NULL DEFAULT '[]',
    created_at   TEXT NOT NULL,
    created_by   TEXT NOT NULL DEFAULT ''
);
CREATE INDEX exports_service ON exports(service_id, id);

CREATE TABLE sessions (
    token_hash TEXT PRIMARY KEY,
    name       TEXT NOT NULL DEFAULT '',
    csrf       TEXT NOT NULL,
    host       TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL,
    last_seen  REAL NOT NULL,
    ip         TEXT NOT NULL DEFAULT '',
    user_agent TEXT NOT NULL DEFAULT ''
)
"""),
]

LATEST_VERSION = MIGRATIONS[-1][0]


def now_text() -> str:
    """資料庫裡的時間一律用本地時間的 ISO 字串（到秒），畫面上直接好讀。"""
    return datetime.now().replace(microsecond=0).isoformat(sep=" ")


class Database:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = threading.RLock()

    # ---------- connection ----------
    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=15, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=15000")
        return conn

    @contextmanager
    def read(self) -> Iterator[sqlite3.Connection]:
        conn = self._connect()
        try:
            yield conn
        finally:
            conn.close()

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            conn = self._connect()
            try:
                conn.execute("BEGIN IMMEDIATE")
                yield conn
                conn.execute("COMMIT")
            except BaseException:
                if conn.in_transaction:
                    conn.execute("ROLLBACK")
                raise
            finally:
                conn.close()

    # ---------- schema ----------
    def migrate(self) -> int:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            conn = self._connect()
            try:
                conn.execute("PRAGMA journal_mode=WAL")
                current = conn.execute("PRAGMA user_version").fetchone()[0]
                for version, script in MIGRATIONS:
                    if version <= current:
                        continue
                    conn.execute("BEGIN IMMEDIATE")
                    try:
                        for statement in script.split(";"):
                            if statement.strip():
                                conn.execute(statement)
                        conn.execute(f"PRAGMA user_version={version}")
                        conn.execute("COMMIT")
                    except BaseException:
                        conn.execute("ROLLBACK")
                        raise
                    current = version
                return current
            finally:
                conn.close()

    # ---------- helpers ----------
    def one(self, sql: str, params: tuple | dict = ()) -> dict | None:
        with self.read() as conn:
            row = conn.execute(sql, params).fetchone()
            return dict(row) if row else None

    def all(self, sql: str, params: tuple | dict = ()) -> list[dict]:
        with self.read() as conn:
            return [dict(r) for r in conn.execute(sql, params).fetchall()]

    def kv_get(self, key: str, default: Any = None) -> Any:
        row = self.one("SELECT value FROM kv WHERE key=?", (key,))
        if row is None:
            return default
        try:
            return json.loads(row["value"])
        except ValueError:
            return default

    def kv_set(self, key: str, value: Any, conn: sqlite3.Connection | None = None) -> None:
        sql = "INSERT INTO kv(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value"
        params = (key, json.dumps(value, ensure_ascii=False))
        if conn is not None:
            conn.execute(sql, params)
            return
        with self.tx() as c:
            c.execute(sql, params)
