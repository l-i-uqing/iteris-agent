# -*- coding: utf-8 -*-
"""
db.py · SQLite 存储层（data/memory.db）

分工（按已确认选型）：
  SQLite 管“精确、事务、元数据”：Gold 指纹唯一索引 / Episode 审计 / 计数与去重状态；
  Pattern / ErrorFix 的 embedding 以 JSON 文本列持久化，检索时全表加载后内存余弦计算
  （数据量 <1 万条时零依赖、毫秒级；接口抽象便于后续替换向量库）。
"""
import json
import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS episodes(
  id TEXT PRIMARY KEY,
  project_id TEXT, task_id TEXT, ts_start INTEGER, ts_end INTEGER,
  status TEXT, goal TEXT, target TEXT, user_hint TEXT, final_payload TEXT,
  trajectory_json TEXT,
  human_verified INTEGER, success_count INTEGER, created_at INTEGER
);
CREATE TABLE IF NOT EXISTS gold(
  id TEXT PRIMARY KEY,
  source_episode TEXT,
  fingerprint_json TEXT,
  signature_hash TEXT UNIQUE,
  payload TEXT,
  hit_count INTEGER, last_hit INTEGER,
  human_verified INTEGER, success_count INTEGER, created_at INTEGER
);
CREATE TABLE IF NOT EXISTS patterns(
  id TEXT PRIMARY KEY,
  title TEXT, cat TEXT, vuln_type TEXT, remediation TEXT, abstract TEXT,
  steps_json TEXT,
  embedding_json TEXT,
  hit_count INTEGER, version INTEGER,
  source_episodes_json TEXT,
  human_verified INTEGER, success_count INTEGER, created_at INTEGER
);
CREATE TABLE IF NOT EXISTS error_fixes(
  id TEXT PRIMARY KEY,
  source_episodes_json TEXT,
  error_type TEXT, error_signature TEXT, fix_strategy TEXT,
  applies_to_json TEXT,
  embedding_json TEXT,
  hit_count INTEGER,
  human_verified INTEGER, success_count INTEGER, created_at INTEGER
);
CREATE INDEX IF NOT EXISTS idx_gold_hash ON gold(signature_hash);
CREATE TABLE IF NOT EXISTS insights(
  id TEXT PRIMARY KEY,
  app_type TEXT, tech_stack_json TEXT,
  feature_points_json TEXT, mindset TEXT,
  source_episodes_json TEXT,
  embedding_json TEXT,
  hit_count INTEGER,
  human_verified INTEGER, success_count INTEGER, created_at INTEGER
);
CREATE TABLE IF NOT EXISTS vuln_graph(
  id TEXT PRIMARY KEY,
  vuln_type TEXT UNIQUE,
  trigger TEXT,
  technique_json TEXT,
  remediation TEXT,
  cve_id TEXT,
  source_patterns_json TEXT,
  source_episodes_json TEXT,
  confidence REAL,
  human_verified INTEGER,
  success_count INTEGER,
  created_at INTEGER,
  updated_at INTEGER
);
CREATE TABLE IF NOT EXISTS pending_review(
  id TEXT PRIMARY KEY,
  kind TEXT,                       -- pattern | error_fix
  payload_json TEXT,               -- 条目内容（模型 JSON）
  reason TEXT,                     -- 为何进待审（置信度低等）
  confidence REAL,
  created_at INTEGER
);
CREATE TABLE IF NOT EXISTS recall_logs(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  project_id TEXT,
  phase TEXT,                      -- pre_solve | error_fix
  query TEXT,                      -- 检索用文本（题目特征 / 报错原文）
  kind TEXT,                       -- pattern | error_fix | gold
  hit_ids TEXT,                    -- 命中的经验 id（JSON 数组）
  hit_count INTEGER,
  ts INTEGER
);
"""


def _j(v):
    return json.dumps(v, ensure_ascii=False) if v is not None else None


def _u(s):
    return json.loads(s) if s else None


class MemoryDB:
    def __init__(self, db_path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row

    def init_schema(self):
        self.conn.executescript(SCHEMA)
        # 迁移：老库 patterns 表补 vuln_type / remediation 列
        cols = [r[1] for r in self.conn.execute("PRAGMA table_info(patterns)").fetchall()]
        if "vuln_type" not in cols:
            self.conn.execute("ALTER TABLE patterns ADD COLUMN vuln_type TEXT DEFAULT ''")
        if "remediation" not in cols:
            self.conn.execute("ALTER TABLE patterns ADD COLUMN remediation TEXT DEFAULT ''")
        self.conn.commit()

    def execute(self, sql, params=()):
        cur = self.conn.execute(sql, params)
        self.conn.commit()
        return cur

    def query(self, sql, params=()):
        return self.conn.execute(sql, params).fetchall()

    def close(self):
        try:
            self.conn.close()
        except Exception:
            pass


# ---------- 行 ↔ 模型 转换 ----------

def episode_to_row(e):
    return {
        "id": e.id, "project_id": e.project_id, "task_id": e.task_id,
        "ts_start": e.ts_start, "ts_end": e.ts_end, "status": e.status,
        "goal": e.goal, "target": e.target, "user_hint": e.user_hint,
        "final_payload": e.final_payload, "trajectory_json": _j(e.trajectory),
        "human_verified": int(e.human_verified), "success_count": e.success_count,
        "created_at": e.created_at,
    }


def gold_to_row(g):
    return {
        "id": g.id, "source_episode": g.source_episode,
        "fingerprint_json": _j(g.fingerprint),
        "signature_hash": g.signature_hash,
        "payload": g.payload, "hit_count": g.hit_count, "last_hit": g.last_hit,
        "human_verified": int(g.human_verified), "success_count": g.success_count,
        "created_at": g.created_at,
    }


def pattern_to_row(p):
    return {
        "id": p.id, "title": p.title, "cat": p.cat, "vuln_type": p.vuln_type,
        "remediation": p.remediation, "abstract": p.abstract,
        "steps_json": _j(p.steps), "embedding_json": _j(p.embedding),
        "hit_count": p.hit_count, "version": p.version,
        "source_episodes_json": _j(p.source_episodes),
        "human_verified": int(p.human_verified), "success_count": p.success_count,
        "created_at": p.created_at,
    }


def errorfix_to_row(e):
    return {
        "id": e.id, "source_episodes_json": _j(e.source_episodes),
        "error_type": e.error_type, "error_signature": e.error_signature,
        "fix_strategy": e.fix_strategy, "applies_to_json": _j(e.applies_to),
        "embedding_json": _j(e.embedding), "hit_count": e.hit_count,
        "human_verified": int(e.human_verified), "success_count": e.success_count,
        "created_at": e.created_at,
    }


def row_to_gold(r):
    from .models import Gold
    return Gold(
        id=r["id"], source_episode=r["source_episode"],
        fingerprint=_u(r["fingerprint_json"]) or {},
        payload=r["payload"], hit_count=r["hit_count"], last_hit=r["last_hit"],
        human_verified=bool(r["human_verified"]), success_count=r["success_count"],
        created_at=r["created_at"],
    )


def row_to_pattern(r):
    from .models import Pattern
    return Pattern(
        id=r["id"], title=r["title"], cat=r["cat"],
        vuln_type=r["vuln_type"] if "vuln_type" in r.keys() else "",
        remediation=r["remediation"] if "remediation" in r.keys() else "",
        abstract=r["abstract"],
        steps=_u(r["steps_json"]) or [], embedding=_u(r["embedding_json"]) or [],
        hit_count=r["hit_count"], version=r["version"],
        source_episodes=_u(r["source_episodes_json"]) or [],
        human_verified=bool(r["human_verified"]), success_count=r["success_count"],
        created_at=r["created_at"],
    )


def insight_to_row(i):
    return {
        "id": i.id, "app_type": i.app_type, "tech_stack_json": _j(i.tech_stack),
        "feature_points_json": _j(i.feature_points), "mindset": i.mindset,
        "source_episodes_json": _j(i.source_episodes),
        "embedding_json": _j(i.embedding), "hit_count": i.hit_count,
        "human_verified": int(i.human_verified), "success_count": i.success_count,
        "created_at": i.created_at,
    }


def row_to_insight(r):
    from .models import Insight
    return Insight(
        id=r["id"], app_type=r["app_type"], tech_stack=_u(r["tech_stack_json"]) or [],
        feature_points=_u(r["feature_points_json"]) or [], mindset=r["mindset"],
        source_episodes=_u(r["source_episodes_json"]) or [],
        embedding=_u(r["embedding_json"]) or [], hit_count=r["hit_count"],
        human_verified=bool(r["human_verified"]), success_count=r["success_count"],
        created_at=r["created_at"],
    )


def row_to_errorfix(r):
    from .models import ErrorFix
    return ErrorFix(
        id=r["id"], source_episodes=_u(r["source_episodes_json"]) or [],
        error_type=r["error_type"], error_signature=r["error_signature"],
        fix_strategy=r["fix_strategy"], applies_to=_u(r["applies_to_json"]) or [],
        embedding=_u(r["embedding_json"]) or [], hit_count=r["hit_count"],
        human_verified=bool(r["human_verified"]), success_count=r["success_count"],
        created_at=r["created_at"],
    )
