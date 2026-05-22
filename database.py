import sqlite3
from datetime import datetime
from typing import List, Dict, Optional

DB_PATH = "tasks.db"

class Database:
    def __init__(self):
        self.init_db()

    def get_conn(self):
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        return conn

    def init_db(self):
        with self.get_conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    text TEXT NOT NULL,
                    responsible TEXT NOT NULL,
                    deadline TEXT NOT NULL,
                    priority TEXT DEFAULT 'Ўрта',
                    status TEXT DEFAULT 'Кутяпти',
                    created_by INTEGER,
                    created_by_name TEXT,
                    updated_by TEXT,
                    created_at TEXT DEFAULT (datetime('now','localtime')),
                    updated_at TEXT DEFAULT (datetime('now','localtime'))
                );

                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    telegram_id INTEGER UNIQUE NOT NULL,
                    full_name TEXT,
                    username TEXT,
                    created_at TEXT DEFAULT (datetime('now','localtime'))
                );

                CREATE TABLE IF NOT EXISTS task_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id INTEGER,
                    old_status TEXT,
                    new_status TEXT,
                    changed_by TEXT,
                    changed_at TEXT DEFAULT (datetime('now','localtime'))
                );
            """)

    # ─── Users ────────────────────────────────────────────────────────────────

    def add_user(self, telegram_id: int, full_name: str, username: str):
        with self.get_conn() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO users (telegram_id, full_name, username)
                VALUES (?, ?, ?)
            """, (telegram_id, full_name, username))

    def get_all_users(self) -> List[Dict]:
        with self.get_conn() as conn:
            rows = conn.execute("SELECT * FROM users").fetchall()
            return [dict(r) for r in rows]

    # ─── Tasks ────────────────────────────────────────────────────────────────

    def add_task(self, text: str, responsible: str, deadline: str,
                 priority: str, created_by: int, created_by_name: str) -> int:
        with self.get_conn() as conn:
            cur = conn.execute("""
                INSERT INTO tasks (text, responsible, deadline, priority, created_by, created_by_name)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (text, responsible, deadline, priority, created_by, created_by_name))
            return cur.lastrowid

    def get_all_tasks(self) -> List[Dict]:
        with self.get_conn() as conn:
            rows = conn.execute("""
                SELECT * FROM tasks ORDER BY
                CASE priority WHEN 'Юқори' THEN 1 WHEN 'Ўрта' THEN 2 ELSE 3 END,
                created_at DESC
            """).fetchall()
            return [dict(r) for r in rows]

    def get_active_tasks(self) -> List[Dict]:
        with self.get_conn() as conn:
            rows = conn.execute("""
                SELECT * FROM tasks
                WHERE status NOT IN ('Бажарилди', 'Бекор қилинди')
                ORDER BY created_at DESC
            """).fetchall()
            return [dict(r) for r in rows]

    def get_task(self, task_id: int) -> Optional[Dict]:
        with self.get_conn() as conn:
            row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
            return dict(row) if row else None

    def update_task_status(self, task_id: int, status: str, updated_by: str):
        with self.get_conn() as conn:
            old = conn.execute("SELECT status FROM tasks WHERE id = ?", (task_id,)).fetchone()
            conn.execute("""
                UPDATE tasks SET status = ?, updated_by = ?,
                updated_at = datetime('now','localtime') WHERE id = ?
            """, (status, updated_by, task_id))
            if old:
                conn.execute("""
                    INSERT INTO task_history (task_id, old_status, new_status, changed_by)
                    VALUES (?, ?, ?, ?)
                """, (task_id, old['status'], status, updated_by))

    def delete_task(self, task_id: int) -> bool:
        with self.get_conn() as conn:
            cur = conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
            return cur.rowcount > 0

    # ─── Statistics ───────────────────────────────────────────────────────────

    def get_statistics(self) -> Dict:
        with self.get_conn() as conn:
            row = conn.execute("""
                SELECT
                    COUNT(*) as total,
                    SUM(CASE WHEN status='Бажарилди' THEN 1 ELSE 0 END) as done,
                    SUM(CASE WHEN status='Жараёнда' THEN 1 ELSE 0 END) as in_progress,
                    SUM(CASE WHEN status='Кутяпти' THEN 1 ELSE 0 END) as waiting,
                    SUM(CASE WHEN status='Бекор қилинди' THEN 1 ELSE 0 END) as cancelled
                FROM tasks
            """).fetchone()
            return dict(row)

    def get_employee_statistics(self) -> List[Dict]:
        with self.get_conn() as conn:
            rows = conn.execute("""
                SELECT
                    responsible,
                    COUNT(*) as total,
                    SUM(CASE WHEN status='Бажарилди' THEN 1 ELSE 0 END) as done,
                    SUM(CASE WHEN status='Жараёнда' THEN 1 ELSE 0 END) as in_progress,
                    SUM(CASE WHEN status='Кутяпти' THEN 1 ELSE 0 END) as waiting,
                    ROUND(
                        SUM(CASE WHEN status='Бажарилди' THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1
                    ) as percent
                FROM tasks
                GROUP BY responsible
                ORDER BY percent DESC, done DESC
            """).fetchall()
            return [dict(r) for r in rows]
