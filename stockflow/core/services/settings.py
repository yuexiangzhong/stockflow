# core/services/settings.py
from __future__ import annotations
import re, random

class SettingsService:
    def __init__(self, db):
        self.db = db

    def get(self, key: str) -> str | None:
        with self.db.connect() as conn:
            cur = conn.cursor()
            cur.execute("SELECT value FROM settings WHERE key=? LIMIT 1", (key,))
            row = cur.fetchone()
            return row["value"] if row else None

    def set(self, key: str, value: str):
        with self.db.transaction() as conn:
            conn.execute("INSERT INTO settings(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                         (key, value))

    def has_company_code(self) -> bool:
        return bool(self.get("company_code"))

    # —— 生成逻辑 ——
    @staticmethod
    def suggest_abbrev(company_name: str) -> str:
        """
        从公司名称提取首字母（A-Z/0-9），最多6位。简化规则：抓取字母数字“词”的首字母；
        若提取不到，给一个默认 'GS'（可手工改）。
        """
        if not company_name:
            return "GS"
        tokens = re.findall(r"[A-Za-z0-9]+", company_name)
        if tokens:
            letters = "".join(t[0] for t in tokens if t)[:6].upper()
            return letters or "GS"
        # 无法提取时，取公司名里能找到的拉丁字母；再不行用 GS
        letters = "".join(re.findall(r"[A-Za-z]", company_name))[:6].upper()
        return letters or "GS"

    @staticmethod
    def normalize_abbrev(abbrev: str) -> str:
        """手动缩写字段清洗：只留 A-Z0-9，最多6位，转大写；为空则由调用者再去 fallback。"""
        s = re.sub(r"[^A-Za-z0-9]", "", abbrev or "").upper()
        return s[:6]

    @staticmethod
    def gen_company_code(abbrev: str) -> str:
        """拼上4位随机数（零填充）。"""
        rand = f"{random.randint(0, 9999):04d}"
        return f"{abbrev}{rand}"
