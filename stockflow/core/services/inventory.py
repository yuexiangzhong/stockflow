from infra.db_interface import DB
from utils.exceptions import NotFound

class InventoryService:
    def __init__(self, db: DB):
        self.db = db

    # 商品
    def add_product(self, sku: str, name: str, spec: str|None=None,
                    unit: str="pcs", cost_price: float=0.0, sale_price: float=0.0) -> int:
        with self.db.transaction() as conn:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO products (sku, name, spec, unit, cost_price, sale_price) VALUES (?,?,?,?,?,?)",
                (sku, name, spec, unit, cost_price, sale_price),
            )
            return cur.lastrowid

    def list_products(self):
        with self.db.connect() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM products WHERE enabled=1 ORDER BY id DESC")
            return [dict(r) for r in cur.fetchall()]

    # 仓库
    def add_warehouse(self, code: str, name: str) -> int:
        with self.db.transaction() as conn:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO warehouses (code, name) VALUES (?,?)",
                (code, name),
            )
            return cur.lastrowid

    def ensure_stock_row(self, product_id: int, warehouse_id: int):
        with self.db.transaction() as conn:
            cur = conn.cursor()
            cur.execute(
                "INSERT OR IGNORE INTO stocks (product_id, warehouse_id, qty_on_hand, qty_reserved) VALUES (?, ?, 0, 0)",
                (product_id, warehouse_id),
            )

    # 入库（最小版）
    def inbound(self, product_id: int, warehouse_id: int, qty: float):
        self.ensure_stock_row(product_id, warehouse_id)
        with self.db.transaction() as conn:
            cur = conn.cursor()
            cur.execute(
                "UPDATE stocks SET qty_on_hand = qty_on_hand + ? WHERE product_id=? AND warehouse_id=?",
                (qty, product_id, warehouse_id),
            )

    # 出库（最小版，未做保留量与订单机制）
    def outbound(self, product_id: int, warehouse_id: int, qty: float):
        with self.db.transaction() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT qty_on_hand FROM stocks WHERE product_id=? AND warehouse_id=?",
                (product_id, warehouse_id),
            )
            row = cur.fetchone()
            if not row:
                raise NotFound("库存记录不存在")
            if row["qty_on_hand"] < qty:
                raise ValueError("库存不足")
            cur.execute(
                "UPDATE stocks SET qty_on_hand = qty_on_hand - ? WHERE product_id=? AND warehouse_id=?",
                (qty, product_id, warehouse_id),
            )

    def stock_of(self, product_id: int, warehouse_id: int):
        with self.db.connect() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT qty_on_hand, qty_reserved FROM stocks WHERE product_id=? AND warehouse_id=?",
                (product_id, warehouse_id),
            )
            row = cur.fetchone()
            if not row:
                return {"qty_on_hand": 0, "qty_reserved": 0}
            return dict(row)
