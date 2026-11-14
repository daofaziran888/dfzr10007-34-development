import { useEffect, useState } from 'react'

import { fetchJson } from '@/api/client'

type Overview = {
  cards: { label: string; value: number }[]
  modules: { name: string; created: number; pending: number; abnormal: number }[]
  audit_review?: AuditReviewSummary
}

type AuditReviewSummary = {
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
  队列汇总: { 队列: string; 队列名称: string; 记录数: number; 待复核: number; 已复核: number }[]
}

const fallbackCards = [{"label": "业务模块", "value": 0}, {"label": "今日新增", "value": 0}]
const fallbackModules = [{"name": "数据集市构建", "created": 0, "pending": 0, "abnormal": 0}, {"name": "自助SQL查询", "created": 0, "pending": 0, "abnormal": 0}, {"name": "拖拽可视化", "created": 0, "pending": 0, "abnormal": 0}, {"name": "看板协作管理", "created": 0, "pending": 0, "abnormal": 0}, {"name": "指标异动归因", "created": 0, "pending": 0, "abnormal": 0}, {"name": "分析模型沉淀", "created": 0, "pending": 0, "abnormal": 0}, {"name": "查询优化建议", "created": 0, "pending": 0, "abnormal": 0}, {"name": "数据故事编排", "created": 0, "pending": 0, "abnormal": 0}, {"name": "数据准备流水线", "created": 0, "pending": 0, "abnormal": 0}, {"name": "数据目录检索", "created": 0, "pending": 0, "abnormal": 0}, {"name": "数据采样管理", "created": 0, "pending": 0, "abnormal": 0}, {"name": "同环比分析", "created": 0, "pending": 0, "abnormal": 0}, {"name": "分析导出中心", "created": 0, "pending": 0, "abnormal": 0}, {"name": "分析告警规则", "created": 0, "pending": 0, "abnormal": 0}, {"name": "数据定时刷新", "created": 0, "pending": 0, "abnormal": 0}, {"name": "查询审计日志", "created": 0, "pending": 0, "abnormal": 0}]

export default function Overview() {
  const [cards, setCards] = useState<Overview['cards']>(fallbackCards)
  const [moduleRows, setModuleRows] = useState<Overview['modules']>(fallbackModules)
  const [auditReview, setAuditReview] = useState<AuditReviewSummary | null>(null)

  useEffect(() => {
    fetchJson<Overview>('/api/overview')
      .then((payload) => {
        setCards(payload.cards)
        setModuleRows(payload.modules)
        setAuditReview(payload.audit_review ?? null)
      })
      .catch(() => undefined)
  }, [])

  return (
    <section className="page">
      <header className="page-head">
        <div>
          <h2>运营概览</h2>
          <p className="page-desc">汇总各业务模块的关键指标，先看总量再看异常。</p>
        </div>
      </header>
      <div className="stat-row">
        {cards.map((card) => (
          <article key={card.label} className="stat-card">
            <span className="stat-label">{card.label}</span>
            <strong className="stat-value">{card.value}</strong>
          </article>
        ))}
      </div>

      {auditReview && (
        <div className="queue-block">
          <div className="queue-head">
            <h3>查询耗时汇总（来源：审计复核队列）</h3>
            <span className="queue-meta">窗口 {auditReview.审计窗口}</span>
          </div>
          <p className="source-note">{auditReview.数据来源}</p>
          <div className="stat-row">
            <article className="stat-card">
              <span className="stat-label">队列记录数</span>
              <strong className="stat-value">{auditReview.记录数}</strong>
            </article>
            <article className="stat-card">
              <span className="stat-label">待复核（未完成）</span>
              <strong className="stat-value">{auditReview.待复核数}</strong>
            </article>
            <article className="stat-card">
              <span className="stat-label">已复核</span>
              <strong className="stat-value">{auditReview.已复核数}</strong>
            </article>
            <article className="stat-card">
              <span className="stat-label">总耗时</span>
              <strong className="stat-value">{auditReview.总耗时}</strong>
            </article>
            <article className="stat-card">
              <span className="stat-label">平均耗时</span>
              <strong className="stat-value">{auditReview.平均耗时}</strong>
            </article>
            <article className="stat-card">
              <span className="stat-label">最大耗时</span>
              <strong className="stat-value">{auditReview.最大耗时}</strong>
            </article>
          </div>
          <table className="data-table">
            <thead>
              <tr><th>复核队列</th><th>记录数</th><th>待复核</th><th>已复核</th></tr>
            </thead>
            <tbody>
              {auditReview.队列汇总.map((row) => (
                <tr key={row.队列}>
                  <td>
                    <span className={`badge ${row.队列}`}>{row.队列}</span>
                    {row.队列名称}
                  </td>
                  <td>{row.记录数}</td>
                  <td>{row.待复核}</td>
                  <td>{row.已复核}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="page-foot">待复核记录保留在未完成口径内，不计入已复核量。</p>
        </div>
      )}

      <table className="data-table">
        <thead>
          <tr><th>业务模块</th><th>今日新增</th><th>待处理</th><th>异常量</th></tr>
        </thead>
        <tbody>
          {moduleRows.map((row) => (
            <tr key={row.name}>
              <td>{row.name}</td>
              <td>{row.created}</td>
              <td>{row.pending}</td>
              <td>{row.abnormal}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  )
}
