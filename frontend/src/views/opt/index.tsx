import { useCallback, useEffect, useMemo, useState } from 'react'

import { fetchJson, request } from '@/api/client'

const ENDPOINT = '/api/opt'
const columns = [
  "建议编号",
  "目标查询",
  "优化类型",
  "当前耗时",
  "预计提速",
  "优化方案",
  "执行状态",
  "建议时间"
]
const actions = [
  "采纳建议",
  "标记执行",
  "关闭建议"
]
const statuses = [
  "待采纳",
  "已采纳",
  "已执行",
  "已关闭"
]
const stats = [
  {
    "label": "优化建议总数",
    "value": 0
  },
  {
    "label": "已采纳建议",
    "value": 0
  },
  {
    "label": "已执行建议",
    "value": 0
  }
]

type Row = Record<string, string | number | null>

type AuditDurationSummary = {
  审计窗口: string
  数据来源: string
  记录数: number
  待复核数: number
  已复核数: number
  总耗时: string
  平均耗时: string
  最大耗时: string
  总扫描行数: number
  总返回行数: number
  明细: { 记录编号: string; 执行耗时: string; 扫描行数: number; 复核状态: string; 队列: string }[]
}

export default function OptView() {
  const [rows, setRows] = useState<Row[]>([])
  const [total, setTotal] = useState(0)
  const [errorMessage, setErrorMessage] = useState('')
  const [filters, setFilters] = useState<Record<string, string>>({})
  const [durationSummary, setDurationSummary] = useState<AuditDurationSummary | null>(null)
  const filterFields = useMemo(() => columns.slice(0, 3), [])

  const reload = useCallback(async () => {
    setErrorMessage('')
    const query = new URLSearchParams(filters).toString()
    try {
      const response = await request(`${ENDPOINT}?${query}`)
      if (!response.ok) {
        throw new Error('优化建议列表读取失败')
      }
      const payload = await response.json()
      setRows(payload.items ?? [])
      setTotal(payload.total ?? 0)
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '查询优化建议列表读取失败')
    }
  }, [filters])

  useEffect(() => {
    void reload()
  }, [reload])

  useEffect(() => {
    // 优化建议直接读取审计复核队列的查询耗时汇总，提速结论对照权威耗时验证。
    fetchJson<AuditDurationSummary>('/api/opt/audit-duration-summary')
      .then(setDurationSummary)
      .catch(() => setDurationSummary(null))
  }, [])

  async function runAction(action: string, row: Row) {
    setErrorMessage('')
    try {
      const response = await request(`${ENDPOINT}/${row.id}/actions`, {
        method: 'POST',
        body: JSON.stringify({ action }),
      })
      if (!response.ok) {
        throw new Error('查询优化建议动作未生效，请稍后重试')
      }
      await reload()
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '查询优化建议操作失败')
    }
  }

  return (
    <section className="page" data-module="opt">
      <header className="page-head">
        <div>
          <h2>查询优化建议管理</h2>
          <p className="page-desc">维护查询优化的瓶颈分析、提速预估与方案记录，为查询优化建议提供可验证的数据工程流程。</p>
        </div>
        <div className="page-actions">
          <button className="btn primary" type="button" onClick={() => setErrorMessage('优化建议登记入口尚未接入审批流')}>
            登记优化建议
          </button>
          <button className="btn" type="button" onClick={() => window.open(`${ENDPOINT}/export`, '_blank')}>
            导出查询优化建议清单
          </button>
        </div>
      </header>

      <div className="stat-row">
        {stats.map((item) => (
          <article key={item.label} className="stat-card">
            <span className="stat-label">{item.label}</span>
            <strong className="stat-value">{item.value}</strong>
          </article>
        ))}
      </div>

      {durationSummary && (
        <div className="queue-block">
          <div className="queue-head">
            <h3>查询耗时汇总（读取自审计复核队列）</h3>
            <span className="queue-meta">窗口 {durationSummary.审计窗口} · 用于验证提速结论</span>
          </div>
          <p className="source-note">来源：{durationSummary.数据来源}</p>
          <div className="stat-row">
            <article className="stat-card">
              <span className="stat-label">样本记录数</span>
              <strong className="stat-value">{durationSummary.记录数}</strong>
            </article>
            <article className="stat-card">
              <span className="stat-label">待复核（未完成）</span>
              <strong className="stat-value">{durationSummary.待复核数}</strong>
            </article>
            <article className="stat-card">
              <span className="stat-label">总耗时 / 平均 / 最大</span>
              <strong className="stat-value">
                {durationSummary.总耗时} / {durationSummary.平均耗时} / {durationSummary.最大耗时}
              </strong>
            </article>
          </div>
          <table className="data-table">
            <thead>
              <tr><th>记录编号</th><th>当前执行耗时</th><th>扫描行数</th><th>所属队列</th><th>复核状态</th></tr>
            </thead>
            <tbody>
              {durationSummary.明细.map((item) => (
                <tr key={item.记录编号}>
                  <td>{item.记录编号}</td>
                  <td>{item.执行耗时}</td>
                  <td>{item.扫描行数.toLocaleString('zh-CN')}</td>
                  <td><span className={`badge ${item.队列}`}>{item.队列}</span></td>
                  <td>
                    <span className={item.复核状态 === '已复核' ? 'badge reviewed' : 'badge pending'}>
                      {item.复核状态}
                    </span>
                  </td>
                </tr>
              ))}
              {durationSummary.明细.length === 0 && (
                <tr><td className="empty-state" colSpan={5}>当前窗口复核队列暂无记录</td></tr>
              )}
            </tbody>
          </table>
        </div>
      )}

      <form className="filter-bar" onSubmit={(event) => { event.preventDefault(); void reload() }}>
        {filterFields.map((field) => (
          <label key={field} className="filter-item">
            <span>{field}</span>
            <input
              value={filters[field] ?? ''}
              placeholder={`按${field}检索`}
              onChange={(event) => setFilters((prev) => ({ ...prev, [field]: event.target.value }))}
            />
          </label>
        ))}
        <button className="btn" type="submit">查询</button>
        <button className="btn ghost" type="button" onClick={() => setFilters({})}>重置条件</button>
      </form>

      <table className="data-table">
        <thead>
          <tr>
            {columns.map((column) => <th key={column}>{column}</th>)}
            <th>可执行动作</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={String(row.id)}>
              {columns.map((column) => <td key={column}>{row[column] ?? '—'}</td>)}
              <td className="row-actions">
                {actions.map((action) => (
                  <button key={action} className="link" type="button" onClick={() => void runAction(action, row)}>
                    {action}
                  </button>
                ))}
              </td>
            </tr>
          ))}
          {rows.length === 0 && (
            <tr>
              <td className="empty-state" colSpan={columns.length + 1}>暂无查询优化建议数据，可先登记优化建议</td>
            </tr>
          )}
        </tbody>
      </table>

      <footer className="page-foot">
        <span>共 {total} 条查询优化建议记录</span>
        {errorMessage && <span className="error-text">{errorMessage}</span>}
      </footer>
    </section>
  )
}
