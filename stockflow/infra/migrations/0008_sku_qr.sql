-- 0008_sku_qr.sql
-- 1) 为产品增加 sku 与 qr_payload 字段（若不存在）
PRAGMA foreign_keys=off;
BEGIN TRANSACTION;

-- sku（产品编码，唯一且不可为空）
ALTER TABLE products ADD COLUMN sku TEXT;

-- 二维码载荷（唯一，避免重复）
ALTER TABLE products ADD COLUMN qr_payload TEXT;

COMMIT;
PRAGMA foreign_keys=on;

-- 2) 为 sku/qr_payload 建唯一索引（幂等处理：如果已建会报错，可忽略）
CREATE UNIQUE INDEX IF NOT EXISTS idx_products_sku ON products(sku);
CREATE UNIQUE INDEX IF NOT EXISTS idx_products_qr_payload ON products(qr_payload);

-- 3) 流水号表（用于按月发号）
CREATE TABLE IF NOT EXISTS sequences (
  scope TEXT PRIMARY KEY,        -- 例如 '2509'（YYMM）
  next  INTEGER NOT NULL
);
