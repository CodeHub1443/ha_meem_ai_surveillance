import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

DB_PATH = "logs/events.db"

STATUSES = {"pending", "enrolled"}


class PersonStore:
    """SQLite-backed store for enrolled and pending persons (gallery metadata).

    Shares the same DB file as EventStore. Uses thread-local connections with
    WAL mode so the API and pipeline can read concurrently.

    The pipeline's FAISS gallery (.npy file) is separate — this store holds
    only metadata (employee fields, enrollment status, thumbnail).
    Joins with the events table are done in the API layer, not here.
    """

    def __init__(self, db_path: str = DB_PATH):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._init_schema()

    # ── Connection ─────────────────────────────────────────────────────────────

    def _conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn"):
            conn = sqlite3.connect(str(self.db_path))
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            self._local.conn = conn
        return self._local.conn

    def _init_schema(self):
        conn = self._conn()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS persons (
                id           TEXT PRIMARY KEY,
                name         TEXT NOT NULL UNIQUE,
                employee_id  TEXT,
                designation  TEXT,
                working_area TEXT,
                status       TEXT NOT NULL DEFAULT 'pending',
                thumbnail_url TEXT,
                created_at   TEXT NOT NULL
            );
            CREATE UNIQUE INDEX IF NOT EXISTS idx_persons_name        ON persons(name);
            CREATE INDEX        IF NOT EXISTS idx_persons_status       ON persons(status);
            CREATE INDEX        IF NOT EXISTS idx_persons_employee_id  ON persons(employee_id);
        """)
        conn.commit()

    # ── Write ──────────────────────────────────────────────────────────────────

    def create(
        self,
        name: str,
        employee_id: Optional[str] = None,
        designation: Optional[str] = None,
        working_area: Optional[str] = None,
        thumbnail_url: Optional[str] = None,
    ) -> str:
        """Insert a new person with status='pending'. Returns the person id."""
        person_id = name.lower().replace(" ", "_")
        conn = self._conn()
        conn.execute(
            """INSERT INTO persons
               (id, name, employee_id, designation, working_area, status, thumbnail_url, created_at)
               VALUES (?, ?, ?, ?, ?, 'pending', ?, ?)""",
            (
                person_id,
                name,
                employee_id,
                designation,
                working_area,
                thumbnail_url,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        conn.commit()
        return person_id

    def update(
        self,
        person_id: str,
        employee_id: Optional[str] = None,
        designation: Optional[str] = None,
        working_area: Optional[str] = None,
        thumbnail_url: Optional[str] = None,
    ) -> bool:
        """Update mutable fields. Only non-None arguments are written. Returns True if found."""
        fields, params = [], []
        if employee_id is not None:
            fields.append("employee_id = ?"); params.append(employee_id)
        if designation is not None:
            fields.append("designation = ?"); params.append(designation)
        if working_area is not None:
            fields.append("working_area = ?"); params.append(working_area)
        if thumbnail_url is not None:
            fields.append("thumbnail_url = ?"); params.append(thumbnail_url)
        if not fields:
            return self.get(person_id) is not None
        params.append(person_id)
        conn = self._conn()
        cur = conn.execute(
            f"UPDATE persons SET {', '.join(fields)} WHERE id = ?", params
        )
        conn.commit()
        return cur.rowcount > 0

    def set_status(self, person_id: str, status: str) -> bool:
        """Set status to 'pending' or 'enrolled'. Returns True if person was found."""
        if status not in STATUSES:
            raise ValueError(f"status must be one of {STATUSES}, got {status!r}")
        conn = self._conn()
        cur = conn.execute(
            "UPDATE persons SET status = ? WHERE id = ?", (status, person_id)
        )
        conn.commit()
        return cur.rowcount > 0

    def enroll_all_pending(self) -> int:
        """Flip every pending person to enrolled. Returns the number transitioned."""
        conn = self._conn()
        cur = conn.execute(
            "UPDATE persons SET status = 'enrolled' WHERE status = 'pending'"
        )
        conn.commit()
        return cur.rowcount

    def enroll_by_ids(self, person_ids: set) -> int:
        """Enroll only the persons whose id is in person_ids (i.e. those actually built
        into the gallery). Persons created during the build that are not yet in the
        gallery remain pending. Returns the number transitioned."""
        if not person_ids:
            return 0
        conn = self._conn()
        cur = conn.executemany(
            "UPDATE persons SET status = 'enrolled' WHERE id = ? AND status = 'pending'",
            [(pid,) for pid in person_ids],
        )
        conn.commit()
        return cur.rowcount

    def set_thumbnail(self, person_id: str, thumbnail_url: str) -> bool:
        conn = self._conn()
        cur = conn.execute(
            "UPDATE persons SET thumbnail_url = ? WHERE id = ?", (thumbnail_url, person_id)
        )
        conn.commit()
        return cur.rowcount > 0

    def delete(self, person_id: str) -> bool:
        """Delete a person record. Returns True if found and deleted."""
        conn = self._conn()
        cur = conn.execute("DELETE FROM persons WHERE id = ?", (person_id,))
        conn.commit()
        return cur.rowcount > 0

    # ── Read ───────────────────────────────────────────────────────────────────

    def get(self, person_id: str) -> Optional[Dict]:
        row = self._conn().execute(
            "SELECT * FROM persons WHERE id = ?", (person_id,)
        ).fetchone()
        return dict(row) if row else None

    def get_by_name(self, name: str) -> Optional[Dict]:
        row = self._conn().execute(
            "SELECT * FROM persons WHERE name = ?", (name,)
        ).fetchone()
        return dict(row) if row else None

    def list(self, status: Optional[str] = None) -> List[Dict]:
        """Return persons, optionally filtered by status ('pending' or 'enrolled')."""
        if status:
            rows = self._conn().execute(
                "SELECT * FROM persons WHERE status = ? ORDER BY name COLLATE NOCASE",
                (status,),
            ).fetchall()
        else:
            rows = self._conn().execute(
                "SELECT * FROM persons ORDER BY name COLLATE NOCASE"
            ).fetchall()
        return [dict(r) for r in rows]

    def exists(self, person_id: str) -> bool:
        return self._conn().execute(
            "SELECT 1 FROM persons WHERE id = ?", (person_id,)
        ).fetchone() is not None