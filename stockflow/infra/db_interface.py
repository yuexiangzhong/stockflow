from pathlib import Path
import sqlite3
from contextlib import contextmanager
from utils.logging import setup_logger

logger = setup_logger()

class DB:
    def __init__(self, db_path: str):
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._ensure_pragmas()

    def _ensure_pragmas(self):
        with self.connect() as conn:
            cur = conn.cursor()
            cur.execute("PRAGMA foreign_keys = ON;")
            cur.execute("PRAGMA journal_mode = WAL;")
            conn.commit()

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    @contextmanager
    def transaction(self):
        with self.connect() as conn:
            try:
                yield conn
                conn.commit()
            except Exception as e:
                conn.rollback()
                logger.error(f"DB transaction rollback: {e}")
                raise

def run_migrations(db: DB):
    # 仅执行一次的简易迁移：检测基础表是否存在，不存在就执行 0001
    with db.connect() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT name FROM sqlite_master
            WHERE type='table' AND name='products';
        """)
        if cur.fetchone():
            return
        sql_path = Path("infra/migrations/0001_init.sql")
        sql = sql_path.read_text(encoding="utf-8")
        cur.executescript(sql)
        conn.commit()
