-- 为商品增加原始字段，避免编辑弹窗丢值
ALTER TABLE products ADD COLUMN category TEXT;
ALTER TABLE products ADD COLUMN detail TEXT;
