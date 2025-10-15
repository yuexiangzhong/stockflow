# GUI 里的商品/仓库/入库/出库

from fastapi import APIRouter, Request, Form, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from api.deps import get_services, current_user, get_cfg
from export.event_logger import append_event
from core.services.settings import SettingsService
from core.services.ids import alloc_sku
from api.routes_qr import build_qr_payload


router = APIRouter()

import re, os, sqlite3
from datetime import datetime
from fastapi import File, UploadFile

# =========================
# 工具函数：金额/克重规范化 & 商品行装饰
# =========================


def _list_loans_for_inbound(db, limit:int=50):
    with db.connect() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, loan_no, company, receiver, handler, discount, total_qty, total_amount, status, created_at
              FROM loan_orders
             ORDER BY (status='借出中') DESC, id DESC
             LIMIT ?
        """, (int(limit),))
        rows = [dict(r) for r in cur.fetchall()]
        # 补格式
        for r in rows:
            r["amount_fmt"] = f"{int(r.get('total_amount') or 0):,}"
        return rows


def _normalize_amount(s: str) -> str:
    """金额：全角→半角，去逗号，只留数字（整数日元）。"""
    if s is None: return ""
    trans = str.maketrans("０１２３４５６７８９，．、", "0123456789,..")
    s = s.translate(trans).replace(",", "")
    return re.sub(r"[^\d]", "", s)

def _normalize_weight(s: str) -> str:
    """克重：全角→半角，去逗号和 g，只留数字与一个小数点（如 12 或 12.5）。"""
    if s is None: return ""
    trans = str.maketrans("０１２３４５６７８９．，、Ｇｇ", "0123456789..  g")
    s = s.translate(trans).replace(",", "").replace("g","").replace("G","").strip()
    s = re.sub(r"[^0-9.]", "", s)
    if s.count(".") > 1:
        parts = [p for p in s.split(".") if p]
        s = parts[0] + ("." + parts[1] if len(parts) > 1 else "")
    return s

def _decorate_products(rows: list[dict]) -> list[dict]:
    """模板展示字段：金额千分位、克重+g、图片URL、品类/详情、登录日、含税勾叉、状态行色、备注等"""
    out = []
    PREDEF = {"戒指", "项链", "手链", "耳饰", "吊坠", "胸针"}
    for r0 in rows:
        r = dict(r0)

        # 金额
        try: r["cost_fmt"] = f'{int(r.get("cost_price") or 0):,}'
        except: r["cost_fmt"] = "0"
        try: r["price_fmt"] = f'{int(r.get("sale_price") or 0):,}'
        except: r["price_fmt"] = "0"
        r["cost_raw"]  = str(int(r.get("cost_price") or 0))
        r["price_raw"] = str(int(r.get("sale_price") or 0))

        # 克重
        w = r.get("spec"); w_str = (str(w).strip() if w is not None else "")
        r["weight_fmt"] = (f"{w_str} g" if w_str else "")

        # 图片
        pp = r.get("photo_path"); r["photo_url"] = (f"/photos/{os.path.basename(pp)}" if pp else "")

        r["qr_url"] = f"/qr/{r['sku']}.png" if r.get("sku") else ""


        # 品类/详情
        r["category"] = r.get("category") or ""
        r["detail"]   = r.get("detail") or ""
        r["category_select"] = (r["category"] if r["category"] in PREDEF else "")
        r["category_custom"] = ("" if r["category"] in PREDEF else r["category"])

        # 登录日期
        r["login_date"] = (r.get("login_date") or "")

        # ✅ 含税勾叉
        ti = r.get("tax_included")
        r["tax_included"] = 1 if str(ti) == "1" else 0
        r["tax_mark"] = "✓" if r["tax_included"] == 1 else "✗"

        # ✅ 备注
        r["remark"] = r.get("remark") or ""

        # ✅ 状态与行色（红=借出 / 灰=已出售 / 白=在库）
        status = (r.get("status") or "在库")
        r["status"] = status
        if status == "借出":
            r["row_bg"] =  "#FCA5A5"   # 稍深一点的红
        elif status == "已出售":
            r["row_bg"] = "#F5F5F5"   # 淡灰
        else:
            r["row_bg"] = "#FFFFFF"   # 白

        # 借出对象（预留显示用）
        r["borrower"] = r.get("borrower") or ""

        out.append(r)
    return out

# =========================
# 商品：列表/新增/编辑/删除
# =========================

@router.get("/products", response_class=HTMLResponse)
def products_page(request: Request, user=Depends(current_user)):
    inv, _ = get_services()
    rows = _decorate_products(inv.list_products())
    return request.app.templates.TemplateResponse(
        "products.html",
        {"request": request, "user": user, "rows": rows}
    )

@router.post("/products", response_class=HTMLResponse)
def product_add(request: Request,
                # sku: str = Form(...),   # ← 不再从表单接收
                category: str = Form(""),
                category_custom: str = Form(""),
                detail: str = Form(""),
                weight: str = Form(""),
                cost: str = Form(""),
                price: str = Form(...),
                login_date: str = Form(""),
                tax_included: str = Form("1"),
                remark: str = Form(""),
                photo: UploadFile | None = File(None),
                user=Depends(current_user)):
    inv, _ = get_services()

    # 售价
    norm_price = _normalize_amount(price)
    if not norm_price:
        rows = _decorate_products(inv.list_products())
        return request.app.templates.TemplateResponse(
            "products.html",
            {"request": request, "user": user, "rows": rows, "error": "售价必须为整数（日元）。"}
        )
    sale_price = int(norm_price)

    # 成本
    cost_price = 0
    if cost.strip():
        norm_cost = _normalize_amount(cost)
        if not norm_cost:
            rows = _decorate_products(inv.list_products())
            return request.app.templates.TemplateResponse(
                "products.html",
                {"request": request, "user": user, "rows": rows, "error": "成本价如填写，必须为整数（日元）。"}
            )
        cost_price = int(norm_cost)

    # 克重
    spec_val = None
    if weight.strip():
        norm_weight = _normalize_weight(weight)
        if not norm_weight:
            rows = _decorate_products(inv.list_products())
            return request.app.templates.TemplateResponse(
                "products.html",
                {"request": request, "user": user, "rows": rows, "error": "克重格式不正确（示例：12 或 12.5）。"}
            )
        spec_val = norm_weight

    # 名称：等于 detail（可空）
    final_name = detail.strip() if detail.strip() else ""

    # 读取公司代码，并分配 SKU
    ss = SettingsService(inv.db)
    company_code = ss.get("company_code")
    if not company_code:
        rows = _decorate_products(inv.list_products())
        return request.app.templates.TemplateResponse(
            "products.html",
            {"request": request, "user": user, "rows": rows, "error": "未设置公司代码，请先完成“公司初始化”。"}
        )
    sku = alloc_sku(inv.db, company_code)

    # 先插入基础字段
    pid = inv.add_product(sku, final_name, spec_val, "pcs", cost_price, sale_price)

    # 扩展字段
    login_date_val = (login_date.strip() or datetime.now().strftime("%Y-%m-%d"))
    tax_flag = 1 if str(tax_included) == "1" else 0
    remark_val = remark.strip() or None
    category_val = (category_custom.strip() or category.strip() or None)
    detail_val = (detail.strip() or "")

    # 生成二维码载荷并保存
    from api.deps import get_cfg
    cfg = get_cfg()
    qr_payload = build_qr_payload(company_code, sku, cfg.security["secret_key"])

    with inv.db.transaction() as conn:
        conn.execute("""
            UPDATE products
               SET category=?, detail=?, login_date=?, tax_included=?, remark=?, status='在库', qr_payload=?
             WHERE id=?""",
            (category_val, detail_val, login_date_val, tax_flag, remark_val, qr_payload, pid)
        )

    # 照片
    saved_path = None
    if photo and photo.filename:
        from pathlib import Path
        photos_dir = Path("data/photos"); photos_dir.mkdir(parents=True, exist_ok=True)
        ext = os.path.splitext(photo.filename)[1].lower() or ".jpg"
        fname = f"{sku}_{datetime.now().strftime('%Y%m%d_%H%M%S')}{ext}"
        dest = photos_dir / fname
        with open(dest, "wb") as f:
            f.write(photo.file.read())
        saved_path = str(dest)
        with inv.db.transaction() as conn:
            conn.execute("UPDATE products SET photo_path=? WHERE id=?", (saved_path, pid))

    # 事件日志
    from export.event_logger import append_event
    ev = {
        "type": "product_add", "sku": sku, "name": final_name, "user": user["username"],
        "sale_price": sale_price, "cost_price": cost_price, "weight_g": spec_val,
        "login_date": login_date_val, "tax_included": tax_flag, "remark": remark or "", "status": "在库",
        "qr_payload": qr_payload
    }
    if saved_path: ev["photo"] = saved_path
    append_event(cfg.paths["event_log_dir"], ev)

    return RedirectResponse(url="/products", status_code=303)



@router.post("/products/{pid}/update", response_class=HTMLResponse)
def product_update(request: Request,
                   pid: int,
                   sku: str = Form(""),    # ← 表单可能传，但我们不会用它覆盖
                   category: str = Form(""),
                   category_custom: str = Form(""),
                   detail: str = Form(""),
                   weight: str = Form(""),
                   cost: str = Form(""),
                   price: str = Form(...),
                   login_date: str = Form(""),
                   tax_included: str = Form("1"),
                   remark: str = Form(""),
                   photo: UploadFile | None = File(None),
                   user=Depends(current_user)):
    inv, _ = get_services()

    with inv.db.connect() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM products WHERE id=?", (pid,))
        old = cur.fetchone()
    if not old:
        return RedirectResponse(url="/products", status_code=303)

    # 金额
    new_sale = _normalize_amount(price) or str(int(old["sale_price"] or 0))
    new_cost = _normalize_amount(cost) if cost.strip() else str(int(old["cost_price"] or 0))
    sale_price = int(new_sale)
    cost_price = int(new_cost)

    # 克重
    if weight.strip():
        norm_weight = _normalize_weight(weight)
        if not norm_weight:
            rows = _decorate_products(inv.list_products())
            return request.app.templates.TemplateResponse(
                "products.html",
                {"request": request, "user": user, "rows": rows, "error": "克重格式不正确（示例：12 或 12.5）。"}
            )
        spec_val = norm_weight
    else:
        spec_val = old["spec"]

    # 详情/品类
    new_category = (category_custom.strip() or category.strip()) if (category_custom.strip() or category.strip()) else (old["category"] or "")
    new_detail = detail.strip() if detail.strip() else ""
    final_name = new_detail

    # 保持原 SKU，不允许修改
    keep_sku = old["sku"]

    # 登录日期 / 含税 / 备注
    login_date_val = (login_date.strip() or (old["login_date"] or "")) or datetime.now().strftime("%Y-%m-%d")
    tax_flag = 1 if str(tax_included) == "1" else 0
    remark_val = (remark.strip() if remark.strip() != "" else (old["remark"] if "remark" in old.keys() else None))

    with inv.db.transaction() as conn:
        conn.execute("""
            UPDATE products
               SET sku=?, name=?, spec=?, unit=?, cost_price=?, sale_price=?,
                   category=?, detail=?, login_date=?, tax_included=?, remark=?
             WHERE id=?""",
            (keep_sku, final_name, spec_val, "pcs", cost_price, sale_price,
             new_category or None, new_detail, login_date_val, tax_flag, remark_val, pid)
        )

    # 图片
    if photo and photo.filename:
        from pathlib import Path
        photos_dir = Path("data/photos"); photos_dir.mkdir(parents=True, exist_ok=True)
        ext = os.path.splitext(photo.filename)[1].lower() or ".jpg"
        fname = f"{keep_sku}_{datetime.now().strftime('%Y%m%d_%H%M%S')}{ext}"
        dest = photos_dir / fname
        with open(dest, "wb") as f:
            f.write(photo.file.read())
        with inv.db.transaction() as conn:
            conn.execute("UPDATE products SET photo_path=? WHERE id=?", (str(dest), pid))

    # 事件日志
    from export.event_logger import append_event
    from api.deps import get_cfg
    cfg = get_cfg()
    append_event(cfg.paths["event_log_dir"], {
        "type": "product_update", "id": pid, "sku": keep_sku, "name": final_name,
        "user": user["username"], "sale_price": sale_price, "cost_price": cost_price,
        "weight_g": spec_val, "login_date": login_date_val, "tax_included": tax_flag, "remark": remark_val or ""
    })

    return RedirectResponse(url="/products", status_code=303)


def _product_has_activity(conn: sqlite3.Connection, pid: int) -> bool:
    """
    安全删除检查：遍历所有表，若存在带 product_id 列且有记录指向该商品，则视为有业务记录，禁止删除。
    这样即使你的实际业务表名不同（inbound/outbound/stock_moves/...），也能稳妥拦截。
    """
    # 列出所有非系统表
    tbls = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    ).fetchall()]
    for t in tbls:
        # 查该表是否有 product_id 列
        try:
            cols = [c[1] for c in conn.execute(f"PRAGMA table_info({t})").fetchall()]
        except Exception:
            continue
        if "product_id" in cols:
            try:
                row = conn.execute(f"SELECT 1 FROM {t} WHERE product_id=? LIMIT 1", (pid,)).fetchone()
                if row:
                    return True
            except Exception:
                # 表数据不规范/其他异常视为有风险，保守不删除
                return True
    return False

@router.post("/products/{pid}/delete", response_class=HTMLResponse)
def product_delete(request: Request, pid: int, user=Depends(current_user)):
    inv, _ = get_services()
    with inv.db.connect() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM products WHERE id=?", (pid,))
        row = cur.fetchone()
        if not row:
            return RedirectResponse(url="/products", status_code=303)

        # 有业务记录则禁止删除
        if _product_has_activity(conn, pid):
            # 直接回列表；如需在 UI 展示提示，可在模板中读取 query 参数显示
            return RedirectResponse(url="/products?error=has_activity", status_code=303)

        # 尝试删除图片文件
        try:
            pp = row["photo_path"]
            if pp and os.path.isfile(pp):
                os.remove(pp)
        except Exception:
            pass

    # 真正删除记录
    with inv.db.transaction() as conn:
        conn.execute("DELETE FROM products WHERE id=?", (pid,))

    # 事件日志
    cfg = get_cfg()
    append_event(cfg.paths["event_log_dir"], {
        "type": "product_delete", "id": pid, "sku": row["sku"], "name": row["name"], "user": user["username"]
    })

    return RedirectResponse(url="/products", status_code=303)

# =========================
# 仓库/入库/出库（未改）
# =========================

@router.get("/warehouses", response_class=HTMLResponse)
def warehouses_page(request: Request, user=Depends(current_user)):
    inv, _ = get_services()
    with inv.db.connect() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM warehouses ORDER BY id DESC")
        whs = [dict(r) for r in cur.fetchall()]
    return request.app.templates.TemplateResponse(
        "warehouses.html",
        {"request": request, "user": user, "rows": whs}
    )

@router.post("/warehouses")
def warehouse_add(request: Request, code: str = Form(...), name: str = Form(...),
                  user=Depends(current_user)):
    inv, _ = get_services()
    inv.add_warehouse(code, name)
    cfg = get_cfg()
    append_event(cfg.paths["event_log_dir"], {
        "type": "warehouse_add", "code": code, "name": name, "user": user["username"]
    })
    return RedirectResponse(url="/warehouses", status_code=303)

@router.get("/inbound", response_class=HTMLResponse)
def inbound_page(request: Request, user=Depends(current_user)):
    inv, _ = get_services()
    prods = inv.list_products()
    with inv.db.connect() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM warehouses ORDER BY id DESC")
        whs = [dict(r) for r in cur.fetchall()]
    # ✅ 带上借出单列表（前 50 条，借出中优先）
    loans = _list_loans_for_inbound(inv.db, 50)

    return request.app.templates.TemplateResponse(
        "inbound.html",
        {"request": request, "user": user, "products": prods, "warehouses": whs, "loans": loans}
    )


@router.post("/inbound")
def inbound_post(request: Request, product_id: int = Form(...), wh_id: int = Form(...),
                 qty: float = Form(...), user=Depends(current_user)):
    inv, _ = get_services()
    inv.inbound(product_id, wh_id, qty)
    cfg = get_cfg()
    append_event(cfg.paths["event_log_dir"], {
        "type": "inbound", "product_id": product_id, "warehouse_id": wh_id,
        "qty": qty, "user": user["username"]
    })
    return RedirectResponse(url="/inbound", status_code=303)

@router.get("/outbound", response_class=HTMLResponse)
def outbound_page(request: Request, user=Depends(current_user)):
    inv, _ = get_services()
    prods = inv.list_products()
    with inv.db.connect() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM warehouses ORDER BY id DESC")
        whs = [dict(r) for r in cur.fetchall()]
    return request.app.templates.TemplateResponse(
        "outbound.html",
        {"request": request, "user": user, "products": prods, "warehouses": whs}
    )

@router.post("/outbound")
def outbound_post(request: Request, product_id: int = Form(...), wh_id: int = Form(...),
                  qty: float = Form(...), user=Depends(current_user)):
    inv, _ = get_services()
    inv.outbound(product_id, wh_id, qty)
    cfg = get_cfg()
    append_event(cfg.paths["event_log_dir"], {
        "type": "outbound", "product_id": product_id, "warehouse_id": wh_id,
        "qty": qty, "user": user["username"]
    })
    return RedirectResponse(url="/outbound", status_code=303)
