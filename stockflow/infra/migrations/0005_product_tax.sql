-- 商品是否含税：1=含税进货，0=无税进货
ALTER TABLE products ADD COLUMN IF NOT EXISTS tax_included INTEGER NOT NULL DEFAULT 1;
