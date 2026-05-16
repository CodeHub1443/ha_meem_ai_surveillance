import sqlite3
import threading
from pathlib import Path
from typing import Dict, List, Optional

DB_PATH = "logs/events.db"


class EventStore:
    """SQLite-backed persistent store for detection events.

    Thread-safe via thread-local connections. WAL mode allows concurrent
    readers (API server) and the writer (pipeline) across separate processes
    sharing the same DB file.
    """

    def __init__(self, db_path: str = DB_PATH):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._init_schema()

    # ── Connection management ──────────────────────────────────────────────────

    def _conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn"):
            conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            self._local.conn = conn
        return self._local.conn

    def _init_schema(self):
        conn = self._conn()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS events (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp  TEXT NOT NULL,
                camera_id  TEXT NOT NULL,
                track_id   INTEGER,
                identity   TEXT,
                score      REAL,
                event_type TEXT NOT NULL,
                snapshot   TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_events_camera   ON events(camera_id);
            CREATE INDEX IF NOT EXISTS idx_events_identity ON events(identity);
            CREATE INDEX IF NOT EXISTS idx_events_ts       ON events(timestamp);
        """)
        conn.commit()

    # ── Write ──────────────────────────────────────────────────────────────────

    def insert(self, event: dict) -> int:
        """Insert a detection event. Returns the new row id."""
        conn = self._conn()
        cur = conn.execute(
            """INSERT INTO events
               (timestamp, camera_id, track_id, identity, score, event_type, snapshot)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                event.get("timestamp"),
                event.get("camera_id"),
                event.get("track_id"),
                event.get("identity"),
                event.get("score"),
                event.get("event"),       # pipeline field name is "event"
                event.get("snapshot"),
            ),
        )
        conn.commit()
        return cur.lastrowid

    # ── Read ───────────────────────────────────────────────────────────────────

    def query(
        self,
        camera_id: Optional[str] = None,
        identity: Optional[str] = None,
        event_type: Optional[str] = None,
        since: Optional[str] = None,
        until: Optional[str] = None,
        limit: int = 500,
        offset: int = 0,
    ) -> List[Dict]:
        """Return events newest-first matching the given filters."""
        clauses, params = self._build_clauses(camera_id, identity, event_type, since, until)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        params.extend([limit, offset])
        sql = f"""
            SELECT timestamp, camera_id, track_id, identity, score,
                   event_type AS event, snapshot
            FROM events
            {where}
            ORDER BY timestamp DESC
            LIMIT ? OFFSET ?
        """
        rows = self._conn().execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def count(
        self,
        camera_id: Optional[str] = None,
        identity: Optional[str] = None,
        event_type: Optional[str] = None,
        since: Optional[str] = None,
        until: Optional[str] = None,
    ) -> int:
        """Row count matching the given filters."""
        clauses, params = self._build_clauses(camera_id, identity, event_type, since, until)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        return self._conn().execute(f"SELECT COUNT(*) FROM events {where}", params).fetchone()[0]

    def count_unique_identities(
        self,
        camera_id: Optional[str] = None,
        since: Optional[str] = None,
        until: Optional[str] = None,
    ) -> int:
        """Count distinct non-null identities matching the given filters."""
        clauses, params = self._build_clauses(camera_id, None, "AUTHORIZED", since, until)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        sql = f"SELECT COUNT(DISTINCT identity) FROM events {where}"
        return self._conn().execute(sql, params).fetchone()[0]

    # ── Internal ───────────────────────────────────────────────────────────────

    @staticmethod
    def _build_clauses(
        camera_id: Optional[str],
        identity: Optional[str],
        event_type: Optional[str],
        since: Optional[str],
        until: Optional[str],
    ):
        clauses: List[str] = []
        params: List = []
        if camera_id:
            clauses.append("camera_id = ?")
            params.append(camera_id)
        if identity:
            clauses.append("identity LIKE ?")
            params.append(f"%{identity}%")
        if event_type:
            clauses.append("event_type = ?")
            params.append(event_type.upper())
        if since:
            clauses.append("timestamp >= ?")
            params.append(since)
        if until:
            clauses.append("timestamp <= ?")
            params.append(until)
        return clauses, params