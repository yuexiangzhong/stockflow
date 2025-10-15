# api/routes_labels.py
from __future__ import annotations
from fastapi import APIRouter, Request, Depends, Form, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from datetime import datetime
from api.deps import current_user, get_db

router = APIRouter()

def _get_setting(key: str) -> str | None:
    db = get_db()
    with db.connect() as conn:
        cur = conn.cursor()
        cur.execute("SELECT value FROM settings WHERE key=? LIMIT 1", (key,))
        r = cur.fetchone()
        return (r["value"] if r else None)

def _company_code() -> str:
    return (_get_setting("company_code") or "").strip()

def _list_products(
    keyword: str = "",
    only_unprinted: bool = False,
    include_sold: bool = False,
    page: int = 1,
    page_size: int = 0,   # 0/负数 = 显示全部
):
    """
    返回 (rows, total)
    - 关键词：SKU/名称/详情/品类 模糊匹配
    - 仅未打印：label_printed_count 为 0 或 NULL
    - include_sold=False 时，排除 status='已售出'
    - 分页：page>=1；page_size<=0 则不分页（返回全部）
    """
    db = get_db()
    sql_base = "FROM products"
    conds, params = [], []

    if keyword:
        kw = f"%{keyword.strip()}%"
        conds.append("(sku LIKE ? OR name LIKE ? OR detail LIKE ? OR category LIKE ?)")
        params += [kw, kw, kw, kw]

    if only_unprinted:
        conds.append("(label_printed_count IS NULL OR label_printed_count = 0)")

    if not include_sold:
        # 默认不显示已售出
        conds.append("(status IS NULL OR status <> '已售出')")

    where_sql = (" WHERE " + " AND ".join(conds)) if conds else ""

    # 先查总数（用于分页）
    count_sql = f"SELECT COUNT(1) {sql_base}{where_sql}"
    rows_sql = f"SELECT * {sql_base}{where_sql} ORDER BY COALESCE(login_date, '') DESC, id DESC"

    with db.connect() as conn:
        cur = conn.cursor()
        # total
        cur.execute(count_sql, tuple(params))
        total = int(cur.fetchone()[0])

        # rows（分页）
        if page_size and page_size > 0:
            # 合法化页码
            page = max(1, int(page))
            offset = (page - 1) * int(page_size)
            rows_sql_limit = f"{rows_sql} LIMIT ? OFFSET ?"
            cur.execute(rows_sql_limit, tuple(params) + (int(page_size), int(offset)))
        else:
            # 不分页，返回全部
            cur.execute(rows_sql, tuple(params))

        rows = [dict(r) for r in cur.fetchall()]

        # 补充显示字段
        for r in rows:
            r["price_fmt"] = f"{int(r.get('sale_price') or 0):,}"
            r["cost_fmt"] = f"{int(r.get('cost_price') or 0):,}"
            status = (r.get("status") or "在库").strip()
            borrower = (r.get("borrower") or "").strip()
            if status == "借出" and borrower:
                r["status_display"] = f"借出（{borrower}）"
            else:
                r["status_display"] = status
            r["printed"] = (r.get("label_printed_count") or 0) > 0

        return rows, total

@router.get("/labels", response_class=HTMLResponse)
def labels_page(
    request: Request,
    q: str = Query("", description="关键词：SKU/名称/详情/品类"),
    only_unprinted: int = Query(0, description="仅未打印：1=是/0=否"),
    include_sold: int = Query(0, description="显示已售出：1=是/0=否（默认不显示）"),
    page: int = Query(1, description="页码（从1开始）"),
    page_size: int = Query(0, description="每页数量；0或负数=显示全部"),
    user=Depends(current_user),
):
    rows, total = _list_products(
        keyword=q,
        only_unprinted=(only_unprinted == 1),
        include_sold=(include_sold == 1),
        page=page,
        page_size=page_size,
    )
    return request.app.templates.TemplateResponse(
        "labels.html",
        {
            "request": request,
            "user": user,
            "rows": rows,
            "q": q,
            "only_unprinted": only_unprinted,
            "include_sold": include_sold,
            "company_code": _company_code(),
            # 分页信息
            "total": total,
            "page": page,
            "page_size": page_size,
        },
    )

@router.get("/labels/print", response_class=HTMLResponse)
def labels_print(
    request: Request,
    ids: str,                 # 逗号分隔的 product id
    # 版式参数（mm）
    w: float = 30.0, h: float = 30.0,
    margin_top: float = 10.0, margin_right: float = 10.0,
    margin_bottom: float = 10.0, margin_left: float = 10.0,
    gap_x: float = 2.0, gap_y: float = 2.0,
    start_row: int = 1, start_col: int = 1,
    # 字段开关（信息半）
    show_category: int = 1, show_detail: int = 1, show_weight: int = 1,
    # 字号策略（auto|small|medium|large）
    font_mode: str = "auto",
    user=Depends(current_user),
):
    # 取数据
    id_list = [int(x) for x in ids.split(",") if x.strip().isdigit()]
    if not id_list:
        return RedirectResponse(url="/labels", status_code=302)

    placeholders = ",".join(["?"] * len(id_list))
    db = get_db()
    with db.connect() as conn:
        cur = conn.cursor()
        cur.execute(f"SELECT * FROM products WHERE id IN ({placeholders}) ORDER BY id", tuple(id_list))
        rows = [dict(r) for r in cur.fetchall()]

    # 计算 A4 网格（列/行）
    page_w, page_h = 210.0, 297.0
    inner_w = page_w - margin_left - margin_right
    inner_h = page_h - margin_top - margin_bottom
    cols = max(1, int((inner_w + gap_x) // (w + gap_x)))
    rows_per_page = max(1, int((inner_h + gap_y) // (h + gap_y)))

    # 供模板渲染
    for r in rows:
        r["price_fmt"] = f"{int(r.get('sale_price') or 0):,}"
        r["weight_fmt"] = (str(r.get("spec")) + " g") if (r.get("spec") not in (None, "", " ")) else ""

    return request.app.templates.TemplateResponse(
        "labels_print.html",
        {
            "request": request,
            "rows": rows,
            "company_code": _company_code(),
            "box": {"w": w, "h": h},
            "margin": {"top": margin_top, "right": margin_right, "bottom": margin_bottom, "left": margin_left},
            "gap": {"x": gap_x, "y": gap_y},
            "grid": {"cols": cols, "rows": rows_per_page},
            "start": {"row": max(1, start_row), "col": max(1, start_col)},
            "fields": {"category": show_category, "detail": show_detail, "weight": show_weight},
            "font_mode": font_mode,
            "ids": ids,  # 用于打印后标记
            # 也可以把分页/筛选状态带回去（若你从打印页想返回列表复用参数）
        },
    )

@router.post("/labels/mark-printed")
def labels_mark_printed(ids: str = Form(...), user=Depends(current_user)):
    id_list = [int(x) for x in ids.split(",") if x.strip().isdigit()]
    if not id_list:
        return RedirectResponse(url="/labels", status_code=302)

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    placeholders = ",".join(["?"] * len(id_list))
    db = get_db()
    with db.connect() as conn:
        cur = conn.cursor()
        cur.execute(
            f"""
            UPDATE products
               SET label_printed_count = COALESCE(label_printed_count,0) + 1,
                   label_printed_at = ?
             WHERE id IN ({placeholders})
            """,
            (now, *id_list),
        )
        conn.commit()
    return RedirectResponse(url="/labels", status_code=303)
