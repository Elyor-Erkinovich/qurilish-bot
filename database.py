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
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA synchronous=NORMAL;")
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
                    mapped_employee TEXT,
                    created_at TEXT DEFAULT (datetime('now','localtime'))
                );

                CREATE TABLE IF NOT EXISTS groups (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id INTEGER UNIQUE NOT NULL,
                    title TEXT,
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

            # Migration check: add mapped_employee column if it doesn't exist
            try:
                conn.execute("ALTER TABLE users ADD COLUMN mapped_employee TEXT;")
            except sqlite3.OperationalError:
                pass

            # Migration check: add deadline_alert_sent column if it doesn't exist
            try:
                conn.execute("ALTER TABLE tasks ADD COLUMN deadline_alert_sent INTEGER DEFAULT 0;")
            except sqlite3.OperationalError:
                pass

            # Create task_attachments table if it doesn't exist
            conn.execute("""
                CREATE TABLE IF NOT EXISTS task_attachments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id INTEGER,
                    type TEXT,
                    content TEXT,
                    created_at TEXT DEFAULT (datetime('now','localtime'))
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

    # ─── Groups ────────────────────────────────────────────────────────────────

    def add_group(self, chat_id: int, title: str):
        with self.get_conn() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO groups (chat_id, title)
                VALUES (?, ?)
            """, (chat_id, title))

    def get_all_groups(self) -> List[Dict]:
        with self.get_conn() as conn:
            rows = conn.execute("SELECT * FROM groups").fetchall()
            return [dict(r) for r in rows]

    # ─── Employee Mapping ──────────────────────────────────────────────────────

    def map_user_to_employee(self, telegram_id: int, employee_name: str):
        with self.get_conn() as conn:
            conn.execute("UPDATE users SET mapped_employee = ? WHERE telegram_id = ?", (employee_name, telegram_id))

    def get_mapped_employee(self, telegram_id: int) -> Optional[str]:
        with self.get_conn() as conn:
            row = conn.execute("SELECT mapped_employee FROM users WHERE telegram_id = ?", (telegram_id,)).fetchone()
            return row['mapped_employee'] if row and row['mapped_employee'] else None

    def get_user_by_mapped_employee(self, employee_name: str) -> Optional[Dict]:
        with self.get_conn() as conn:
            row = conn.execute("SELECT * FROM users WHERE mapped_employee = ?", (employee_name,)).fetchone()
            return dict(row) if row else None

    # ─── Tasks ────────────────────────────────────────────────────────────────

    def add_task(self, text: str, responsible: str, deadline: str,
                 priority: str, created_by: int, created_by_name: str) -> int:
        with self.get_conn() as conn:
            cur = conn.execute("""
                INSERT INTO tasks (text, responsible, deadline, priority, status, created_by, created_by_name)
                VALUES (?, ?, ?, ?, 'Жараёнда', ?, ?)
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

    def get_employee_tasks(self, responsible: str) -> List[Dict]:
        with self.get_conn() as conn:
            rows = conn.execute("""
                SELECT * FROM tasks
                WHERE responsible = ?
                ORDER BY
                CASE status WHEN 'Жараёнда' THEN 1 WHEN 'Кутяпти' THEN 2 WHEN 'Бажарилди' THEN 3 ELSE 4 END,
                created_at DESC
            """, (responsible,)).fetchall()
            return [dict(r) for r in rows]

    def get_single_employee_statistics(self, responsible: str) -> Dict:
        with self.get_conn() as conn:
            row = conn.execute("""
                SELECT
                    COUNT(*) as total,
                    SUM(CASE WHEN status='Бажарилди' THEN 1 ELSE 0 END) as done,
                    SUM(CASE WHEN status='Жараёнда' THEN 1 ELSE 0 END) as in_progress,
                    SUM(CASE WHEN status='Кутяпти' THEN 1 ELSE 0 END) as waiting,
                    SUM(CASE WHEN status='Бекор қилинди' THEN 1 ELSE 0 END) as cancelled
                FROM tasks
                WHERE responsible = ?
            """, (responsible,)).fetchone()
            
            res = dict(row) if row else {}
            for key in ['total', 'done', 'in_progress', 'waiting', 'cancelled']:
                if res.get(key) is None:
                    res[key] = 0
            return res

    # ─── Task Attachments & Alerts ────────────────────────────────────────────

    def add_task_attachment(self, task_id: int, type_: str, content: str):
        with self.get_conn() as conn:
            conn.execute("""
                INSERT INTO task_attachments (task_id, type, content)
                VALUES (?, ?, ?)
            """, (task_id, type_, content))

    def get_task_attachments(self, task_id: int) -> List[Dict]:
        with self.get_conn() as conn:
            rows = conn.execute("""
                SELECT * FROM task_attachments
                WHERE task_id = ?
                ORDER BY created_at ASC
            """, (task_id,)).fetchall()
            return [dict(r) for r in rows]

    def set_deadline_alert_sent(self, task_id: int):
        with self.get_conn() as conn:
            conn.execute("UPDATE tasks SET deadline_alert_sent = 1 WHERE id = ?", (task_id,))


