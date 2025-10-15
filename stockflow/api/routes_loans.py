# api/routes_loans.py
from __future__ import annotations
from typing import List, Optional
from datetime import datetime

from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi import status as http_status
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from api.deps import get_db, current_user, get_cfg
from export.event_logger import append_event

router = APIRouter()

# ====== 输入模型 ======
class LoanItemIn(BaseModel):
    sku: str

class LoanCreateIn(BaseModel):
    company:  Optional[str] = ""
    receiver: Optional[str] = ""
    handler:  Optional[str] = ""
    discount: float = Field(..., gt=0.0, le=1.0)
    items:    List[LoanItemIn]

# ====== 表结构兜底：防止清库后 500 ======
def _ensure_schema(conn) -> None:
    # 订单头
    conn.execute("""
    CREATE TABLE IF NOT EXISTS loan_orders (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        loan_no       TEXT UNIQUE NOT NULL,
        company       TEXT,
        receiver      TEXT,
        handler       TEXT,
        discount      REAL NOT NULL DEFAULT 1.0,
        total_qty     INTEGER NOT NULL DEFAULT 0,
        total_amount  INTEGER NOT NULL DEFAULT 0,   -- 折后合计（整数）
        status        TEXT NOT NULL DEFAULT '借出中',
        created_at    TEXT NOT NULL,                -- 本地时间字符串
        returned_qty  INTEGER NOT NULL DEFAULT 0,
        returned_amt  INTEGER NOT NULL DEFAULT 0,
        closed_at     TEXT
    );
    """)
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_loan_orders_no ON loan_orders(loan_no);")

    # 订单明细
    conn.execute("""
    CREATE TABLE IF NOT EXISTS loan_items (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        order_id   INTEGER NOT NULL,
        product_id INTEGER NOT NULL,
        sku        TEXT NOT NULL,
        price      INTEGER NOT NULL DEFAULT 0,     -- 原价
        returned   INTEGER NOT NULL DEFAULT 0,     -- 0/1
        returned_at TEXT,
        FOREIGN KEY(order_id) REFERENCES loan_orders(id) ON DELETE CASCADE
    );
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_loan_items_order ON loan_items(order_id);")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_loan_items_sku   ON loan_items(sku);")

    # products 上用到的字段兜底（老库可能缺）
    try:
        cols = [c[1] for c in conn.execute("PRAGMA table_info(products)").fetchall()]
        if "status" not in cols:
            conn.execute("ALTER TABLE products ADD COLUMN status TEXT;")
            conn.execute("UPDATE products SET status='在库' WHERE status IS NULL OR status='';")
        if "borrower" not in cols:
            conn.execute("ALTER TABLE products ADD COLUMN borrower TEXT;")
    except Exception:
        pass

# ====== 单号分配：LYYMMDDNNN（sequences 表） ======
def _alloc_loan_no(conn) -> str:
    today = datetime.now().strftime("%y%m%d")  # YYMMDD
    scope = f"LOAN-{today}"
    row = conn.execute("SELECT next FROM sequences WHERE scope=? LIMIT 1", (scope,)).fetchone()
    if not row:
        conn.execute("INSERT INTO sequences(scope, next) VALUES(?, ?)", (scope, 2))
        n = 1
    else:
        n = int(row["next"] or 1)
        conn.execute("UPDATE sequences SET next=? WHERE scope=?", (n + 1, scope))
    return f"L{today}{n:03d}"

# ====== 创建借出单（兼容两个路径） ======
@router.post("/api/loans")
@router.post("/api/loans/create")
def create_loan(payload: LoanCreateIn, user = Depends(current_user)):
    if not payload.items:
        raise HTTPException(http_status.HTTP_400_BAD_REQUEST, detail="明细为空")
    if not (payload.company or payload.receiver or payload.handler):
        raise HTTPException(http_status.HTTP_400_BAD_REQUEST, detail="借入公司/接货负责人/经手人至少填写一项")

    # SKU 去重规范化
    sku_list = [(it.sku or "").strip().upper() for it in payload.items if (it.sku or "").strip()]
    sku_list = list(dict.fromkeys(sku_list))
    if not sku_list:
        raise HTTPException(http_status.HTTP_400_BAD_REQUEST, detail="SKU 为空")

    db = get_db()
    with db.transaction() as conn:
        # 兜底建表
        _ensure_schema(conn)

        # 拉取商品
        ph = ",".join(["?"] * len(sku_list))
        rows = conn.execute(f"""
            SELECT id, sku, sale_price, status, borrower
              FROM products
             WHERE sku IN ({ph})
        """, tuple(sku_list)).fetchall()
        found = { (r["sku"] or "").upper(): r for r in rows }

        # 缺失
        missing = [s for s in sku_list if s not in found]
        if missing:
            raise HTTPException(http_status.HTTP_404_NOT_FOUND, detail=f"不存在的 SKU: {', '.join(missing)}")

        # 非“在库”拦截（二次保护）
        bad = []
        for s in sku_list:
            st = (found[s]["status"] or "在库").strip()
            if st != "在库":
                who = found[s]["borrower"] or ""
                bad.append(f"{s}（状态：{st}{'，' + who if who else ''}）")
        if bad:
            raise HTTPException(http_status.HTTP_409_CONFLICT, detail="以下商品不可借出：\n" + "\n".join(bad))

        # 合计
        total_qty = len(sku_list)
        origin_sum = sum(int(found[s]["sale_price"] or 0) for s in sku_list)
        total_amount = int(round(origin_sum * float(payload.discount)))

        # 本地时间（避免 SQLite 时区偏差）
        now_local = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        borrower_txt = "，".join([x for x in [
            (f"借入公司：{payload.company.strip()}"  ) if payload.company  else "",
            (f"接货负责人：{payload.receiver.strip()}") if payload.receiver else "",
            (f"本公司经手人：{payload.handler.strip()}")  if payload.handler  else "",
            (f"折扣：{payload.discount:.2f}")
        ] if x])

        # 订单头
        loan_no = _alloc_loan_no(conn)
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO loan_orders(loan_no, company, receiver, handler, discount,
                                    total_qty, total_amount, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, '借出中', ?)
        """, (
            loan_no,
            (payload.company or "").strip(),
            (payload.receiver or "").strip(),
            (payload.handler or "").strip(),
            float(payload.discount),
            total_qty,
            total_amount,
            now_local,
        ))
        loan_id = cur.lastrowid

        # 明细
        for s in sku_list:
            r = found[s]
            cur.execute("""
                INSERT INTO loan_items(order_id, product_id, sku, price)
                VALUES (?, ?, ?, ?)
            """, (loan_id, int(r["id"]), r["sku"], int(r["sale_price"] or 0)))

        # 更新产品状态 + 借出方
        conn.execute(f"""
            UPDATE products
               SET status='借出', borrower=?
             WHERE sku IN ({ph})
        """, (borrower_txt, *sku_list))

    # 事件日志
    cfg = get_cfg()
    append_event(cfg.paths["event_log_dir"], {
        "type": "loan_create",
        "loan_id": loan_id,
        "loan_no": loan_no,
        "company": payload.company or "",
        "receiver": payload.receiver or "",
        "handler":  payload.handler  or "",
        "discount": payload.discount,
        "total_qty": total_qty,
        "total_amount": total_amount,
        "items": sku_list,
        "user": user["username"],
        "created_at": now_local
    })

    return {
        "loan_id": loan_id,
        "loan_no": loan_no,
        "total_qty": total_qty,
        "total_amount": total_amount,
        "created_at": now_local
    }

# ====== 详情页：/loans/{slug}，slug 可为 id 或 loan_no ======
@router.get("/loans/{loan_id}", response_class=HTMLResponse)
def loan_detail_page(request: Request, loan_id: int, user=Depends(current_user)):
    db = get_db()
    with db.connect() as conn:
        # 头
        h = conn.execute("""
            SELECT id, loan_no, company, receiver, handler, discount,
                   total_qty, total_amount, status, created_at
              FROM loan_orders
             WHERE id=?
             LIMIT 1
        """, (loan_id,)).fetchone()
        if not h:
            raise HTTPException(status_code=404, detail="借出单不存在")

        # 明细 + 产品信息
        rows = conn.execute("""
            SELECT li.sku,
                   li.price                   AS sale_price,
                   p.category,
                   p.detail,
                   p.photo_path,
                   p.name,
                   p.spec
              FROM loan_items li
              LEFT JOIN products p ON p.id = li.product_id
             WHERE li.order_id=?
             ORDER BY li.id
        """, (loan_id,)).fetchall()

    head = dict(h)
    discount = float(head.get("discount") or 1)

    # 规范缩略图 URL，并算折后价（模板里用到 final_price）
    def photo_url_from_path(path: str | None) -> str:
        if not path:
            return ""
        p = str(path).replace("\\", "/")
        base = p.rsplit("/", 1)[-1]
        return f"/photos/{base}" if base else ""

    items = []
    for r in rows:
        d = dict(r)
        d["photo_url"]  = photo_url_from_path(d.get("photo_path"))
        d["final_price"] = int(round((int(d.get("sale_price") or 0)) * discount))
        items.append(d)

    return request.app.templates.TemplateResponse(
        "loan_detail.html",            # ← 和你现有模板名一致
        {
            "request": request,
            "user": user,
            "head": head,              # ← 模板里用 head.*
            "items": items             # ← 模板里用 items 循环
        }
    )