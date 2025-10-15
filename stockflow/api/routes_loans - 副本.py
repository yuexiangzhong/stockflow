# api/routes_loans.py
from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException, Body, Request
from fastapi.responses import JSONResponse, HTMLResponse
from pydantic import BaseModel, Field
from typing import List
from datetime import datetime
from zoneinfo import ZoneInfo  # Python 3.9+ 自带
import os

from api.deps import get_services, get_db, current_user, get_cfg
from core.services.ids import next_sequence

router = APIRouter()

# === 工具：生成借出单号 LN-YYMM-NNNN ===

def _now_jst_str() -> str:
    return datetime.now(ZoneInfo("Asia/Tokyo")).strftime("%Y-%m-%d %H:%M:%S")

def _alloc_loan_no(conn) -> str:
    yymm = datetime.now().strftime("%y%m")
    scope = f"loan-{yymm}"            # 独立序列段
    n = next_sequence(conn, scope)
    return f"LN-{yymm}-{n:04d}"

# === 入参模型 ===
class LoanItemIn(BaseModel):
    sku: str

class LoanCreateIn(BaseModel):
    company: str = ""
    receiver: str = ""
    handler: str = ""
    discount: float = Field(..., ge=0.0, le=1.0)
    items: List[LoanItemIn]

# === POST /api/loans ===
@router.post("/api/loans", response_class=JSONResponse)
def create_loan(payload: LoanCreateIn = Body(...), user=Depends(current_user)):
    inv, _ = get_services()
    db = get_db()

    if not payload.items:
        raise HTTPException(400, "items 不能为空")
    if not (0 < payload.discount <= 1):
        raise HTTPException(400, "discount 必须在 (0, 1]")

    skus = [i.sku.strip().upper() for i in payload.items if i.sku.strip()]
    skus = list(dict.fromkeys(skus))  # 去重保序

    # 读取产品
    with db.connect() as conn:
        cur = conn.cursor()
        placeholders = ",".join(["?"] * len(skus))
        cur.execute(f"SELECT * FROM products WHERE UPPER(sku) IN ({placeholders})", tuple(skus))
        rows = [dict(r) for r in cur.fetchall()]

    # 校验存在 & 在库可借
    prod_by_sku = {r["sku"].upper(): r for r in rows}
    not_found = [s for s in skus if s not in prod_by_sku]
    if not_found:
        raise HTTPException(400, f"以下 SKU 不存在：{', '.join(not_found)}")
    bad_status = [r["sku"] for r in rows if (r.get("status") or "在库") != "在库"]
    if bad_status:
        raise HTTPException(400, f"以下 SKU 非在库状态，无法借出：{', '.join(bad_status)}")

    # 计算金额
    sale_prices = []
    for s in skus:
        sp = int(prod_by_sku[s]["sale_price"] or 0)
        sale_prices.append(sp)
    total_qty = len(skus)
    final_prices = [int(round(sp * payload.discount)) for sp in sale_prices]
    total_amount = sum(final_prices)

    # 写入订单 & 更新产品
    with db.transaction() as conn:
        loan_no = _alloc_loan_no(conn)

        # 使用东京时区时间作为创建时间（避免 UTC 少 9 小时）
        created_at = datetime.now(ZoneInfo("Asia/Tokyo")).strftime("%Y-%m-%d %H:%M:%S")

        cur = conn.cursor()
        cur.execute("""
            INSERT INTO loan_orders
                (loan_no, company, receiver, handler, discount,
                 total_qty, total_amount, status, created_at)
            VALUES
                (?,       ?,       ?,       ?,       ?,
                 ?,       ?,       '借出中', ?)
        """, (
            loan_no,
            payload.company.strip(),
            payload.receiver.strip(),
            payload.handler.strip(),
            float(payload.discount),
            total_qty,
            total_amount,
            created_at,
        ))
        loan_id = cur.lastrowid

        # 明细
        for s, sp, fp in zip(skus, sale_prices, final_prices):
            p = prod_by_sku[s]
            cur.execute("""
                INSERT INTO loan_items(loan_id, product_id, sku, sale_price, discount, final_price)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (loan_id, int(p["id"]), p["sku"], int(sp), float(payload.discount), int(fp)))

        # 更新产品状态 + 借出信息（同时把 borrower 也填上，便于旧表格展示）
        borrower_text = " / ".join([x for x in [payload.company.strip(), payload.receiver.strip(), payload.handler.strip()] if x])
        for s in skus:
            p = prod_by_sku[s]
            cur.execute("""
                UPDATE products
                   SET status='借出',
                       borrower_company=?,
                       borrower_receiver=?,
                       borrower_handler=?,
                       borrower=?,
                       borrowed_at=datetime('now')
                 WHERE id=?
            """, (payload.company.strip(), payload.receiver.strip(), payload.handler.strip(), borrower_text, int(p["id"])))

    # 事件日志
    cfg = get_cfg()
    from export.event_logger import append_event
    append_event(cfg.paths["event_log_dir"], {
        "type": "loan_create",
        "loan_no": loan_no,
        "company": payload.company,
        "receiver": payload.receiver,
        "handler": payload.handler,
        "discount": float(payload.discount),
        "total_qty": total_qty,
        "total_amount": total_amount,
        "skus": skus,
        "user": user["username"],
    })

    return {
        "ok": True,
        "loan_id": loan_id,
        "loan_no": loan_no,
        "total_qty": total_qty,
        "total_amount": total_amount,
    }

# === GET /loans/{loan_id} 借出单详情（HTML） ===
@router.get("/loans/{loan_id}", response_class=HTMLResponse)
def loan_detail(loan_id: int, request: Request, user=Depends(current_user)):
    db = get_db()
    with db.connect() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM loan_orders WHERE id=? LIMIT 1", (loan_id,))
        head = cur.fetchone()
        if not head:
            raise HTTPException(404, "借出单不存在")

        # 明细 + 基本产品信息（品类/详情/图）
        cur.execute("""
            SELECT li.*, p.category, p.detail, p.photo_path
              FROM loan_items li
              JOIN products p ON p.id = li.product_id
             WHERE li.loan_id=?
             ORDER BY li.id
        """, (loan_id,))
        items = [dict(r) for r in cur.fetchall()]

    # 构造 photo_url
    for r in items:
        pp = r.get("photo_path") or ""
        r["photo_url"] = (f"/photos/{os.path.basename(pp)}" if pp else "")

    return request.app.templates.TemplateResponse("loan_detail.html", {
        "request": request,
        "user": user,
        "head": dict(head),
        "items": items,
    })
