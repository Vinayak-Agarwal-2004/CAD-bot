"""
SQLite storage for models, rendered videos, scheduled posts and metrics.
"""
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional

SCHEMA_VERSION = 2

SCHEMA = '''
CREATE TABLE IF NOT EXISTS models (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filepath TEXT UNIQUE NOT NULL,          -- full path, so same-named files never collide
    filename TEXT NOT NULL,
    sha256 TEXT,                            -- identical meshes are rendered once
    file_size INTEGER,
    added_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    stats TEXT,                             -- JSON from content.model_analyzer
    score REAL,                             -- visual interest score, higher first
    status TEXT DEFAULT 'pending',          -- pending|rejected|rendered|failed|duplicate
    attempts INTEGER DEFAULT 0,
    last_error TEXT
);
CREATE INDEX IF NOT EXISTS idx_models_sha ON models(sha256);

CREATE TABLE IF NOT EXISTS videos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    model_id INTEGER NOT NULL REFERENCES models(id),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    variant TEXT NOT NULL,                  -- JSON: format, hook, palette, material...
    metadata TEXT,                          -- JSON: per-platform titles/captions
    video_path TEXT,
    cover_path TEXT,
    render_seconds REAL,
    status TEXT DEFAULT 'rendering',        -- rendering|ready|failed
    error_message TEXT
);

CREATE TABLE IF NOT EXISTS posts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id INTEGER NOT NULL REFERENCES videos(id),
    platform TEXT NOT NULL,
    scheduled_at TIMESTAMP NOT NULL,        -- UTC
    status TEXT DEFAULT 'scheduled',        -- scheduled|posted|draft|failed|exported
    remote_id TEXT,
    url TEXT,
    posted_at TIMESTAMP,
    attempts INTEGER DEFAULT 0,
    error_message TEXT,
    UNIQUE(video_id, platform)
);

CREATE TABLE IF NOT EXISTS metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id INTEGER NOT NULL REFERENCES posts(id),
    collected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    views INTEGER, likes INTEGER, comments INTEGER, shares INTEGER, saves INTEGER,
    raw TEXT
);

CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
'''


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _ts(value: datetime) -> str:
    return value.strftime('%Y-%m-%d %H:%M:%S')


class DatabaseManager:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.init_database()

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA foreign_keys = ON')
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def init_database(self):
        with self.connect() as conn:
            conn.executescript(SCHEMA)
            conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES ('schema_version', ?)",
                         (str(SCHEMA_VERSION),))

    # ------------------------------------------------------------ models
    def add_model(self, filepath: Path, sha256: Optional[str] = None) -> int:
        filepath = Path(filepath).resolve()
        with self.connect() as conn:
            conn.execute(
                'INSERT OR IGNORE INTO models (filepath, filename, sha256, file_size) VALUES (?, ?, ?, ?)',
                (str(filepath), filepath.name, sha256, filepath.stat().st_size))
            row = conn.execute('SELECT id FROM models WHERE filepath = ?', (str(filepath),)).fetchone()
            if sha256:
                conn.execute('UPDATE models SET sha256 = ? WHERE id = ? AND sha256 IS NULL', (sha256, row['id']))
            return row['id']

    def get_model(self, model_id: int) -> Optional[Dict]:
        with self.connect() as conn:
            row = conn.execute('SELECT * FROM models WHERE id = ?', (model_id,)).fetchone()
        return self._model_row(row) if row else None

    def get_model_by_path(self, filepath: Path) -> Optional[Dict]:
        with self.connect() as conn:
            row = conn.execute('SELECT * FROM models WHERE filepath = ?',
                               (str(Path(filepath).resolve()),)).fetchone()
        return self._model_row(row) if row else None

    def find_duplicate(self, model_id: int, sha256: str) -> Optional[int]:
        """Return the id of an earlier model with identical content, if any."""
        with self.connect() as conn:
            row = conn.execute('SELECT id FROM models WHERE sha256 = ? AND id < ? ORDER BY id LIMIT 1',
                               (sha256, model_id)).fetchone()
        return row['id'] if row else None

    def set_model_analysis(self, model_id: int, stats: Dict, score: float, status: str):
        with self.connect() as conn:
            conn.execute('UPDATE models SET stats = ?, score = ?, status = ? WHERE id = ?',
                         (json.dumps(stats), score, status, model_id))

    def set_model_status(self, model_id: int, status: str, error: Optional[str] = None,
                         count_attempt: bool = False):
        with self.connect() as conn:
            conn.execute(
                'UPDATE models SET status = ?, last_error = ?, attempts = attempts + ? WHERE id = ?',
                (status, error, 1 if count_attempt else 0, model_id))

    def get_models(self, status: Optional[str] = None) -> List[Dict]:
        query, args = 'SELECT * FROM models', ()
        if status:
            query, args = query + ' WHERE status = ?', (status,)
        with self.connect() as conn:
            return [self._model_row(r) for r in conn.execute(query, args)]

    def get_render_queue(self, limit: Optional[int] = None, max_attempts: int = 2) -> List[Dict]:
        """Analysed models that have never been rendered, most interesting first.
        Failed models are retried until they reach max_attempts."""
        query = '''
            SELECT * FROM models
            WHERE (status = 'pending' AND stats IS NOT NULL)
               OR (status = 'failed' AND attempts < ?)
            ORDER BY score DESC, id ASC
        '''
        args: tuple = (max_attempts,)
        if limit:
            query += ' LIMIT ?'
            args += (int(limit),)
        with self.connect() as conn:
            return [self._model_row(r) for r in conn.execute(query, args)]

    @staticmethod
    def _model_row(row) -> Dict:
        data = dict(row)
        data['stats'] = json.loads(data['stats']) if data.get('stats') else None
        return data

    # ------------------------------------------------------------ videos
    def create_video(self, model_id: int, variant: Dict) -> int:
        with self.connect() as conn:
            cur = conn.execute('INSERT INTO videos (model_id, variant) VALUES (?, ?)',
                               (model_id, json.dumps(variant, sort_keys=True)))
            return cur.lastrowid

    def update_video_variant(self, video_id: int, variant: Dict):
        with self.connect() as conn:
            conn.execute('UPDATE videos SET variant = ? WHERE id = ?',
                         (json.dumps(variant, sort_keys=True), video_id))

    def finish_video(self, video_id: int, video_path: Path, cover_path: Optional[Path],
                     metadata: Dict, render_seconds: float):
        with self.connect() as conn:
            conn.execute('''UPDATE videos SET status = 'ready', video_path = ?, cover_path = ?,
                            metadata = ?, render_seconds = ?, error_message = NULL WHERE id = ?''',
                         (str(video_path), str(cover_path) if cover_path else None,
                          json.dumps(metadata), render_seconds, video_id))

    def fail_video(self, video_id: int, error: str):
        with self.connect() as conn:
            conn.execute("UPDATE videos SET status = 'failed', error_message = ? WHERE id = ?",
                         (error[:4000], video_id))

    def fail_stale_videos(self, older_than_seconds: int) -> int:
        """Mark videos left in 'rendering' by a killed process as failed."""
        cutoff = _ts(utcnow() - timedelta(seconds=older_than_seconds))
        with self.connect() as conn:
            cur = conn.execute("UPDATE videos SET status = 'failed', error_message = 'interrupted' "
                               "WHERE status = 'rendering' AND created_at < ?", (cutoff,))
            return cur.rowcount

    def get_video(self, video_id: int) -> Optional[Dict]:
        with self.connect() as conn:
            row = conn.execute('SELECT * FROM videos WHERE id = ?', (video_id,)).fetchone()
        return self._video_row(row) if row else None

    def get_videos(self, status: Optional[str] = None, unscheduled_for: Optional[str] = None) -> List[Dict]:
        query, args = 'SELECT v.* FROM videos v WHERE 1=1', []
        if status:
            query += ' AND v.status = ?'
            args.append(status)
        if unscheduled_for:
            query += ' AND NOT EXISTS (SELECT 1 FROM posts p WHERE p.video_id = v.id AND p.platform = ?)'
            args.append(unscheduled_for)
        query += ' ORDER BY v.id'
        with self.connect() as conn:
            return [self._video_row(r) for r in conn.execute(query, args)]

    def count_videos(self) -> int:
        with self.connect() as conn:
            return conn.execute('SELECT COUNT(*) FROM videos').fetchone()[0]

    @staticmethod
    def _video_row(row) -> Dict:
        data = dict(row)
        data['variant'] = json.loads(data['variant']) if data.get('variant') else {}
        data['metadata'] = json.loads(data['metadata']) if data.get('metadata') else {}
        return data

    # ------------------------------------------------------------ posts
    def schedule_post(self, video_id: int, platform: str, when_utc: datetime) -> Optional[int]:
        with self.connect() as conn:
            cur = conn.execute(
                'INSERT OR IGNORE INTO posts (video_id, platform, scheduled_at) VALUES (?, ?, ?)',
                (video_id, platform, _ts(when_utc)))
            return cur.lastrowid if cur.rowcount else None

    def get_scheduled_times(self, platform: str, since_utc: datetime) -> List[datetime]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT scheduled_at FROM posts WHERE platform = ? AND scheduled_at >= ? AND status != 'failed'",
                (platform, _ts(since_utc))).fetchall()
        return [datetime.strptime(r[0], '%Y-%m-%d %H:%M:%S') for r in rows]

    def get_due_posts(self, now_utc: Optional[datetime] = None, max_attempts: int = 3) -> List[Dict]:
        now_utc = now_utc or utcnow()
        with self.connect() as conn:
            rows = conn.execute('''
                SELECT * FROM posts
                WHERE scheduled_at <= ? AND (status = 'scheduled' OR (status = 'failed' AND attempts < ?))
                ORDER BY scheduled_at''', (_ts(now_utc), max_attempts)).fetchall()
        return [dict(r) for r in rows]

    def mark_post(self, post_id: int, status: str, remote_id: Optional[str] = None,
                  url: Optional[str] = None, error: Optional[str] = None):
        with self.connect() as conn:
            conn.execute('''
                UPDATE posts SET status = ?, remote_id = COALESCE(?, remote_id), url = COALESCE(?, url),
                    error_message = ?, attempts = attempts + 1,
                    posted_at = CASE WHEN ? IN ('posted', 'draft') THEN ? ELSE posted_at END
                WHERE id = ?''',
                (status, remote_id, url, error, status, _ts(utcnow()), post_id))

    def get_posts(self, platform: Optional[str] = None, statuses: Iterable[str] = ('posted',)) -> List[Dict]:
        statuses = list(statuses)
        query = f"SELECT * FROM posts WHERE status IN ({','.join('?' * len(statuses))})"
        args = list(statuses)
        if platform:
            query += ' AND platform = ?'
            args.append(platform)
        with self.connect() as conn:
            return [dict(r) for r in conn.execute(query, args)]

    # ------------------------------------------------------------ metrics
    def add_metrics(self, post_id: int, views=None, likes=None, comments=None,
                    shares=None, saves=None, raw: Optional[Dict] = None):
        with self.connect() as conn:
            conn.execute('''INSERT INTO metrics (post_id, views, likes, comments, shares, saves, raw)
                            VALUES (?, ?, ?, ?, ?, ?, ?)''',
                         (post_id, views, likes, comments, shares, saves, json.dumps(raw or {})))

    def get_performance_rows(self, min_age_hours: int = 48) -> List[Dict]:
        """Latest metrics per post that is old enough to judge, joined with its variant."""
        cutoff = _ts(utcnow() - timedelta(hours=min_age_hours))
        with self.connect() as conn:
            rows = conn.execute('''
                SELECT p.id AS post_id, p.platform, p.posted_at, v.variant, v.id AS video_id,
                       m.views, m.likes, m.comments, m.shares, m.saves
                FROM posts p
                JOIN videos v ON v.id = p.video_id
                JOIN metrics m ON m.id = (SELECT id FROM metrics WHERE post_id = p.id
                                          ORDER BY collected_at DESC, id DESC LIMIT 1)
                WHERE p.status = 'posted' AND p.posted_at <= ?''', (cutoff,)).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            d['variant'] = json.loads(d['variant'])
            result.append(d)
        return result

    # ------------------------------------------------------------ stats
    def get_statistics(self) -> Dict:
        with self.connect() as conn:
            def count(sql, *args):
                return conn.execute(sql, args).fetchone()[0]
            models_by_status = {r[0]: r[1] for r in conn.execute(
                'SELECT status, COUNT(*) FROM models GROUP BY status')}
            posts_by_status = {f'{r[0]}:{r[1]}': r[2] for r in conn.execute(
                'SELECT platform, status, COUNT(*) FROM posts GROUP BY platform, status')}
            avg = conn.execute("SELECT AVG(render_seconds) FROM videos WHERE status = 'ready'").fetchone()[0]
            return {
                'models': models_by_status,
                'videos_ready': count("SELECT COUNT(*) FROM videos WHERE status = 'ready'"),
                'videos_failed': count("SELECT COUNT(*) FROM videos WHERE status = 'failed'"),
                'posts': posts_by_status,
                'average_render_seconds': round(avg or 0, 1),
            }
