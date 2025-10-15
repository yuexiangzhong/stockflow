# api/deps.py
from __future__ import annotations
import pathlib
import sqlite3
from fastapi import Request, HTTPException, status

from utils.config import load_config
from infra.db_interface import DB, run_migrations

try:
    from core.services.inventory import InventoryService
    from core.services.auth import AuthService
except ModuleNotFoundError:
    from services.inventory import InventoryService
    from services.auth import AuthService

_cfg = load_config()
_db = DB(_cfg.database_path)

def _has_column(conn, table: str, column: str) -> bool:
    try:
        cols = [c[1] for c in conn.execute(f"PRAGMA table_info({table})").fetchall()]
        return column in cols
    except Exception:
        return False

def ensure_all_migrations():
    run_migrations(_db)

    files_in_order = [
        "0002_auth.sql",
        "0003_product_photo.sql",
        "0004_product_extra.sql",
        "0005_product_tax.sql",
        "0006_product_remark.sql",
        "0007_settings.sql",
        "0008_sku_qr.sql",
        "0009_label_print.sql",
        "0010_loans.sql",          # ✅ 新增
    ]

    with _db.connect() as conn:
        for fname in files_in_order:
            f = pathlib.Path(f"infra/migrations/{fname}")
            if f.exists():
                try:
                    conn.executescript(f.read_text(encoding="utf-8"))
                except sqlite3.OperationalError:
                    pass  # 幂等忽略

        # 兜底列（避免旧库缺列）
        for col, ddl in [
            ("photo_path",   "ALTER TABLE products ADD COLUMN photo_path TEXT"),
            ("category",     "ALTER TABLE products ADD COLUMN category TEXT"),
            ("detail",       "ALTER TABLE products ADD COLUMN detail TEXT"),
            ("login_date",   "ALTER TABLE products ADD COLUMN login_date TEXT"),
            ("tax_included", "ALTER TABLE products ADD COLUMN tax_included INTEGER NOT NULL DEFAULT 1"),
            ("remark",       "ALTER TABLE products ADD COLUMN remark TEXT"),
            ("status",       "ALTER TABLE products ADD COLUMN status TEXT"),
            ("borrower",     "ALTER TABLE products ADD COLUMN borrower TEXT"),
            # ✅ 新增借出字段兜底
            ("borrower_company",  "ALTER TABLE products ADD COLUMN borrower_company TEXT"),
            ("borrower_receiver", "ALTER TABLE products ADD COLUMN borrower_receiver TEXT"),
            ("borrower_handler",  "ALTER TABLE products ADD COLUMN borrower_handler TEXT"),
            ("borrowed_at",       "ALTER TABLE products ADD COLUMN borrowed_at TEXT"),
            ("sku",          "ALTER TABLE products ADD COLUMN sku TEXT"),
            ("qr_payload",   "ALTER TABLE products ADD COLUMN qr_payload TEXT"),
        ]:
            if not _has_column(conn, "products", col):
                try:
                    conn.execute(ddl)
                except sqlite3.OperationalError:
                    pass

        # 默认 status
        try:
            conn.execute("UPDATE products SET status='在库' WHERE status IS NULL OR status=''")
        except:
            pass

        try:
            conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_products_sku ON products(sku)")
        except sqlite3.OperationalError:
            pass
        try:
            conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_products_qr_payload ON products(qr_payload)")
        except sqlite3.OperationalError:
            pass
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS sequences (
                  scope TEXT PRIMARY KEY,
                  next  INTEGER NOT NULL
                )
            """)
        except sqlite3.OperationalError:
            pass

        conn.commit()

    AuthService(_db).ensure_default_admin()

ensure_all_migrations()

def get_cfg():
    return _cfg

def get_db():
    return _db

def get_services():
    return InventoryService(_db), AuthService(_db)

def current_user(request: Request):
    cookie_name = _cfg.security.get("cookie_name", "sf_session")
    token = request.cookies.get(cookie_name)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    from utils.security import decode_jwt
    data = decode_jwt(token, _cfg.security["secret_key"])
    if not data:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    return data
