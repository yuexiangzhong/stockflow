BEGIN;

-- 借出单主表
CREATE TABLE IF NOT EXISTS loan_orders (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  loan_no      TEXT NOT NULL UNIQUE,         -- 单号，如 L251007001
  company      TEXT,                          -- 借入公司
  receiver     TEXT,                          -- 接货负责人
  handler      TEXT,                          -- 本公司经手人
  discount     REAL NOT NULL DEFAULT 1.0,     -- 0~1
  total_qty    INTEGER NOT NULL DEFAULT 0,
  total_amount INTEGER NOT NULL DEFAULT 0,    -- 折后合计（整数日元）
  status       TEXT NOT NULL DEFAULT '借出中',-- 借出中 / 已归还 / 部分归还
  created_at   TEXT                           -- 本地时间：由应用层写入 'YYYY-MM-DD HH:MM:SS'
);

-- 借出单明细
CREATE TABLE IF NOT EXISTS loan_items (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  order_id   INTEGER NOT NULL,
  product_id INTEGER NOT NULL,
  sku        TEXT NOT NULL,
  price      INTEGER NOT NULL DEFAULT 0,      -- 原售价（整数）
  FOREIGN KEY (order_id)  REFERENCES loan_orders(id) ON DELETE CASCADE,
  FOREIGN KEY (product_id) REFERENCES products(id)   ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_loan_items_order   ON loan_items(order_id);
CREATE INDEX IF NOT EXISTS idx_loan_items_product ON loan_items(product_id);

COMMIT;
