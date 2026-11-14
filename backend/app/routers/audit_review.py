"""审计复核队列接口：独立于原始查询审计日志，单独提供复核队列视图。

- POST /api/audit-review/queues/generate：按审计窗口生成复核队列（同窗口幂等）
- GET  /api/audit-review/queues：查看所有窗口的复核队列
- GET  /api/audit-review/queues/{window}：查看单个窗口的队列证据
- POST /api/audit-review/review：复核单条审计记录
- GET  /api/audit-review/duration-summary：查询耗时汇总（供查询优化建议读取）
- POST /api/audit-review/metric-events：审计批次写入耗时事件（首个成功事件为准）
- GET  /api/audit-review/metric-events：读取耗时事件流（含旧耗时快照）
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from app.schemas import ActionResult
from app.services.audit_review import DEFAULT_WINDOW, AuditReviewService

router = APIRouter(prefix="/api/audit-review", tags=["审计复核队列"])

service = AuditReviewService()


class MetricEventPayload(BaseModel):
    """一个审计批次上报的耗时事件集合。"""

    batch_id: str | None = None
    events: list[dict[str, Any]] = Field(default_factory=list)


class ReviewPayload(BaseModel):
    """复核动作入参：记录编号必填，窗口与备注可选。"""

    record_no: str
    window: str | None = DEFAULT_WINDOW
    remark: str | None = None


@router.post("/queues/generate")
def generate_queues(window: str | None = Query(default=None, description="审计窗口，如 2026-09")) -> dict[str, Any]:
    """生成审计复核队列；重复生成同一窗口只返回已存在的那一份队列。"""
    return service.generate_queues(window)


@router.get("/queues")
def list_queue_windows() -> dict[str, Any]:
    """列出所有审计窗口的复核队列概况。"""
    windows = service.list_queue_windows()
    return {"total": len(windows), "items": windows}


@router.get("/queues/{window}")
def get_queue(window: str) -> dict[str, Any]:
    """查看单个审计窗口的复核队列，证据按执行耗时/扫描量排列。"""
    queue = service.get_queue(window)
    if queue is None:
        return {"message": f"审计窗口 {window} 尚未生成复核队列", "queues": []}
    return queue


@router.post("/review", response_model=ActionResult)
def review_item(payload: ReviewPayload) -> ActionResult:
    """复核队列中的单条记录；未复核记录始终保持「待复核」，不会显示为完成。"""
    item, message = service.review_item(
        payload.record_no.strip(),
        window=payload.window,
        remark=payload.remark,
    )
    if item is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=item)


@router.get("/duration-summary")
def duration_summary(window: str | None = Query(default=None, description="审计窗口，如 2026-09")) -> dict[str, Any]:
    """来源明确的查询耗时汇总，查询优化建议与运营概览共用此口径。"""
    return service.duration_summary(window)


@router.post("/metric-events")
def ingest_metric_events(payload: MetricEventPayload) -> dict[str, Any]:
    """审计批次并发写入耗时事件：同一记录以首个成功事件为权威快照，其余事件留痕可读。"""
    if not payload.events:
        return {"ok": False, "message": "events 为空，没有可写入的耗时事件"}
    result = service.ingest_metric_events(payload.events, batch_id=payload.batch_id)
    result["ok"] = True
    return result


@router.get("/metric-events")
def list_metric_events(
    record_no: str | None = Query(default=None, description="按记录编号过滤耗时事件"),
) -> dict[str, Any]:
    """读取耗时事件流，被抢占的旧耗时快照同样保留、可继续读取。"""
    items = service.list_metric_events(record_no=record_no)
    return {"total": len(items), "items": items}
