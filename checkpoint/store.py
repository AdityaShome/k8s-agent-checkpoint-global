import json
import sqlite3
import datetime
import warnings
from typing import Any, Optional
from .models import StepRecord, StepStatus


class SQLiteStore:
    def __init__(self, path: str):
        self.path = path
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._init_schema()

    def _init_schema(self):
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS steps (
                run_id TEXT NOT NULL,
                step TEXT NOT NULL,
                status TEXT NOT NULL,
                result TEXT,
                error TEXT,
                started_at TIMESTAMP,
                completed_at TIMESTAMP,
                duration_ms REAL,
                PRIMARY KEY (run_id, step)
            );

            CREATE TABLE IF NOT EXISTS runs (
                run_id TEXT PRIMARY KEY,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                metadata TEXT
            );
        """)
        self._conn.commit()

    def _ensure_run(self, run_id: str):
        self._conn.execute(
            "INSERT OR IGNORE INTO runs (run_id, created_at) VALUES (?, ?)",
            (run_id, datetime.datetime.utcnow()),
        )
        self._conn.commit()

    @staticmethod
    def _serialize(result: Any) -> str:
        try:
            return json.dumps(result)
        except (TypeError, ValueError):
            warnings.warn(
                f"Result is not JSON-serializable; falling back to str(). "
                f"Type: {type(result).__name__}",
                stacklevel=3,
            )
            return json.dumps(str(result))

    @staticmethod
    def _deserialize(raw: Optional[str]) -> Any:
        if raw is None:
            return None
        return json.loads(raw)

    def is_done(self, run_id: str, step: str) -> bool:
        cur = self._conn.execute(
            "SELECT status FROM steps WHERE run_id=? AND step=?",
            (run_id, step),
        )
        row = cur.fetchone()
        return row is not None and row[0] == StepStatus.DONE.value

    def get_result(self, run_id: str, step: str) -> Any:
        cur = self._conn.execute(
            "SELECT result FROM steps WHERE run_id=? AND step=?",
            (run_id, step),
        )
        row = cur.fetchone()
        if row is None:
            return None
        return self._deserialize(row[0])

    def mark_running(self, run_id: str, step: str):
        self._ensure_run(run_id)
        now = datetime.datetime.utcnow()
        self._conn.execute(
            """INSERT INTO steps (run_id, step, status, started_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(run_id, step) DO UPDATE SET
                   status=excluded.status,
                   started_at=excluded.started_at,
                   completed_at=NULL,
                   result=NULL,
                   error=NULL,
                   duration_ms=NULL""",
            (run_id, step, StepStatus.RUNNING.value, now),
        )
        self._conn.commit()

    def mark_done(self, run_id: str, step: str, result: Any):
        now = datetime.datetime.utcnow()
        serialized = self._serialize(result)
        self._conn.execute(
            """UPDATE steps SET
                   status=?,
                   result=?,
                   completed_at=?,
                   duration_ms=(
                       CASE WHEN started_at IS NOT NULL
                       THEN (julianday(?) - julianday(started_at)) * 86400000
                       ELSE NULL END
                   )
               WHERE run_id=? AND step=?""",
            (StepStatus.DONE.value, serialized, now, now, run_id, step),
        )
        self._conn.commit()

    def mark_failed(self, run_id: str, step: str, error: str):
        now = datetime.datetime.utcnow()
        self._conn.execute(
            """UPDATE steps SET
                   status=?,
                   error=?,
                   completed_at=?
               WHERE run_id=? AND step=?""",
            (StepStatus.FAILED.value, error, now, run_id, step),
        )
        self._conn.commit()

    def get_run_summary(self, run_id: str) -> dict:
        cur = self._conn.execute(
            """SELECT
                   SUM(CASE WHEN status='done' THEN 1 ELSE 0 END) AS completed,
                   SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) AS failed,
                   SUM(CASE WHEN status='running' THEN 1 ELSE 0 END) AS running,
                   COUNT(*) AS total
               FROM steps WHERE run_id=?""",
            (run_id,),
        )
        row = cur.fetchone()
        if row is None or row[3] == 0:
            return {"completed": 0, "failed": 0, "running": 0, "total": 0}
        return {
            "completed": row[0] or 0,
            "failed": row[1] or 0,
            "running": row[2] or 0,
            "total": row[3] or 0,
        }

    def list_completed_steps(self, run_id: str) -> list[str]:
        cur = self._conn.execute(
            "SELECT step FROM steps WHERE run_id=? AND status='done' ORDER BY rowid",
            (run_id,),
        )
        return [row[0] for row in cur.fetchall()]

    def clear_run(self, run_id: str):
        self._conn.execute("DELETE FROM steps WHERE run_id=?", (run_id,))
        self._conn.execute("DELETE FROM runs WHERE run_id=?", (run_id,))
        self._conn.commit()

    def close(self):
        self._conn.close()


class PostgreSQLStore:
    def __init__(self, dsn: str):
        try:
            import psycopg2
            import psycopg2.extras
        except ImportError:
            raise ImportError(
                "psycopg2 is required for PostgreSQL support. "
                "Install it with: pip install agent-checkpoint[postgres]"
            )
        self._psycopg2 = psycopg2
        self._conn = psycopg2.connect(dsn)
        self._conn.autocommit = False
        self._init_schema()

    def _init_schema(self):
        with self._conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS steps (
                    run_id TEXT NOT NULL,
                    step TEXT NOT NULL,
                    status TEXT NOT NULL,
                    result TEXT,
                    error TEXT,
                    started_at TIMESTAMP,
                    completed_at TIMESTAMP,
                    duration_ms REAL,
                    PRIMARY KEY (run_id, step)
                );

                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY,
                    created_at TIMESTAMP DEFAULT NOW(),
                    metadata TEXT
                );
            """)
        self._conn.commit()

    def _ensure_run(self, run_id: str):
        with self._conn.cursor() as cur:
            cur.execute(
                "INSERT INTO runs (run_id, created_at) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                (run_id, datetime.datetime.utcnow()),
            )
        self._conn.commit()

    @staticmethod
    def _serialize(result: Any) -> str:
        try:
            return json.dumps(result)
        except (TypeError, ValueError):
            warnings.warn(
                f"Result is not JSON-serializable; falling back to str(). "
                f"Type: {type(result).__name__}",
                stacklevel=3,
            )
            return json.dumps(str(result))

    @staticmethod
    def _deserialize(raw: Optional[str]) -> Any:
        if raw is None:
            return None
        return json.loads(raw)

    def is_done(self, run_id: str, step: str) -> bool:
        with self._conn.cursor() as cur:
            cur.execute(
                "SELECT status FROM steps WHERE run_id=%s AND step=%s",
                (run_id, step),
            )
            row = cur.fetchone()
        return row is not None and row[0] == StepStatus.DONE.value

    def get_result(self, run_id: str, step: str) -> Any:
        with self._conn.cursor() as cur:
            cur.execute(
                "SELECT result FROM steps WHERE run_id=%s AND step=%s",
                (run_id, step),
            )
            row = cur.fetchone()
        return self._deserialize(row[0]) if row else None

    def mark_running(self, run_id: str, step: str):
        self._ensure_run(run_id)
        now = datetime.datetime.utcnow()
        with self._conn.cursor() as cur:
            cur.execute(
                """INSERT INTO steps (run_id, step, status, started_at)
                   VALUES (%s, %s, %s, %s)
                   ON CONFLICT (run_id, step) DO UPDATE SET
                       status=EXCLUDED.status,
                       started_at=EXCLUDED.started_at,
                       completed_at=NULL,
                       result=NULL,
                       error=NULL,
                       duration_ms=NULL""",
                (run_id, step, StepStatus.RUNNING.value, now),
            )
        self._conn.commit()

    def mark_done(self, run_id: str, step: str, result: Any):
        now = datetime.datetime.utcnow()
        serialized = self._serialize(result)
        with self._conn.cursor() as cur:
            cur.execute(
                """UPDATE steps SET
                       status=%s,
                       result=%s,
                       completed_at=%s,
                       duration_ms=CASE WHEN started_at IS NOT NULL
                           THEN EXTRACT(EPOCH FROM (%s - started_at)) * 1000
                           ELSE NULL END
                   WHERE run_id=%s AND step=%s""",
                (StepStatus.DONE.value, serialized, now, now, run_id, step),
            )
        self._conn.commit()

    def mark_failed(self, run_id: str, step: str, error: str):
        now = datetime.datetime.utcnow()
        with self._conn.cursor() as cur:
            cur.execute(
                """UPDATE steps SET status=%s, error=%s, completed_at=%s
                   WHERE run_id=%s AND step=%s""",
                (StepStatus.FAILED.value, error, now, run_id, step),
            )
        self._conn.commit()

    def get_run_summary(self, run_id: str) -> dict:
        with self._conn.cursor() as cur:
            cur.execute(
                """SELECT
                       SUM(CASE WHEN status='done' THEN 1 ELSE 0 END),
                       SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END),
                       SUM(CASE WHEN status='running' THEN 1 ELSE 0 END),
                       COUNT(*)
                   FROM steps WHERE run_id=%s""",
                (run_id,),
            )
            row = cur.fetchone()
        if row is None or row[3] == 0:
            return {"completed": 0, "failed": 0, "running": 0, "total": 0}
        return {
            "completed": int(row[0] or 0),
            "failed": int(row[1] or 0),
            "running": int(row[2] or 0),
            "total": int(row[3] or 0),
        }

    def list_completed_steps(self, run_id: str) -> list[str]:
        with self._conn.cursor() as cur:
            cur.execute(
                "SELECT step FROM steps WHERE run_id=%s AND status='done' ORDER BY started_at",
                (run_id,),
            )
            return [row[0] for row in cur.fetchall()]

    def clear_run(self, run_id: str):
        with self._conn.cursor() as cur:
            cur.execute("DELETE FROM steps WHERE run_id=%s", (run_id,))
            cur.execute("DELETE FROM runs WHERE run_id=%s", (run_id,))
        self._conn.commit()

    def close(self):
        self._conn.close()


class CheckpointStore:
    """
    Public entry point. Selects backend based on URL scheme:
      sqlite:///path/to/file.db
      postgresql://user:pass@host/db
    """

    def __init__(self, url: str):
        if url.startswith("sqlite:///"):
            path = url[len("sqlite:///"):]
            self._backend = SQLiteStore(path)
        elif url.startswith("postgresql://") or url.startswith("postgres://"):
            self._backend = PostgreSQLStore(url)
        else:
            raise ValueError(
                f"Unsupported database URL scheme. "
                f"Use 'sqlite:///path' or 'postgresql://...' Got: {url!r}"
            )

    def is_done(self, run_id: str, step: str) -> bool:
        return self._backend.is_done(run_id, step)

    def get_result(self, run_id: str, step: str) -> Any:
        return self._backend.get_result(run_id, step)

    def mark_running(self, run_id: str, step: str):
        self._backend.mark_running(run_id, step)

    def mark_done(self, run_id: str, step: str, result: Any):
        self._backend.mark_done(run_id, step, result)

    def mark_failed(self, run_id: str, step: str, error: str):
        self._backend.mark_failed(run_id, step, error)

    def get_run_summary(self, run_id: str) -> dict:
        return self._backend.get_run_summary(run_id)

    def list_completed_steps(self, run_id: str) -> list[str]:
        return self._backend.list_completed_steps(run_id)

    def clear_run(self, run_id: str):
        self._backend.clear_run(run_id)

    def close(self):
        self._backend.close()
