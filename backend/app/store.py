"""内存数据仓库：给每个业务模块准备一份可筛选、可流转的示例数据。

真实项目里这里会换成数据库访问层；当前实现只依赖标准库，保证克隆下来就能起。
审计复核队列与耗时事件另外维护两张独立表，并通过同一把可重入锁串行化写入，
保证两个审计批次并发写同一条记录时，只有首个成功事件能成为权威快照。
"""
from __future__ import annotations

import threading
from typing import Any

from app.seed import SEED_ROWS

# 审计复核相关的独立表名，避免和原始审计日志混在一起。
REVIEW_QUEUE_TABLE = "audit_review_queue"
METRIC_EVENT_TABLE = "audit_metric_event"


class Store:
    def __init__(self) -> None:
        self._tables: dict[str, list[dict[str, Any]]] = {
            name: [dict(row) for row in rows] for name, rows in SEED_ROWS.items()
        }
        # 复核队列与耗时事件不属于 seed 数据，初始化即建空表。
        self._tables[REVIEW_QUEUE_TABLE] = []
        self._tables[METRIC_EVENT_TABLE] = []
        # 复核队列生成、事件写入都走这把锁；可重入允许服务层嵌套加锁。
        self.lock = threading.RLock()

    def module_names(self) -> list[str]:
        return sorted(self._tables)

    def rows(self, module: str) -> list[dict[str, Any]]:
        return self._tables.setdefault(module, [])

    def find(self, module: str, entry_id: int) -> dict[str, Any] | None:
        for row in self.rows(module):
            if int(row.get("id", 0)) == entry_id:
                return row
        return None

    def next_id(self, module: str) -> int:
        """在锁内取下一个自增主键，避免并发批次互相覆盖。"""
        with self.lock:
            rows = self.rows(module)
            return max((int(row.get("id", 0)) for row in rows), default=0) + 1

    def overview(self) -> dict[str, object]:
        internal_tables = {REVIEW_QUEUE_TABLE, METRIC_EVENT_TABLE}
        modules: list[dict[str, object]] = []
        for name in self.module_names():
            if name in internal_tables:
                continue
            rows = self.rows(name)
            modules.append({
                "name": name,
                "created": len(rows),
                "pending": sum(1 for row in rows if row.get("pending")),
                "abnormal": sum(1 for row in rows if row.get("abnormal")),
            })
        cards = [
            {"label": "业务模块", "value": len(modules)},
            {"label": "今日新增", "value": sum(int(item["created"]) for item in modules)},
            {"label": "待处理", "value": sum(int(item["pending"]) for item in modules)},
            {"label": "异常量", "value": sum(int(item["abnormal"]) for item in modules)},
        ]
        # 运营概览只呈现来源明确的查询耗时汇总，未复核记录不计入已完成量。
        audit_summary = self.audit_review_summary()
        return {
            "cards": cards,
            "modules": modules,
            "audit_review": audit_summary,
        }

    def audit_review_summary(self) -> dict[str, object]:
        """汇总审计复核队列与查询耗时，概览与优化建议共用同一份口径。"""
        # 延迟导入，避免 store 模块反向依赖服务层。
        from app.services.audit_review import AuditReviewService

        return AuditReviewService().duration_summary()



store = Store()
