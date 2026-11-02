# -*- coding: utf-8 -*-
"""
backend.memory · 经验记忆存储层（Episode / Gold / Pattern / ErrorFix）

使用：
    from backend.memory.service import MemoryService
    svc = MemoryService()                      # 默认 data/memory.db + mock 向量
    svc.insert_pattern(Pattern(...))
    svc.search_patterns("堆叠注入 sql_mode", top_k=3)
"""
from .models import Episode, ErrorFix, Gold, Pattern
from .review import ReviewResult, ReviewService
from .service import InsertResult, MemoryService

__all__ = ["MemoryService", "InsertResult", "Episode", "Gold", "Pattern", "ErrorFix",
           "ReviewService", "ReviewResult"]
