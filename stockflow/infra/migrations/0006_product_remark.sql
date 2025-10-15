-- 商品备注（内部记录）
ALTER TABLE products ADD COLUMN IF NOT EXISTS remark TEXT;
