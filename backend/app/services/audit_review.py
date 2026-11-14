"""审计复核队列业务规则。

职责：
1. 把查询审计日志按执行耗时、扫描行数、返回行数分组，生成 slow / scan-heavy /
   large-result 三条复核队列，每条队列里的记录都带「待复核依据」和复核状态。
2. 同一审计窗口重复生成只保留一份复核队列（幂等），队列项是不可变耗时快照，
   旧快照在队列重建后依旧可通过耗时事件表读取。
3. 两个审计批次并发写同一条记录的耗时事件时，以首个成功事件为准，后续事件只留痕、
   不覆盖权威快照。
4. 输出来源明确的查询耗时汇总，供运营概览与查询优化建议共用同一口径。
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from app.store import METRIC_EVENT_TABLE, REVIEW_QUEUE_TABLE, store

MODULE = "audit"

# 复核阈值（自行取舍后的口径，集中在这里便于后续调整）：
# - slow：执行耗时达到 800ms；
# - scan-heavy：扫描行数达到 100 万行（优先级高于 slow，避免同一条记录重复入队）；
# - large-result：返回行数达到 1 万行。
SLOW_DURATION_MS = 800
SCAN_HEAVY_ROWS = 1_000_000
LARGE_RESULT_ROWS = 10_000

# 队列顺序即页面与汇总里的展示顺序。
QUEUE_ORDER = ["scan-heavy", "slow", "large-result"]
QUEUE_LABELS = {
    "scan-heavy": "高扫描量队列",
    "slow": "慢查询队列",
    "large-result": "大结果集队列",
}
QUEUE_REASONS = {
    "scan-heavy": f"扫描行数达到 {SCAN_HEAVY_ROWS:,} 行阈值",
    "slow": f"执行耗时达到 {SLOW_DURATION_MS}ms 阈值",
    "large-result": f"返回行数达到 {LARGE_RESULT_ROWS:,} 行阈值",
}

REVIEW_PENDING = "待复核"
REVIEW_DONE = "已复核"
DEFAULT_WINDOW = "2026-09"

_DURATION_PATTERN = re.compile(r"^\s*([0-9]+(?:\.[0-9]+)?)\s*(ms|毫秒|s|秒)?\s*$", re.IGNORECASE)
_COUNT_PATTERN = re.compile(r"[0-9]+")


def parse_duration_ms(value: Any) -> int | None:
    """把 '820ms'、'1.4s'、'18毫秒' 等耗时文本统一解析成毫秒整数；无法识别返回 None。"""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return max(int(round(float(value))), 0)
    match = _DURATION_PATTERN.match(str(value))
    if not match:
        return None
    number = float(match.group(1))
    unit = (match.group(2) or "ms").lower()
    if unit in {"s", "秒"}:
        number *= 1000
    return max(int(round(number)), 0)


def parse_row_count(value: Any) -> int | None:
    """把扫描/返回行数解析成整数，兼容 '1,280,000 行' 这类带分隔符的文本。"""
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return max(value, 0)
    if isinstance(value, float):
        return max(int(round(value)), 0)
    digits = "".join(_COUNT_PATTERN.findall(str(value)))
    if not digits:
        return None
    return max(int(digits), 0)


def format_duration(ms: int | None) -> str:
    """把毫秒数渲染回可读耗时，保证汇总里每个数字都有来源说明。"""
    if ms is None:
        return "—"
    if ms >= 1000:
        return f"{ms / 1000:g}s"
    return f"{ms}ms"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class AuditReviewService:
    # ------------------------------------------------------------------ 耗时事件

    def ingest_metric_events(
        self,
        events: list[dict[str, Any]],
        *,
        batch_id: str | None = None,
    ) -> dict[str, Any]:
        """接收一个审计批次的耗时事件。

        全程持锁：同一记录编号的首个成功事件成为权威快照（accepted=True），
        并发或重复到达的事件只留痕（accepted=False、reason 说明被谁抢先），
        旧事件本身继续可读，不会被删除或改写。
        """
        batch = (batch_id or f"batch-{_now_iso()}").strip()
        results: list[dict[str, Any]] = []
        with store.lock:
            existing = store.rows(METRIC_EVENT_TABLE)
            canonical_by_record = {
                str(row["记录编号"]): row
                for row in existing
                if row.get("accepted")
            }
            for raw in events:
                record_no = str(raw.get("记录编号") or "").strip()
                duration_ms = parse_duration_ms(raw.get("执行耗时"))
                scanned = parse_row_count(raw.get("扫描行数"))
                returned = parse_row_count(raw.get("返回行数"))
                if not record_no or duration_ms is None or scanned is None or returned is None:
                    results.append({
                        "记录编号": record_no or None,
                        "accepted": False,
                        "reason": "缺少记录编号或无法解析执行耗时/扫描行数/返回行数",
                    })
                    continue
                event_id = store.next_id(METRIC_EVENT_TABLE)
                first_event = canonical_by_record.get(record_no)
                if first_event is not None:
                    # 首个成功事件已存在：保留本次事件作为旧耗时快照，但不更新权威值。
                    event = {
                        "id": event_id,
                        "批次编号": batch,
                        "记录编号": record_no,
                        "查询语句": str(raw.get("查询语句") or ""),
                        "执行人": str(raw.get("执行人") or ""),
                        "duration_ms": duration_ms,
                        "执行耗时": format_duration(duration_ms),
                        "扫描行数": scanned,
                        "返回行数": returned,
                        "accepted": False,
                        "reason": f"权威快照已由事件 #{first_event['id']}（批次 {first_event['批次编号']}）写入",
                        "created_at": _now_iso(),
                    }
                    existing.append(event)
                    results.append({
                        "记录编号": record_no,
                        "accepted": False,
                        "reason": event["reason"],
                        "event_id": event_id,
                    })
                    continue
                event = {
                    "id": event_id,
                    "批次编号": batch,
                    "记录编号": record_no,
                    "查询语句": str(raw.get("查询语句") or ""),
                    "执行人": str(raw.get("执行人") or ""),
                    "duration_ms": duration_ms,
                    "执行耗时": format_duration(duration_ms),
                    "扫描行数": scanned,
                    "返回行数": returned,
                    "accepted": True,
                    "reason": "首个成功事件，作为权威耗时快照",
                    "created_at": _now_iso(),
                }
                existing.append(event)
                canonical_by_record[record_no] = event
                results.append({
                    "记录编号": record_no,
                    "accepted": True,
                    "reason": event["reason"],
                    "event_id": event_id,
                })
        accepted = sum(1 for item in results if item["accepted"])
        return {
            "批次编号": batch,
            "received": len(results),
            "accepted": accepted,
            "rejected": len(results) - accepted,
            "results": results,
        }

    def list_metric_events(self, *, record_no: str | None = None) -> list[dict[str, Any]]:
        """读取耗时事件流（含被抢占的旧快照），按写入顺序返回。"""
        rows = store.rows(METRIC_EVENT_TABLE)
        if record_no:
            rows = [row for row in rows if str(row.get("记录编号")) == record_no]
        return [dict(row) for row in rows]

    def canonical_metrics(self) -> dict[str, dict[str, Any]]:
        """权威耗时快照：记录编号 -> 首个成功事件。"""
        return {
            str(row["记录编号"]): dict(row)
            for row in store.rows(METRIC_EVENT_TABLE)
            if row.get("accepted")
        }

    # ------------------------------------------------------------------ 复核队列

    def _metric_view_for(self, entry: dict[str, Any]) -> dict[str, Any] | None:
        """单条审计记录的指标视图：优先用权威事件，缺失时回落到原始审计日志。"""
        record_no = str(entry.get("记录编号") or "")
        canonical = self.canonical_metrics().get(record_no)
        if canonical is not None:
            return {
                "记录编号": record_no,
                "查询语句": canonical.get("查询语句") or entry.get("查询语句"),
                "执行人": canonical.get("执行人") or entry.get("执行人"),
                "duration_ms": canonical["duration_ms"],
                "执行耗时": canonical["执行耗时"],
                "扫描行数": canonical["扫描行数"],
                "返回行数": canonical["返回行数"],
                "指标来源": f"权威耗时事件 #{canonical['id']}（批次 {canonical['批次编号']}）",
                "来源事件": canonical["id"],
            }
        duration_ms = parse_duration_ms(entry.get("执行耗时"))
        scanned = parse_row_count(entry.get("扫描行数"))
        returned = parse_row_count(entry.get("返回行数"))
        if duration_ms is None or scanned is None or returned is None:
            return None
        return {
            "记录编号": record_no,
            "查询语句": entry.get("查询语句"),
            "执行人": entry.get("执行人"),
            "duration_ms": duration_ms,
            "执行耗时": format_duration(duration_ms),
            "扫描行数": scanned,
            "返回行数": returned,
            "指标来源": "原始查询审计日志（尚无耗时事件）",
            "来源事件": None,
        }

    @staticmethod
    def _classify(metric: dict[str, Any]) -> tuple[str | None, str]:
        """按阈值分组，scan-heavy 优先于 slow，保证一条记录只进入一条队列。"""
        if metric["扫描行数"] >= SCAN_HEAVY_ROWS:
            return "scan-heavy", QUEUE_REASONS["scan-heavy"]
        if metric["duration_ms"] >= SLOW_DURATION_MS:
            return "slow", QUEUE_REASONS["slow"]
        if metric["返回行数"] >= LARGE_RESULT_ROWS:
            return "large-result", QUEUE_REASONS["large-result"]
        return None, "未达到任何复核阈值"

    @staticmethod
    def _sort_queue(queue_name: str, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if queue_name == "slow":
            # 慢查询队列：按执行耗时从高到低排列证据，耗时相同再按记录编号。
            return sorted(items, key=lambda item: (-item["duration_ms"], item["记录编号"]))
        if queue_name == "scan-heavy":
            # 高扫描量队列：按扫描量从高到低，扫描量相同再看耗时。
            return sorted(
                items,
                key=lambda item: (-item["扫描行数"], -item["duration_ms"], item["记录编号"]),
            )
        return sorted(
            items,
            key=lambda item: (-item["返回行数"], -item["duration_ms"], item["记录编号"]),
        )

    def generate_queues(self, window: str | None = None) -> dict[str, Any]:
        """为一个审计窗口生成复核队列；同窗口重复调用只保留一份队列（幂等）。"""
        window_key = (window or DEFAULT_WINDOW).strip()
        with store.lock:
            for queue in store.rows(REVIEW_QUEUE_TABLE):
                if queue.get("window") == window_key:
                    return dict(queue)

            buckets: dict[str, list[dict[str, Any]]] = {name: [] for name in QUEUE_ORDER}
            skipped: list[dict[str, str]] = []
            for entry in store.rows(MODULE):
                executed_at = str(entry.get("执行时间") or "")
                if not executed_at.startswith(window_key):
                    continue
                metric = self._metric_view_for(entry)
                if metric is None:
                    skipped.append({
                        "记录编号": str(entry.get("记录编号") or ""),
                        "原因": "执行耗时/扫描行数/返回行数无法解析，缺少复核依据",
                    })
                    continue
                queue_name, reason = self._classify(metric)
                if queue_name is None:
                    skipped.append({"记录编号": metric["记录编号"], "原因": reason})
                    continue
                buckets[queue_name].append({
                    "记录编号": metric["记录编号"],
                    "查询语句": metric["查询语句"],
                    "执行人": metric["执行人"],
                    "执行耗时": metric["执行耗时"],
                    "duration_ms": metric["duration_ms"],
                    "扫描行数": metric["扫描行数"],
                    "返回行数": metric["返回行数"],
                    "队列": queue_name,
                    "复核状态": REVIEW_PENDING,
                    "待复核依据": reason,
                    "指标来源": metric["指标来源"],
                    "来源事件": metric["来源事件"],
                    "快照时间": _now_iso(),
                    "复核时间": None,
                    "复核备注": None,
                })

            queues: list[dict[str, Any]] = []
            item_seq = 0
            for name in QUEUE_ORDER:
                ordered = self._sort_queue(name, buckets[name])
                items = []
                for item in ordered:
                    item_seq += 1
                    items.append({"item_id": item_seq, **item})
                queues.append({
                    "queue": name,
                    "队列名称": QUEUE_LABELS[name],
                    "入队阈值": QUEUE_REASONS[name],
                    "total": len(items),
                    "pending": len(items),
                    "reviewed": 0,
                    "items": items,
                })

            record = {
                "id": store.next_id(REVIEW_QUEUE_TABLE),
                "window": window_key,
                "审计窗口": window_key,
                "generated_at": _now_iso(),
                "queues": queues,
                "skipped": skipped,
            }
            store.rows(REVIEW_QUEUE_TABLE).append(record)
            return dict(record)

    def list_queue_windows(self) -> list[dict[str, Any]]:
        """所有已生成的复核队列窗口，按生成时间倒序。"""
        rows = [
            {
                "id": row["id"],
                "window": row["window"],
                "审计窗口": row["审计窗口"],
                "generated_at": row["generated_at"],
                "队列数": len(row["queues"]),
                "记录数": sum(int(q["total"]) for q in row["queues"]),
                "待复核": sum(int(q["pending"]) for q in row["queues"]),
                "已复核": sum(int(q["reviewed"]) for q in row["queues"]),
            }
            for row in store.rows(REVIEW_QUEUE_TABLE)
        ]
        return sorted(rows, key=lambda row: row["generated_at"], reverse=True)

    def get_queue(self, window: str | None = None) -> dict[str, Any] | None:
        window_key = (window or DEFAULT_WINDOW).strip()
        for row in store.rows(REVIEW_QUEUE_TABLE):
            if row.get("window") == window_key:
                return dict(row)
        return None

    def review_item(
        self,
        record_no: str,
        *,
        window: str | None = None,
        remark: str | None = None,
    ) -> tuple[dict[str, Any] | None, str]:
        """把队列里的单条审计记录标记为已复核；未复核记录不会在任何地方显示为完成。"""
        window_key = (window or DEFAULT_WINDOW).strip()
        with store.lock:
            queue_record = self.get_queue(window_key)
            if queue_record is None:
                return None, f"审计窗口 {window_key} 尚未生成复核队列"
            for queue in queue_record["queues"]:
                for item in queue["items"]:
                    if item["记录编号"] == record_no:
                        if item["复核状态"] == REVIEW_DONE:
                            return item, f"{record_no} 已是已复核状态，无需重复操作"
                        item["复核状态"] = REVIEW_DONE
                        item["复核时间"] = _now_iso()
                        item["复核备注"] = remark
                        queue["reviewed"] = int(queue["reviewed"]) + 1
                        queue["pending"] = int(queue["pending"]) - 1
                        return item, f"{record_no} 已复核，来源依据：{item['待复核依据']}"
            return None, f"{record_no} 不在窗口 {window_key} 的复核队列中"

    # ------------------------------------------------------------------ 耗时汇总

    def duration_summary(self, window: str | None = None) -> dict[str, Any]:
        """来源明确的查询耗时汇总，运营概览与查询优化建议读同一份数据。"""
        window_key = (window or DEFAULT_WINDOW).strip()
        queue_record = self.get_queue(window_key)

        metrics: list[dict[str, Any]] = []
        if queue_record is not None:
            for queue in queue_record["queues"]:
                for item in queue["items"]:
                    metrics.append({
                        "记录编号": item["记录编号"],
                        "执行人": item["执行人"],
                        "duration_ms": item["duration_ms"],
                        "执行耗时": item["执行耗时"],
                        "扫描行数": item["扫描行数"],
                        "返回行数": item["返回行数"],
                        "队列": item["队列"],
                        "复核状态": item["复核状态"],
                        "指标来源": item["指标来源"],
                    })

        durations = [item["duration_ms"] for item in metrics]
        total = len(metrics)
        reviewed = sum(1 for item in metrics if item["复核状态"] == REVIEW_DONE)
        pending = total - reviewed
        summary = {
            "审计窗口": window_key,
            "数据来源": "审计复核队列快照（权威耗时事件优先，缺失时回落到原始查询审计日志）",
            "队列是否已生成": queue_record is not None,
            "记录数": total,
            "待复核数": pending,
            "已复核数": reviewed,
            # 未复核记录仍计入耗时样本，但单独标记，绝不显示为完成。
            "总耗时_ms": sum(durations),
            "总耗时": format_duration(sum(durations) if durations else None),
            "平均耗时_ms": int(round(sum(durations) / total)) if total else None,
            "平均耗时": format_duration(int(round(sum(durations) / total))) if total else "—",
            "最大耗时_ms": max(durations) if durations else None,
            "最大耗时": format_duration(max(durations) if durations else None),
            "总扫描行数": sum(item["扫描行数"] for item in metrics),
            "总返回行数": sum(item["返回行数"] for item in metrics),
            "队列汇总": [
                {
                    "队列": name,
                    "队列名称": QUEUE_LABELS[name],
                    "记录数": sum(1 for item in metrics if item["队列"] == name),
                    "待复核": sum(
                        1 for item in metrics
                        if item["队列"] == name and item["复核状态"] == REVIEW_PENDING
                    ),
                    "已复核": sum(
                        1 for item in metrics
                        if item["队列"] == name and item["复核状态"] == REVIEW_DONE
                    ),
                }
                for name in QUEUE_ORDER
            ],
            "明细": metrics,
        }
        return summary
