# core/services/ids.py
from __future__ import annotations
from datetime import datetime
from typing import Optional

# —— 工具 —— #
def _scope_yymm(dt: datetime | None = None) -> str:
    d = dt or datetime.now()
    return d.strftime("%y%m")

def _ensure_schema(conn) -> None:
    """
    幂等建表/索引：sequences(scope->next)、products.sku 唯一索引
    """
    # 序列表：每个 scope 维护一个 next 指针
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sequences (
            scope TEXT PRIMARY KEY,
            next  INTEGER NOT NULL
        );
    """)
    # 兜底唯一索引（如已建会忽略）
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_products_sku ON products(sku);")

def next_sequence(conn, scope: str) -> int:
    """
    从 sequences(scope) 中“取号并+1”，必须在**外层事务**中调用。
    事务建议使用 IMMEDIATE/EXCLUSIVE（你的 db.transaction() 已可满足）。
    返回：本次分配到的序号（已保证同事务下原子）
    """
    # 读取
    row = conn.execute(
        "SELECT next FROM sequences WHERE scope=? LIMIT 1",
        (scope,)
    ).fetchone()

    if not row:
        # 首次：插入 next=2，并返回 1
        conn.execute(
            "INSERT INTO sequences(scope, next) VALUES(?, ?)",
            (scope, 2)
        )
        return 1
    else:
        cur_next = int(row["next"] or 1)
        # 自增
        conn.execute(
            "UPDATE sequences SET next=? WHERE scope=?",
            (cur_next + 1, scope)
        )
        return cur_next

def alloc_sku(db, company_code: str) -> str:
    """
    生成并返回唯一 SKU：{COMPANY_CODE}-{YYMM}-{NNNN}
    - 在单一事务中完成：建表/取号/校验，避免并发冲突
    - 若你后续插入 products 时也在同一事务里，更稳
    """
    if not company_code or not company_code.strip():
        raise RuntimeError("公司代码为空，无法分配 SKU")

    scope = _scope_yymm()

    # 关键点：只用 **一个** 连接（同一事务）完成所有步骤
    with db.transaction() as conn:
        _ensure_schema(conn)

        n = next_sequence(conn, scope)
        sku = f"{company_code}-{scope}-{n:04d}"

        # 二次校验（理论上不会撞，因为序列原子；保守起见留着）
        exists = conn.execute(
            "SELECT 1 FROM products WHERE sku=? LIMIT 1",
            (sku,)
        ).fetchone()
        if exists:
            # 极低概率：若有人绕过分配器手工写了同名 SKU，顺延一次
            n = next_sequence(conn, scope)
            sku = f"{company_code}-{scope}-{n:04d}"

        return sku
