"""
Database manager for tracking STL files and render jobs
"""
import sqlite3
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict
import json

class DatabaseManager:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.init_database()

    def init_database(self):
        """Initialize database with required tables"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()

            # Table for STL files
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS stl_files (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    filename TEXT UNIQUE NOT NULL,
                    filepath TEXT NOT NULL,
                    added_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    file_size INTEGER,
                    status TEXT DEFAULT 'pending'
                )
            ''')

            # Table for render jobs
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS render_jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    stl_file_id INTEGER,
                    output_path TEXT,
                    object_color TEXT,
                    background_color TEXT,
                    render_date TIMESTAMP,
                    render_duration REAL,
                    status TEXT DEFAULT 'pending',
                    error_message TEXT,
                    FOREIGN KEY (stl_file_id) REFERENCES stl_files(id)
                )
            ''')

            conn.commit()

    def add_stl_file(self, filepath: Path) -> int:
        """Add a new STL file to the database"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()

            file_size = filepath.stat().st_size

            cursor.execute('''
                INSERT OR IGNORE INTO stl_files (filename, filepath, file_size)
                VALUES (?, ?, ?)
            ''', (filepath.name, str(filepath), file_size))

            cursor.execute('SELECT id FROM stl_files WHERE filename = ?', 
                          (filepath.name,))
            result = cursor.fetchone()
            conn.commit()

            return result[0] if result else None

    def get_pending_files(self, limit: Optional[int] = None) -> List[Dict]:
        """Get pending STL files for processing"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            query = '''
                SELECT * FROM stl_files 
                WHERE status = 'pending'
                ORDER BY added_date ASC
            '''

            if limit:
                query += f' LIMIT {limit}'

            cursor.execute(query)
            return [dict(row) for row in cursor.fetchall()]

    def create_render_job(self, stl_file_id: int, 
                         object_color: tuple, 
                         background_color: tuple) -> int:
        """Create a new render job"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()

            cursor.execute('''
                INSERT INTO render_jobs 
                (stl_file_id, object_color, background_color)
                VALUES (?, ?, ?)
            ''', (stl_file_id, 
                  json.dumps(object_color), 
                  json.dumps(background_color)))

            conn.commit()
            return cursor.lastrowid

    def update_render_job(self, job_id: int, 
                         status: str,
                         output_path: Optional[str] = None,
                         render_duration: Optional[float] = None,
                         error_message: Optional[str] = None):
        """Update render job status"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()

            cursor.execute('''
                UPDATE render_jobs 
                SET status = ?,
                    output_path = ?,
                    render_date = CURRENT_TIMESTAMP,
                    render_duration = ?,
                    error_message = ?
                WHERE id = ?
            ''', (status, output_path, render_duration, error_message, job_id))

            # Update STL file status if job completed
            if status == 'completed':
                cursor.execute('''
                    UPDATE stl_files 
                    SET status = 'completed'
                    WHERE id = (SELECT stl_file_id FROM render_jobs WHERE id = ?)
                ''', (job_id,))

            conn.commit()

    def get_statistics(self) -> Dict:
        """Get rendering statistics"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()

            cursor.execute('SELECT COUNT(*) FROM stl_files')
            total_files = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM stl_files WHERE status = 'completed'")
            completed_files = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM stl_files WHERE status = 'pending'")
            pending_files = cursor.fetchone()[0]

            cursor.execute('''
                SELECT AVG(render_duration) FROM render_jobs 
                WHERE status = 'completed'
            ''')
            avg_duration = cursor.fetchone()[0] or 0

            return {
                'total_files': total_files,
                'completed_files': completed_files,
                'pending_files': pending_files,
                'average_render_time': round(avg_duration, 2)
            }
