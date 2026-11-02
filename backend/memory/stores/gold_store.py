# -*- coding: utf-8 -*-
"""
gold_store.py · Gold 层（题目指纹 → payload，仅精确匹配）

signature_hash = sha256(规范化指纹)，SQLite UNIQUE 索引，O(1) 查重。
"""
import time
from typing import Optional

from ..db import gold_to_row, row_to_gold
from ..models import Gold, canonical_fingerprint_hash


class GoldStore:
    def __init__(self, db):
        self.db = db

    def insert(self, g: Gold):
        self.db.execute(
            "INSERT OR IGNORE INTO gold(id, source_episode, fingerprint_json, signature_hash,"
            " payload, hit_count, last_hit, human_verified, success_count, created_at)"
            " VALUES(?,?,?,?,?,?,?,?,?,?)",
            tuple(gold_to_row(g).values()),
        )
        return g

    def get(self, gid: str) -> Optional[Gold]:
        rows = self.db.query("SELECT * FROM gold WHERE id=?", (gid,))
        return row_to_gold(rows[0]) if rows else None

    def get_by_hash(self, signature_hash: str) -> Optional[Gold]:
        rows = self.db.query("SELECT * FROM gold WHERE signature_hash=?", (signature_hash,))
        return row_to_gold(rows[0]) if rows else None

    def exact_match(self, fingerprint: dict) -> Optional[Gold]:
        """按规范化指纹精确匹配"""
        return self.get_by_hash(canonical_fingerprint_hash(fingerprint))

    def find_by_type_and_tables(self, vuln_type: str, tables) -> Optional[Gold]:
        """同题识别：vuln_type + 表名集合均精确相等（结构化精确匹配，不走向量）"""
        tables = sorted(set(t for t in (tables or []) if t))
        if not vuln_type and not tables:
            return None
        for g in self.list_all():
            fp = g.fingerprint or {}
            if fp.get("vuln_type") != vuln_type:
                continue
            fp_tables = sorted(set(t for t in (fp.get("tables") or []) if t))
            if fp_tables == tables:
                return g
        return None

    def update(self, g: Gold):
        self.db.execute(
            "UPDATE gold SET source_episode=?, fingerprint_json=?, signature_hash=?, payload=?,"
            " hit_count=?, last_hit=?, human_verified=?, success_count=?, created_at=? WHERE id=?",
            (g.source_episode, __import__("json").dumps(g.fingerprint, ensure_ascii=False),
             g.signature_hash, g.payload, g.hit_count, g.last_hit,
             int(g.human_verified), g.success_count, g.created_at, g.id),
        )

    def delete(self, gid: str):
        self.db.execute("DELETE FROM gold WHERE id=?", (gid,))

    def increment_hit(self, gid: str):
        now = int(time.time() * 1000)
        self.db.execute("UPDATE gold SET hit_count=hit_count+1, last_hit=? WHERE id=?", (now, gid))

    def list_all(self):
        return [row_to_gold(r) for r in self.db.query("SELECT * FROM gold ORDER BY created_at DESC")]

    def count(self) -> int:
        return self.db.query("SELECT COUNT(*) AS n FROM gold")[0]["n"]
