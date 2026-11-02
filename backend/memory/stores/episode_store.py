# -*- coding: utf-8 -*-
"""
episode_store.py · Episode 层（完整轨迹，仅审计，不参与检索）
"""
from typing import List, Optional

from ..db import episode_to_row
from ..models import Episode
from ..db import _u


def _row_to_episode(r):
    return Episode(
        id=r["id"], project_id=r["project_id"], task_id=r["task_id"],
        ts_start=r["ts_start"], ts_end=r["ts_end"], status=r["status"],
        goal=r["goal"], target=r["target"], user_hint=r["user_hint"],
        final_payload=r["final_payload"], trajectory=_u(r["trajectory_json"]) or [],
        human_verified=bool(r["human_verified"]), success_count=r["success_count"],
        created_at=r["created_at"],
    )


class EpisodeStore:
    def __init__(self, db):
        self.db = db

    def insert(self, e: Episode):
        self.db.execute(
            "INSERT OR REPLACE INTO episodes(id, project_id, task_id, ts_start, ts_end, status,"
            " goal, target, user_hint, final_payload, trajectory_json, human_verified, success_count,"
            " created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            tuple(episode_to_row(e).values()),
        )
        return e

    def get(self, eid: str) -> Optional[Episode]:
        rows = self.db.query("SELECT * FROM episodes WHERE id=?", (eid,))
        return _row_to_episode(rows[0]) if rows else None

    def delete(self, eid: str):
        self.db.execute("DELETE FROM episodes WHERE id=?", (eid,))

    def list_all(self, limit: int = 100):
        return [_row_to_episode(r) for r in self.db.query(
            "SELECT * FROM episodes ORDER BY created_at DESC LIMIT ?", (limit,))]

    def count(self) -> int:
        return self.db.query("SELECT COUNT(*) AS n FROM episodes")[0]["n"]
