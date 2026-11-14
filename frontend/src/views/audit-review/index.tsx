import { useCallback, useEffect, useMemo, useState } from 'react'

import { request } from '@/api/client'

const ENDPOINT = '/api/audit-review'
const DEFAULT_WINDOW = '2026-09'

type QueueItem = {
  item_id: number
  记录编号: string
  查询语句: string
  执行人: string
  执行耗时: string
  duration_ms: number
  扫描行数: number
  返回行数: number
  队列: string
  复核状态: string
  待复核依据: string
  指标来源: string
  来源事件: number | null
  快照时间: string
  复核时间: string | null
  复核备注: string | null
}

type QueueBucket = {
  queue: string
  队列名称: string
  入队阈值: string
  total: number
  pending: number
  reviewed: number
  items: QueueItem[]
}

type QueueRecord = {
  id: number
  window: string
  审计窗口: string
  generated_at: string
  queues: QueueBucket[]
  skipped: { 记录编号: string; 原因: string }[]
}

type Summary = {
  审计窗口: string
  数据来源: string
  队列是否已生成: boolean
  记录数: number
  待复核数: number
  已复核数: number
  总耗时: string
  平均耗时: string
  最大耗时: string
  总扫描行数: number
  总返回行数: number
}

type MetricEvent = {
  id: number
  批次编号: string
  记录编号: string
  执行耗时: string
  扫描行数: number
  返回行数: number
  accepted: boolean
  reason: string
  created_at: string
}

const queueClass: Record<string, string> = {
  'scan-heavy': 'badge scan-heavy',
  slow: 'badge slow',
  'large-result': 'badge large-result',
}

function formatNumber(value: number): string {
  return value.toLocaleString('zh-CN')
}

export default function AuditReviewView() {
  const [windowKey, setWindowKey] = useState(DEFAULT_WINDOW)
  const [queueRecord, setQueueRecord] = useState<QueueRecord | null>(null)
  const [summary, setSummary] = useState<Summary | null>(null)
  const [events, setEvents] = useState<MetricEvent[]>([])
  const [errorMessage, setErrorMessage] = useState('')
  const [notice, setNotice] = useState('')

  const load = useCallback(async (window: string) => {
    setErrorMessage('')
    try {
      const [queueRes, summaryRes, eventsRes] = await Promise.all([
        request(`${ENDPOINT}/queues/${encodeURIComponent(window)}`),
        request(`${ENDPOINT}/duration-summary?window=${encodeURIComponent(window)}`),
        request(`${ENDPOINT}/metric-events`),
      ])
      if (!queueRes.ok || !summaryRes.ok || !eventsRes.ok) {
        throw new Error('审计复核队列读取失败')
      }
      const queuePayload = (await queueRes.json()) as QueueRecord & { message?: string }
      // 无队列时接口返回 { message, queues: [] }，用 id 区分是否为真正的队列记录。
      setQueueRecord(queuePayload.id ? queuePayload : null)
      setSummary(await summaryRes.json())
      const eventPayload = (await eventsRes.json()) as { items: MetricEvent[] }
      setEvents(eventPayload.items ?? [])
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '审计复核队列读取失败')
    }
  }, [])

  useEffect(() => {
    void load(windowKey)
  }, [load, windowKey])

  const allItems = useMemo(
    () => queueRecord?.queues.flatMap((bucket) => bucket.items) ?? [],
    [queueRecord],
  )

  async function generateQueue() {
    setErrorMessage('')
    setNotice('')
    try {
      const response = await request(
        `${ENDPOINT}/queues/generate?window=${encodeURIComponent(windowKey)}`,
        { method: 'POST' },
      )
      if (!response.ok) {
        throw new Error('复核队列生成失败')
      }
      const payload = (await response.json()) as QueueRecord
      setNotice(`审计窗口 ${payload.审计窗口} 的复核队列只保留一份（队列记录 #${payload.id}）`)
      await load(windowKey)
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '复核队列生成失败')
    }
  }

  async function reviewItem(item: QueueItem) {
    setErrorMessage('')
    setNotice('')
    try {
      const response = await request(`${ENDPOINT}/review`, {
        method: 'POST',
        body: JSON.stringify({ record_no: item.记录编号, window: windowKey }),
      })
      const payload = await response.json()
      if (!response.ok || payload.ok === false) {
        throw new Error(payload.message ?? '复核操作未生效')
      }
      setNotice(payload.message)
      await load(windowKey)
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '复核操作失败')
    }
  }

  const summaryCards = summary
    ? [
        { label: '队列记录数', value: String(summary.记录数) },
        { label: '待复核（未完成）', value: String(summary.待复核数) },
        { label: '已复核', value: String(summary.已复核数) },
        { label: '总耗时', value: summary.总耗时 },
        { label: '平均耗时', value: summary.平均耗时 },
        { label: '最大耗时', value: summary.最大耗时 },
      ]
    : []

  return (
    <section className="page" data-module="audit-review">
      <header className="page-head">
        <div>
          <h2>审计复核队列</h2>
          <p className="page-desc">
            按执行耗时、扫描行数与返回行数分组的独立复核视图：每条记录都附待复核依据与指标来源，
            未复核记录不会显示为完成。
          </p>
        </div>
        <div className="page-actions">
          <label className="filter-item">
            <span>审计窗口</span>
            <input value={windowKey} onChange={(event) => setWindowKey(event.target.value.trim())} />
          </label>
          <button className="btn primary" type="button" onClick={() => void generateQueue()}>
            生成 / 刷新复核队列
          </button>
        </div>
      </header>

      {summary && (
        <>
          <p className="source-note">
            查询耗时汇总来源：{summary.数据来源}（窗口 {summary.审计窗口}）
          </p>
          <div className="stat-row">
            {summaryCards.map((card) => (
              <article key={card.label} className="stat-card">
                <span className="stat-label">{card.label}</span>
                <strong className="stat-value">{card.value}</strong>
              </article>
            ))}
          </div>
        </>
      )}

      {notice && <p className="notice-text">{notice}</p>}
      {errorMessage && <p className="error-text">{errorMessage}</p>}

      {!queueRecord && (
        <p className="empty-state">窗口 {windowKey} 尚未生成复核队列，点击右上角按钮生成。</p>
      )}

      {queueRecord?.queues.map((bucket) => (
        <div key={bucket.queue} className="queue-block">
          <div className="queue-head">
            <h3>
              <span className={queueClass[bucket.queue]}>{bucket.queue}</span>
              {bucket.队列名称}
            </h3>
            <span className="queue-meta">
              {bucket.入队阈值} · 共 {bucket.total} 条 · 待复核 {bucket.pending} 条 · 已复核 {bucket.reviewed} 条
            </span>
          </div>
          <table className="data-table">
            <thead>
              <tr>
                <th>记录编号</th>
                <th>查询语句 / 执行人</th>
                <th>执行耗时 ↓</th>
                <th>扫描行数 ↓</th>
                <th>返回行数</th>
                <th>复核状态</th>
                <th>待复核依据与指标来源</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              {bucket.items.map((item) => (
                <tr key={String(item.item_id)} className={item.复核状态 === '已复核' ? 'row-reviewed' : 'row-pending'}>
                  <td>{item.记录编号}</td>
                  <td>
                    <code className="sql-cell">{item.查询语句}</code>
                    <span className="operator-cell">{item.执行人}</span>
                  </td>
                  <td>{item.执行耗时}</td>
                  <td>{formatNumber(item.扫描行数)}</td>
                  <td>{formatNumber(item.返回行数)}</td>
                  <td>
                    <span className={item.复核状态 === '已复核' ? 'badge reviewed' : 'badge pending'}>
                      {item.复核状态}
                    </span>
                  </td>
                  <td className="basis-cell">
                    <span>{item.待复核依据}</span>
                    <small className="source-cell">来源：{item.指标来源}</small>
                  </td>
                  <td>
                    {item.复核状态 === '待复核' ? (
                      <button className="link" type="button" onClick={() => void reviewItem(item)}>
                        标记已复核
                      </button>
                    ) : (
                      <span className="muted-text">
                        已完成{item.复核备注 ? `：${item.复核备注}` : ''}
                      </span>
                    )}
                  </td>
                </tr>
              ))}
              {bucket.items.length === 0 && (
                <tr>
                  <td className="empty-state" colSpan={8}>本窗口暂无记录进入{bucket.队列名称}</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      ))}

      {queueRecord && queueRecord.skipped.length > 0 && (
        <div className="queue-block">
          <div className="queue-head">
            <h3>未入队记录</h3>
            <span className="queue-meta">未达到复核阈值或指标无法解析，不计入完成量</span>
          </div>
          <table className="data-table">
            <thead>
              <tr><th>记录编号</th><th>未入队原因</th></tr>
            </thead>
            <tbody>
              {queueRecord.skipped.map((row) => (
                <tr key={row.记录编号}>
                  <td>{row.记录编号}</td>
                  <td className="muted-text">{row.原因}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="queue-block">
        <div className="queue-head">
          <h3>耗时事件流</h3>
          <span className="queue-meta">同一记录以首个成功事件为权威快照，被抢占的旧快照继续可读</span>
        </div>
        <table className="data-table">
          <thead>
            <tr>
              <th>#</th><th>批次</th><th>记录编号</th><th>执行耗时</th><th>扫描行数</th>
              <th>返回行数</th><th>事件状态</th><th>说明</th>
            </tr>
          </thead>
          <tbody>
            {events.map((event) => (
              <tr key={String(event.id)}>
                <td>{event.id}</td>
                <td>{event.批次编号}</td>
                <td>{event.记录编号}</td>
                <td>{event.执行耗时}</td>
                <td>{formatNumber(event.扫描行数)}</td>
                <td>{formatNumber(event.返回行数)}</td>
                <td>
                  <span className={event.accepted ? 'badge reviewed' : 'badge pending'}>
                    {event.accepted ? '权威快照' : '旧快照留痕'}
                  </span>
                </td>
                <td className="muted-text">{event.reason}</td>
              </tr>
            ))}
            {events.length === 0 && (
              <tr>
                <td className="empty-state" colSpan={8}>暂无耗时事件，审计批次可通过 /api/audit-review/metric-events 写入</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      <footer className="page-foot">
        <span>队列内共 {allItems.length} 条证据，按执行耗时与扫描量降序排列</span>
      </footer>
    </section>
  )
}
