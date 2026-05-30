import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

DB_PATH = "logs/events.db"

# ROW_NUMBER() window functions require SQLite 3.25.0 (2018-09-15).
# Warn at import time so failures surface at startup, not on first API call.
_sqlite_ver = tuple(int(x) for x in sqlite3.sqlite_version.split("."))
if _sqlite_ver < (3, 25, 0):
    import warnings
    warnings.warn(
        f"SQLite {sqlite3.sqlite_version} is older than 3.25.0 — "
        "get_cluster_groups() will fall back to a Python-side sort.",
        RuntimeWarning,
        stacklevel=1,
    )


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
            conn = sqlite3.connect(str(self.db_path))
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            self._local.conn = conn
        return self._local.conn

    def _init_schema(self):
        conn = self._conn()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS schema_meta (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            INSERT OR IGNORE INTO schema_meta VALUES ('version', '1');

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
            CREATE INDEX IF NOT EXISTS idx_events_cam_ts   ON events(camera_id, timestamp);

            CREATE TABLE IF NOT EXISTS unknown_embeddings (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                track_id   INTEGER NOT NULL,
                camera_id  TEXT NOT NULL,
                timestamp  TEXT NOT NULL,
                snapshot   TEXT,
                embedding  BLOB NOT NULL,
                cluster_id INTEGER
            );
            CREATE INDEX IF NOT EXISTS idx_uemb_ts    ON unknown_embeddings(timestamp);
            CREATE INDEX IF NOT EXISTS idx_uemb_cam   ON unknown_embeddings(camera_id);
            CREATE INDEX IF NOT EXISTS idx_uemb_cid   ON unknown_embeddings(cluster_id);
            CREATE INDEX IF NOT EXISTS idx_uemb_track ON unknown_embeddings(track_id);

            CREATE TABLE IF NOT EXISTS cluster_meta (
                id           INTEGER PRIMARY KEY CHECK (id = 1),
                last_run_at  TEXT NOT NULL,
                n_embeddings INTEGER NOT NULL,
                n_clusters   INTEGER NOT NULL,
                n_noise      INTEGER NOT NULL
            );
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

    def insert_with_embedding(
        self,
        event: dict,
        embedding: np.ndarray,
    ) -> int:
        """Atomically insert an UNKNOWN event row and its embedding blob.

        Using a single ``with conn:`` transaction guarantees that a crash
        between the two writes never leaves an orphaned event row without an
        embedding — the whole pair is either committed or rolled back.

        Returns the new events row id.
        """
        blob = embedding.astype(np.float32).tobytes()
        conn = self._conn()
        with conn:
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
                    event.get("event"),
                    event.get("snapshot"),
                ),
            )
            conn.execute(
                """INSERT INTO unknown_embeddings
                   (track_id, camera_id, timestamp, snapshot, embedding)
                   VALUES (?, ?, ?, ?, ?)""",
                (
                    event.get("track_id"),
                    event.get("camera_id"),
                    event.get("timestamp"),
                    event.get("snapshot"),
                    blob,
                ),
            )
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

    # ── Unknown embeddings ─────────────────────────────────────────────────────

    def insert_unknown_embedding(
        self,
        track_id: int,
        camera_id: str,
        timestamp: str,
        embedding: np.ndarray,
        snapshot: Optional[str] = None,
    ) -> int:
        """Persist the aggregated face embedding for an UNKNOWN event."""
        blob = embedding.astype(np.float32).tobytes()
        conn = self._conn()
        cur = conn.execute(
            """INSERT INTO unknown_embeddings
               (track_id, camera_id, timestamp, snapshot, embedding)
               VALUES (?, ?, ?, ?, ?)""",
            (track_id, camera_id, timestamp, snapshot, blob),
        )
        conn.commit()
        return cur.lastrowid

    def get_all_unknown_embeddings(self, days: int = 90) -> List[Dict]:
        """Return embeddings within the rolling window (default 90 days).

        Caps the in-memory load fed to clustering — AgglomerativeClustering is
        O(n²) so unbounded growth makes it unusable. Older rows stay in the DB
        for audit purposes but are excluded from clustering runs.
        """
        rows = self._conn().execute(
            """SELECT id, track_id, camera_id, timestamp, embedding
               FROM unknown_embeddings
               WHERE timestamp >= datetime('now', ?)
               ORDER BY timestamp DESC""",
            (f"-{days} days",),
        ).fetchall()
        return [dict(r) for r in rows]

    def count_unknown_embeddings(self) -> int:
        return self._conn().execute("SELECT COUNT(*) FROM unknown_embeddings").fetchone()[0]

    def prune_clustered_embeddings(self) -> int:
        """Null-out embedding BLOBs for rows that already have a cluster label.

        Rows are kept for audit (track_id / camera_id / timestamps stay intact)
        but the 2 KB per-row BLOB is freed.  Safe to call after every clustering
        run.  Returns the number of rows updated.
        """
        conn = self._conn()
        cur = conn.execute(
            "UPDATE unknown_embeddings SET embedding = NULL WHERE cluster_id IS NOT NULL AND embedding IS NOT NULL"
        )
        conn.commit()
        return cur.rowcount

    def prune_old_unknown_embeddings(self, keep_days: int = 365) -> int:
        """Delete unknown_embedding rows older than *keep_days* days.

        Prevents unbounded table growth.  The default 365-day window keeps one
        year of history for audits while bounding O(n²) clustering cost.
        Returns the number of rows deleted.
        """
        conn = self._conn()
        cur = conn.execute(
            "DELETE FROM unknown_embeddings WHERE timestamp < datetime('now', ?)",
            (f"-{keep_days} days",),
        )
        conn.commit()
        return cur.rowcount

    # ── Cluster results ────────────────────────────────────────────────────────

    def update_cluster_results(
        self,
        updates: List[Tuple[int, int]],   # [(db_id, cluster_id), ...]
        n_embeddings: int,
        n_clusters: int,
        n_noise: int,
    ):
        """Write cluster labels back to unknown_embeddings and record run metadata."""
        conn = self._conn()
        conn.executemany(
            "UPDATE unknown_embeddings SET cluster_id = ? WHERE id = ?",
            [(label, db_id) for db_id, label in updates],
        )
        conn.execute(
            """INSERT OR REPLACE INTO cluster_meta
               (id, last_run_at, n_embeddings, n_clusters, n_noise)
               VALUES (1, ?, ?, ?, ?)""",
            (datetime.now(timezone.utc).isoformat(), n_embeddings, n_clusters, n_noise),
        )
        conn.commit()

    def get_cluster_meta(self) -> Optional[Dict]:
        """Return metadata from the most recent clustering run, or None."""
        row = self._conn().execute(
            "SELECT last_run_at, n_embeddings, n_clusters, n_noise FROM cluster_meta WHERE id = 1"
        ).fetchone()
        return dict(row) if row else None

    def get_cluster_groups(self, max_snapshots: int = 4) -> dict:
        """Return clusters and singletons with sample snapshots for visual verification.

        Returns:
          {
            "clusters":   [ {cluster_id, track_count, first_seen, last_seen,
                             cameras, snapshots}, ... ],   # label >= 0, sorted by size desc
            "singletons": [ {track_id, first_seen, camera_id, snapshot}, ... ],
          }
        """
        conn = self._conn()

        # ── Named clusters (cluster_id >= 0) ──────────────────────────────────
        cluster_rows = conn.execute("""
            SELECT cluster_id,
                   COUNT(DISTINCT track_id) AS track_count,
                   MIN(timestamp)           AS first_seen,
                   MAX(timestamp)           AS last_seen,
                   GROUP_CONCAT(DISTINCT camera_id) AS cameras
            FROM   unknown_embeddings
            WHERE  cluster_id >= 0
            GROUP  BY cluster_id
            ORDER  BY track_count DESC, cluster_id
        """).fetchall()

        # Up to max_snapshots non-null snapshots per cluster (most recent first).
        # ROW_NUMBER() requires SQLite ≥ 3.25.0.  Fall back to a Python-side
        # grouping pass on older versions (e.g. system SQLite on some Linuxes).
        if _sqlite_ver >= (3, 25, 0):
            snap_rows = conn.execute("""
                WITH ranked AS (
                    SELECT cluster_id, snapshot,
                           ROW_NUMBER() OVER (
                               PARTITION BY cluster_id
                               ORDER BY timestamp DESC
                           ) AS rn
                    FROM unknown_embeddings
                    WHERE cluster_id >= 0 AND snapshot IS NOT NULL
                )
                SELECT cluster_id, snapshot FROM ranked WHERE rn <= ?
            """, (max_snapshots,)).fetchall()
        else:
            # Fallback: fetch all snapshots, truncate in Python.
            all_snaps = conn.execute("""
                SELECT cluster_id, snapshot
                FROM unknown_embeddings
                WHERE cluster_id >= 0 AND snapshot IS NOT NULL
                ORDER BY timestamp DESC
            """).fetchall()
            seen: Dict[int, int] = {}
            snap_rows = []
            for r in all_snaps:
                cid = r["cluster_id"]
                seen[cid] = seen.get(cid, 0) + 1
                if seen[cid] <= max_snapshots:
                    snap_rows.append(r)

        snap_map: Dict[int, List[str]] = {}
        for r in snap_rows:
            snap_map.setdefault(r["cluster_id"], []).append(r["snapshot"])

        clusters = [
            {
                "cluster_id":  r["cluster_id"],
                "track_count": r["track_count"],
                "first_seen":  r["first_seen"],
                "last_seen":   r["last_seen"],
                "cameras":     r["cameras"].split(",") if r["cameras"] else [],
                "snapshots":   snap_map.get(r["cluster_id"], []),
            }
            for r in cluster_rows
        ]

        # ── Singletons (cluster_id == -1, one entry per track_id) ─────────────
        singleton_rows = conn.execute("""
            SELECT track_id,
                   MIN(timestamp) AS first_seen,
                   camera_id,
                   MAX(snapshot)  AS snapshot
            FROM   unknown_embeddings
            WHERE  cluster_id = -1
            GROUP  BY track_id
            ORDER  BY first_seen DESC
        """).fetchall()

        singletons = [
            {
                "track_id":  r["track_id"],
                "first_seen": r["first_seen"],
                "camera_id": r["camera_id"],
                "snapshot":  r["snapshot"],
            }
            for r in singleton_rows
        ]

        return {"clusters": clusters, "singletons": singletons}

    def count_unique_unauthorized(
        self,
        camera_id: Optional[str] = None,
        since: Optional[str] = None,
        until: Optional[str] = None,
    ) -> Optional[int]:
        """Count unique unauthorized persons from the last clustering run.

        A unique person = one HDBSCAN cluster (≥2 track appearances) OR one
        singleton track (noise, label=-1, appeared exactly once).
        Returns None if clustering has never been run.
        """
        if self.get_cluster_meta() is None:
            return None

        clauses: List[str] = ["cluster_id IS NOT NULL"]
        params: List = []
        if camera_id:
            clauses.append("camera_id = ?")
            params.append(camera_id)
        if since:
            clauses.append("timestamp >= ?")
            params.append(since)
        if until:
            clauses.append("timestamp <= ?")
            params.append(until)
        where = "WHERE " + " AND ".join(clauses)

        # Single query avoids a TOCTOU race between two separate counts.
        # Clusters contribute one unit per distinct cluster_id (≥ 0);
        # singletons contribute one unit per distinct track_id (cluster_id = -1).
        sql = f"""
            SELECT
                COUNT(DISTINCT CASE WHEN cluster_id >= 0 THEN cluster_id  END) +
                COUNT(DISTINCT CASE WHEN cluster_id =  -1 THEN track_id    END)
            FROM unknown_embeddings
            {where}
        """
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