# -*- coding: utf-8 -*-
"""
pending_store.py · 待审队列

复盘产物中 confidence < 0.5 的 pattern / error_fix 不直接入库，
进本表等待人工审核（人工确认后再调 MemoryService 入库）。
"""
import json
from typing import List, Optional

from ..db import _u


class PendingItem:
    __slots__ = ("id", "kind", "payload", "reason", "confidence", "created_at")

    def __init__(self, id, kind, payload, reason, confidence, created_at):
        self.id = id
        self.kind = kind          # pattern | error_fix
        self.payload = payload    # dict（模型原始输出条目）
        self.reason = reason
        self.confidence = confidence
        self.created_at = created_at

    def to_dict(self):
        return {
            "id": self.id, "kind": self.kind, "payload": self.payload,
            "reason": self.reason, "confidence": self.confidence,
            "created_at": self.created_at,
        }


class PendingStore:
    def __init__(self, db):
        self.db = db

    def add(self, kind: str, payload: dict, reason: str, confidence: float, pid: str = "") -> PendingItem:
        import time
        item = PendingItem(
            pid or ("pd_" + str(int(time.time() * 1000))),
            kind, payload, reason, confidence, int(time.time() * 1000),
        )
        self.db.execute(
            "INSERT OR REPLACE INTO pending_review(id, kind, payload_json, reason, confidence, created_at)"
            " VALUES(?,?,?,?,?,?)",
            (item.id, item.kind, json.dumps(item.payload, ensure_ascii=False),
             item.reason, item.confidence, item.created_at),
        )
        return item

    def get(self, pid: str) -> Optional[PendingItem]:
        rows = self.db.query("SELECT * FROM pending_review WHERE id=?", (pid,))
        return self._row(rows[0]) if rows else None

    def delete(self, pid: str):
        self.db.execute("DELETE FROM pending_review WHERE id=?", (pid,))

    def list_all(self) -> List[PendingItem]:
        return [self._row(r) for r in self.db.query("SELECT * FROM pending_review ORDER BY created_at DESC")]

    def count(self) -> int:
        return self.db.query("SELECT COUNT(*) AS n FROM pending_review")[0]["n"]

    @staticmethod
    def _row(r):
        return PendingItem(
            r["id"], r["kind"], _u(r["payload_json"]) or {},
            r["reason"], r["confidence"], r["created_at"],
        )
