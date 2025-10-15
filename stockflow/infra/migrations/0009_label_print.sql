-- infra/migrations/0009_label_print.sql
BEGIN;

-- 已打印次数
ALTER TABLE products ADD COLUMN label_printed_count INTEGER NOT NULL DEFAULT 0;

-- 最后打印时间（ISO8601 文本）
ALTER TABLE products ADD COLUMN label_printed_at TEXT;

COMMIT;
