import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from .filesystem import exists, fingerprint, state_directory
from .models import HistoryError

SCHEMA_VERSION = 1
SCHEMA = """
BEGIN;
CREATE TABLE runs (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL
);
CREATE TABLE moves (
    id INTEGER PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(id),
    source TEXT NOT NULL,
    target TEXT NOT NULL,
    checksum TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('pending', 'moved', 'undo_pending', 'undone', 'failed'))
);
CREATE INDEX moves_run ON moves(run_id);
PRAGMA user_version = 1;
COMMIT;
"""


def has_history(root: Path) -> bool:
    directory = state_directory(root)
    return exists(directory / "history.sqlite3")


class History:
    def __init__(self, root: Path):
        self.root = root
        self.connection: sqlite3.Connection | None = None
        self.lock: sqlite3.Connection | None = None

    def __enter__(self) -> "History":
        try:
            directory = state_directory(self.root, create=True)
            for filename in ("lock.sqlite3", "history.sqlite3", "history.sqlite3-journal"):
                path = directory / filename
                if exists(path):
                    fingerprint(path)
            self.lock = sqlite3.connect(directory / "lock.sqlite3", timeout=0, isolation_level=None)
            try:
                self.lock.execute("BEGIN EXCLUSIVE")
            except sqlite3.OperationalError as error:
                if error.sqlite_errorcode in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED):
                    raise HistoryError("Эта папка уже обрабатывается другим процессом. Повторите позже.") from error
                raise
            self.connection = sqlite3.connect(directory / "history.sqlite3", isolation_level=None)
            self.connection.row_factory = sqlite3.Row
            self.connection.execute("PRAGMA foreign_keys = ON")
            if self.connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise HistoryError("История повреждена. Файлы не перемещались.")
            version = self.connection.execute("PRAGMA user_version").fetchone()[0]
            tables = self.connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
            if version == 0 and not tables:
                self.connection.executescript(SCHEMA)
            elif version != SCHEMA_VERSION:
                raise HistoryError(f"Неподдерживаемая версия истории: {version}.")
            self.connection.execute("SELECT id, created_at FROM runs LIMIT 0")
            self.connection.execute("SELECT id, run_id, source, target, checksum, status FROM moves LIMIT 0")
            return self
        except (OSError, sqlite3.Error, HistoryError):
            self.close()
            raise

    def __exit__(self, exception_type, exception, traceback) -> None:
        self.close()

    def close(self) -> None:
        if self.connection is not None:
            self.connection.close()
            self.connection = None
        if self.lock is not None:
            self.lock.close()
            self.lock = None

    def database(self) -> sqlite3.Connection:
        if self.connection is None:
            raise HistoryError("История не открыта.")
        return self.connection

    def create_run(self) -> str:
        run_id = uuid4().hex
        self.database().execute(
            "INSERT INTO runs(id, created_at) VALUES (?, ?)",
            (run_id, datetime.now(UTC).isoformat(timespec="seconds")),
        )
        return run_id

    def add_move(self, run_id: str, source: Path, target: Path, checksum: str) -> sqlite3.Row:
        cursor = self.database().execute(
            "INSERT INTO moves(run_id, source, target, checksum, status) VALUES (?, ?, ?, ?, 'pending')",
            (run_id, source.relative_to(self.root).as_posix(), target.relative_to(self.root).as_posix(), checksum),
        )
        return self.database().execute("SELECT * FROM moves WHERE id = ?", (cursor.lastrowid,)).fetchone()

    def set_status(self, move_id: int, status: str) -> None:
        self.database().execute("UPDATE moves SET status = ? WHERE id = ?", (status, move_id))

    def move_status(self, move_id: int) -> str:
        record = self.database().execute("SELECT status FROM moves WHERE id = ?", (move_id,)).fetchone()
        if record is None:
            raise HistoryError(f"В истории отсутствует перемещение {move_id}.")
        return record["status"]

    def pending_moves(self) -> list[sqlite3.Row]:
        return self.database().execute(
            "SELECT * FROM moves WHERE status IN ('pending', 'undo_pending') ORDER BY id"
        ).fetchall()

    def latest_moves(self) -> list[sqlite3.Row]:
        return self.database().execute(
            """
            SELECT * FROM moves WHERE status = 'moved' AND run_id = (
                SELECT runs.id FROM runs JOIN moves ON moves.run_id = runs.id
                WHERE moves.status = 'moved' ORDER BY runs.rowid DESC LIMIT 1
            ) ORDER BY id DESC
            """
        ).fetchall()

    def summaries(self, limit: int) -> list[sqlite3.Row]:
        return self.database().execute(
            """
            SELECT runs.id, runs.created_at, COUNT(moves.id) AS total,
                SUM(moves.status = 'moved') AS moved,
                SUM(moves.status = 'undone') AS undone,
                SUM(moves.status IN ('pending', 'undo_pending')) AS pending,
                SUM(moves.status = 'failed') AS failed
            FROM runs LEFT JOIN moves ON moves.run_id = runs.id
            GROUP BY runs.id ORDER BY runs.rowid DESC LIMIT ?
            """,
            (limit,),
        ).fetchall()
