import os
import sqlite3
from datetime import datetime
from typing import List, Dict, Optional
import pytz

# Try importing psycopg2 for Postgres
try:
    import psycopg2
    import psycopg2.extras
    HAS_POSTGRES = True
except ImportError:
    HAS_POSTGRES = False

DB_PATH = "tasks.db"

class Database:
    def __init__(self):
        self.is_postgres = False
        self.db_url = os.getenv("DATABASE_URL")
        self._postgres_conn = None
        
        if self.db_url and HAS_POSTGRES:
            try:
                # Test connection
                self.is_postgres = True
                conn = self.get_conn()
                print("DATABASE: Connected to PostgreSQL cloud database successfully!", flush=True)
            except Exception as e:
                print(f"DATABASE WARNING: Could not connect to PostgreSQL ({e}). Falling back to SQLite local database.", flush=True)
                self.is_postgres = False
                self._postgres_conn = None
        else:
            print("DATABASE: PostgreSQL connection not configured or library missing. Using local SQLite database (tasks.db).", flush=True)
            
        self.init_db()

    def get_conn(self):
        if self.db_url and HAS_POSTGRES:
            if self._postgres_conn is None or self._postgres_conn.closed:
                self._reconnect_postgres()
            else:
                # Active ping to verify connection is physically alive
                try:
                    with self._postgres_conn.cursor() as cur:
                        cur.execute("SELECT 1")
                except (psycopg2.OperationalError, psycopg2.InterfaceError):
                    print("DATABASE WARNING: Connection physically dead. Reconnecting...", flush=True)
                    self._reconnect_postgres()
            
            if self._postgres_conn is not None:
                return self._postgres_conn
                
        # Fallback to SQLite
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        return conn

    def _reconnect_postgres(self):
        try:
            if self._postgres_conn is not None:
                try:
                    self._postgres_conn.close()
                except Exception:
                    pass
            self._postgres_conn = psycopg2.connect(self.db_url)
            self._postgres_conn.autocommit = True
            self.is_postgres = True
        except Exception as e:
            print(f"DATABASE RECONNECT ERROR: {e}. Falling back to SQLite temporarily.", flush=True)
            self.is_postgres = False
            self._postgres_conn = None

    def init_db(self):
        # 1. Initialize SQLite always to ensure fallback database exists
        try:
            with sqlite3.connect(DB_PATH) as conn:
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

                    CREATE TABLE IF NOT EXISTS task_attachments (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        task_id INTEGER,
                        type TEXT,
                        content TEXT,
                        created_at TEXT DEFAULT (datetime('now','localtime'))
                    );
                """)
                try:
                    conn.execute("ALTER TABLE users ADD COLUMN mapped_employee TEXT;")
                except sqlite3.OperationalError:
                    pass
                try:
                    conn.execute("ALTER TABLE tasks ADD COLUMN deadline_alert_sent INTEGER DEFAULT 0;")
                except sqlite3.OperationalError:
                    pass
        except Exception as e:
            print(f"DATABASE WARNING: Failed to initialize SQLite database ({e})", flush=True)

        # 2. Initialize Postgres if configured
        if self.db_url and HAS_POSTGRES:
            try:
                conn = self.get_conn()
                if self.is_postgres and conn is not None:
                    with conn.cursor() as cur:
                        cur.execute("""
                            CREATE TABLE IF NOT EXISTS tasks (
                                id SERIAL PRIMARY KEY,
                                text TEXT NOT NULL,
                                responsible TEXT NOT NULL,
                                deadline TEXT NOT NULL,
                                priority TEXT DEFAULT 'Ўрта',
                                status TEXT DEFAULT 'Кутяпти',
                                created_by BIGINT,
                                created_by_name TEXT,
                                updated_by TEXT,
                                created_at TEXT DEFAULT to_char(now() AT TIME ZONE 'Asia/Tashkent', 'YYYY-MM-DD HH24:MI:SS'),
                                updated_at TEXT DEFAULT to_char(now() AT TIME ZONE 'Asia/Tashkent', 'YYYY-MM-DD HH24:MI:SS'),
                                deadline_alert_sent INTEGER DEFAULT 0
                            );

                            CREATE TABLE IF NOT EXISTS users (
                                id SERIAL PRIMARY KEY,
                                telegram_id BIGINT UNIQUE NOT NULL,
                                full_name TEXT,
                                username TEXT,
                                mapped_employee TEXT,
                                created_at TEXT DEFAULT to_char(now() AT TIME ZONE 'Asia/Tashkent', 'YYYY-MM-DD HH24:MI:SS')
                            );

                            CREATE TABLE IF NOT EXISTS groups (
                                id SERIAL PRIMARY KEY,
                                chat_id BIGINT UNIQUE NOT NULL,
                                title TEXT,
                                created_at TEXT DEFAULT to_char(now() AT TIME ZONE 'Asia/Tashkent', 'YYYY-MM-DD HH24:MI:SS')
                            );

                            CREATE TABLE IF NOT EXISTS task_history (
                                id SERIAL PRIMARY KEY,
                                task_id INTEGER,
                                old_status TEXT,
                                new_status TEXT,
                                changed_by TEXT,
                                changed_at TEXT DEFAULT to_char(now() AT TIME ZONE 'Asia/Tashkent', 'YYYY-MM-DD HH24:MI:SS')
                            );

                            CREATE TABLE IF NOT EXISTS task_attachments (
                                id SERIAL PRIMARY KEY,
                                task_id INTEGER,
                                type TEXT,
                                content TEXT,
                                created_at TEXT DEFAULT to_char(now() AT TIME ZONE 'Asia/Tashkent', 'YYYY-MM-DD HH24:MI:SS')
                            );
                        """)
            except Exception as e:
                print(f"DATABASE WARNING: Failed to initialize PostgreSQL database ({e}). Falling back to SQLite local database.", flush=True)
                self.is_postgres = False
                self._postgres_conn = None

    # ─── Users ────────────────────────────────────────────────────────────────

    def add_user(self, telegram_id: int, full_name: str, username: str):
        if self.is_postgres:
            with self.get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO users (telegram_id, full_name, username)
                        VALUES (%s, %s, %s)
                        ON CONFLICT (telegram_id)
                        DO UPDATE SET full_name = EXCLUDED.full_name, username = EXCLUDED.username
                    """, (telegram_id, full_name, username))
        else:
            with self.get_conn() as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO users (telegram_id, full_name, username)
                    VALUES (?, ?, ?)
                """, (telegram_id, full_name, username))

    def get_all_users(self) -> List[Dict]:
        if self.is_postgres:
            with self.get_conn() as conn:
                with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
                    cur.execute("SELECT * FROM users")
                    return [dict(r) for r in cur.fetchall()]
        else:
            with self.get_conn() as conn:
                rows = conn.execute("SELECT * FROM users").fetchall()
                return [dict(r) for r in rows]

    # ─── Groups ────────────────────────────────────────────────────────────────

    def add_group(self, chat_id: int, title: str):
        if self.is_postgres:
            with self.get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO groups (chat_id, title)
                        VALUES (%s, %s)
                        ON CONFLICT (chat_id)
                        DO UPDATE SET title = EXCLUDED.title
                    """, (chat_id, title))
        else:
            with self.get_conn() as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO groups (chat_id, title)
                    VALUES (?, ?)
                """, (chat_id, title))

    def get_all_groups(self) -> List[Dict]:
        if self.is_postgres:
            with self.get_conn() as conn:
                with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
                    cur.execute("SELECT * FROM groups")
                    return [dict(r) for r in cur.fetchall()]
        else:
            with self.get_conn() as conn:
                rows = conn.execute("SELECT * FROM groups").fetchall()
                return [dict(r) for r in rows]

    # ─── Employee Mapping ──────────────────────────────────────────────────────

    def map_user_to_employee(self, telegram_id: int, employee_name: str):
        if self.is_postgres:
            with self.get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("UPDATE users SET mapped_employee = %s WHERE telegram_id = %s", (employee_name, telegram_id))
        else:
            with self.get_conn() as conn:
                conn.execute("UPDATE users SET mapped_employee = ? WHERE telegram_id = ?", (employee_name, telegram_id))

    def get_mapped_employee(self, telegram_id: int) -> Optional[str]:
        if self.is_postgres:
            with self.get_conn() as conn:
                with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
                    cur.execute("SELECT mapped_employee FROM users WHERE telegram_id = %s", (telegram_id,))
                    row = cur.fetchone()
                    return row['mapped_employee'] if row and row['mapped_employee'] else None
        else:
            with self.get_conn() as conn:
                row = conn.execute("SELECT mapped_employee FROM users WHERE telegram_id = ?", (telegram_id,)).fetchone()
                return row['mapped_employee'] if row and row['mapped_employee'] else None

    def get_user_by_mapped_employee(self, employee_name: str) -> Optional[Dict]:
        if self.is_postgres:
            with self.get_conn() as conn:
                with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
                    cur.execute("SELECT * FROM users WHERE mapped_employee = %s", (employee_name,))
                    row = cur.fetchone()
                    return dict(row) if row else None
        else:
            with self.get_conn() as conn:
                row = conn.execute("SELECT * FROM users WHERE mapped_employee = ?", (employee_name,)).fetchone()
                return dict(row) if row else None

    # ─── Tasks ────────────────────────────────────────────────────────────────

    def add_task(self, text: str, responsible: str, deadline: str,
                 priority: str, created_by: int, created_by_name: str) -> int:
        now_str = datetime.now(pytz.timezone("Asia/Tashkent")).strftime("%Y-%m-%d %H:%M:%S")
        if self.is_postgres:
            with self.get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO tasks (text, responsible, deadline, priority, status, created_by, created_by_name, created_at, updated_at)
                        VALUES (%s, %s, %s, %s, 'Жараёнда', %s, %s, %s, %s) RETURNING id
                    """, (text, responsible, deadline, priority, created_by, created_by_name, now_str, now_str))
                    return cur.fetchone()[0]
        else:
            with self.get_conn() as conn:
                cur = conn.execute("""
                    INSERT INTO tasks (text, responsible, deadline, priority, status, created_by, created_by_name)
                    VALUES (?, ?, ?, ?, 'Жараёнда', ?, ?)
                """, (text, responsible, deadline, priority, created_by, created_by_name))
                return cur.lastrowid

    def get_all_tasks(self) -> List[Dict]:
        query = """
            SELECT * FROM tasks ORDER BY
            CASE priority WHEN 'Юқори' THEN 1 WHEN 'Ўрта' THEN 2 ELSE 3 END,
            created_at DESC
        """
        if self.is_postgres:
            with self.get_conn() as conn:
                with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
                    cur.execute(query)
                    return [dict(r) for r in cur.fetchall()]
        else:
            with self.get_conn() as conn:
                rows = conn.execute(query).fetchall()
                return [dict(r) for r in rows]

    def get_active_tasks(self) -> List[Dict]:
        query = """
            SELECT * FROM tasks
            WHERE status NOT IN ('Бажарилди', 'Бекор қилинди')
            ORDER BY created_at DESC
        """
        if self.is_postgres:
            with self.get_conn() as conn:
                with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
                    cur.execute(query)
                    return [dict(r) for r in cur.fetchall()]
        else:
            with self.get_conn() as conn:
                rows = conn.execute(query).fetchall()
                return [dict(r) for r in rows]

    def get_task(self, task_id: int) -> Optional[Dict]:
        if self.is_postgres:
            with self.get_conn() as conn:
                with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
                    cur.execute("SELECT * FROM tasks WHERE id = %s", (task_id,))
                    row = cur.fetchone()
                    return dict(row) if row else None
        else:
            with self.get_conn() as conn:
                row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
                return dict(row) if row else None

    def update_task_status(self, task_id: int, status: str, updated_by: str):
        now_str = datetime.now(pytz.timezone("Asia/Tashkent")).strftime("%Y-%m-%d %H:%M:%S")
        if self.is_postgres:
            with self.get_conn() as conn:
                with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
                    cur.execute("SELECT status FROM tasks WHERE id = %s", (task_id,))
                    old = cur.fetchone()
                    
                    cur.execute("""
                        UPDATE tasks SET status = %s, updated_by = %s,
                        updated_at = %s WHERE id = %s
                    """, (status, updated_by, now_str, task_id))
                    
                    if old:
                        cur.execute("""
                            INSERT INTO task_history (task_id, old_status, new_status, changed_by, changed_at)
                            VALUES (%s, %s, %s, %s, %s)
                        """, (task_id, old['status'], status, updated_by, now_str))
        else:
            with self.get_conn() as conn:
                old = conn.execute("SELECT status FROM tasks WHERE id = ?", (task_id,)).fetchone()
                conn.execute("""
                    UPDATE tasks SET status = ?, updated_by = ?,
                    updated_at = ? WHERE id = ?
                """, (status, updated_by, now_str, task_id))
                if old:
                    conn.execute("""
                        INSERT INTO task_history (task_id, old_status, new_status, changed_by, changed_at)
                        VALUES (?, ?, ?, ?, ?)
                    """, (task_id, old['status'], status, updated_by, now_str))

    def delete_task(self, task_id: int) -> bool:
        if self.is_postgres:
            with self.get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("DELETE FROM tasks WHERE id = %s", (task_id,))
                    return cur.rowcount > 0
        else:
            with self.get_conn() as conn:
                cur = conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
                return cur.rowcount > 0

    # ─── Statistics ───────────────────────────────────────────────────────────

    def get_statistics(self) -> Dict:
        query = """
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN status='Бажарилди' THEN 1 ELSE 0 END) as done,
                SUM(CASE WHEN status='Жараёнда' THEN 1 ELSE 0 END) as in_progress,
                SUM(CASE WHEN status='Кутяпти' THEN 1 ELSE 0 END) as waiting,
                SUM(CASE WHEN status='Бекор қилинди' THEN 1 ELSE 0 END) as cancelled
            FROM tasks
        """
        if self.is_postgres:
            with self.get_conn() as conn:
                with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
                    cur.execute(query)
                    row = cur.fetchone()
                    res = dict(row) if row else {}
        else:
            with self.get_conn() as conn:
                row = conn.execute(query).fetchone()
                res = dict(row) if row else {}
                
        for key in ['total', 'done', 'in_progress', 'waiting', 'cancelled']:
            if res.get(key) is None:
                res[key] = 0
        return res

    def get_employee_statistics(self) -> List[Dict]:
        query = """
            SELECT
                responsible,
                COUNT(*) as total,
                SUM(CASE WHEN status='Бажарилди' THEN 1 ELSE 0 END) as done,
                SUM(CASE WHEN status='Жараёнда' THEN 1 ELSE 0 END) as in_progress,
                SUM(CASE WHEN status='Кутяпти' THEN 1 ELSE 0 END) as waiting,
                ROUND(
                    CAST(SUM(CASE WHEN status='Бажарилди' THEN 1 ELSE 0 END) * 100.0 AS NUMERIC) / COUNT(*), 1
                ) as percent
            FROM tasks
            GROUP BY responsible
            ORDER BY percent DESC, done DESC
        """
        if self.is_postgres:
            with self.get_conn() as conn:
                with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
                    cur.execute(query)
                    return [dict(r) for r in cur.fetchall()]
        else:
            with self.get_conn() as conn:
                rows = conn.execute(query).fetchall()
                return [dict(r) for r in rows]

    def get_employee_tasks(self, responsible: str) -> List[Dict]:
        query = """
            SELECT * FROM tasks
            WHERE responsible = %s
            ORDER BY
            CASE status WHEN 'Жараёнда' THEN 1 WHEN 'Кутяпти' THEN 2 WHEN 'Бажарилди' THEN 3 ELSE 4 END,
            created_at DESC
        """
        if self.is_postgres:
            with self.get_conn() as conn:
                with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
                    cur.execute(query, (responsible,))
                    return [dict(r) for r in cur.fetchall()]
        else:
            with self.get_conn() as conn:
                rows = conn.execute(query.replace("%s", "?"), (responsible,)).fetchall()
                return [dict(r) for r in rows]

    def get_single_employee_statistics(self, responsible: str) -> Dict:
        query = """
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN status='Бажарилди' THEN 1 ELSE 0 END) as done,
                SUM(CASE WHEN status='Жараёнда' THEN 1 ELSE 0 END) as in_progress,
                SUM(CASE WHEN status='Кутяпти' THEN 1 ELSE 0 END) as waiting,
                SUM(CASE WHEN status='Бекор қилинди' THEN 1 ELSE 0 END) as cancelled
            FROM tasks
            WHERE responsible = %s
        """
        if self.is_postgres:
            with self.get_conn() as conn:
                with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
                    cur.execute(query, (responsible,))
                    row = cur.fetchone()
                    res = dict(row) if row else {}
        else:
            with self.get_conn() as conn:
                row = conn.execute(query.replace("%s", "?"), (responsible,)).fetchone()
                res = dict(row) if row else {}
                
        for key in ['total', 'done', 'in_progress', 'waiting', 'cancelled']:
            if res.get(key) is None:
                res[key] = 0
        return res

    # ─── Task Attachments & Alerts ────────────────────────────────────────────

    def add_task_attachment(self, task_id: int, type_: str, content: str):
        now_str = datetime.now(pytz.timezone("Asia/Tashkent")).strftime("%Y-%m-%d %H:%M:%S")
        if self.is_postgres:
            with self.get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO task_attachments (task_id, type, content, created_at)
                        VALUES (%s, %s, %s, %s)
                    """, (task_id, type_, content, now_str))
        else:
            with self.get_conn() as conn:
                conn.execute("""
                    INSERT INTO task_attachments (task_id, type, content)
                    VALUES (?, ?, ?)
                """, (task_id, type_, content))

    def get_task_attachments(self, task_id: int) -> List[Dict]:
        query = """
            SELECT * FROM task_attachments
            WHERE task_id = %s
            ORDER BY created_at ASC
        """
        if self.is_postgres:
            with self.get_conn() as conn:
                with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
                    cur.execute(query, (task_id,))
                    return [dict(r) for r in cur.fetchall()]
        else:
            with self.get_conn() as conn:
                rows = conn.execute(query.replace("%s", "?"), (task_id,)).fetchall()
                return [dict(r) for r in rows]

    def set_deadline_alert_sent(self, task_id: int):
        if self.is_postgres:
            with self.get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("UPDATE tasks SET deadline_alert_sent = 1 WHERE id = %s", (task_id,))
        else:
            with self.get_conn() as conn:
                conn.execute("UPDATE tasks SET deadline_alert_sent = 1 WHERE id = ?", (task_id,))
