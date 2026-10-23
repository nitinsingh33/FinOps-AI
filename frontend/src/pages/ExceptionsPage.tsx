import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  AlertTriangle, Search, RefreshCw, Bot, ChevronLeft,
  ChevronRight, X, CheckCircle2, Clock, XCircle
} from 'lucide-react'
import {
  fetchExceptions, fetchException, investigateException,
  reviewException, fetchAuditTrail
} from '../api/client'
import { formatDate, formatCurrency, severityClass, reviewStatusClass } from '../lib/format'
import type { ExceptionDetail, ReconciliationException } from '../types'

const CATEGORIES = ['', 'amount_mismatch', 'missing_in_gateway', 'missing_in_payments', 'duplicate', 'fee_discrepancy', 'currency_mismatch', 'refund_mismatch', 'unmatched_refund', 'settlement_discrepancy']
const SEVERITIES = ['', 'critical', 'high', 'medium', 'low']
const STATUSES = ['', 'open', 'in_review', 'resolved', 'dismissed']
const GATEWAYS = ['', 'gateway_a', 'gateway_b']

export default function ExceptionsPage() {
  const queryClient = useQueryClient()
  const [filters, setFilters] = useState({ category: '', gateway: '', review_status: '', severity: '' })
  const [page, setPage] = useState(1)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [showModal, setShowModal] = useState(false)

  const { data, isLoading } = useQuery({
    queryKey: ['exceptions', filters, page],
    queryFn: () => fetchExceptions({ ...filters, page, page_size: 25 }),
    refetchInterval: 15_000,
  })

  const { data: detail, isLoading: detailLoading } = useQuery({
    queryKey: ['exception-detail', selectedId],
    queryFn: () => fetchException(selectedId!),
    enabled: !!selectedId && showModal,
  })

  const { data: auditData } = useQuery({
    queryKey: ['audit', selectedId],
    queryFn: () => fetchAuditTrail(selectedId!),
    enabled: !!selectedId && showModal,
  })

  const investigateMutation = useMutation({
    mutationFn: (id: string) => investigateException(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['exception-detail', selectedId] })
    },
  })

  const reviewMutation = useMutation({
    mutationFn: ({ id, action }: { id: string; action: string }) =>
      reviewException(id, { action, reviewer: 'analyst', notes: `Status set to ${action}` }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['exception-detail', selectedId] })
      queryClient.invalidateQueries({ queryKey: ['exceptions'] })
    },
  })

  const items: ReconciliationException[] = data?.items ?? []
  const total: number = data?.total ?? 0
  const totalPages = Math.ceil(total / 25)

  const openDetail = (id: string) => {
    setSelectedId(id)
    setShowModal(true)
  }

  const setFilter = (key: string, value: string) => {
    setFilters(prev => ({ ...prev, [key]: value }))
    setPage(1)
  }

  return (
    <div className="page-wrapper">
      <div className="page-header">
        <h1 className="page-title">Exceptions</h1>
        <p className="page-subtitle">Review, investigate and resolve reconciliation exceptions</p>
      </div>

      {/* Filters */}
      <div className="filters-bar">
        <div className="filter-group">
          <Search size={14} color="var(--color-text-muted)" />
        </div>
        <select className="form-select" style={{ width: 'auto' }} value={filters.category} onChange={e => setFilter('category', e.target.value)}>
          <option value="">All Categories</option>
          {CATEGORIES.filter(Boolean).map(c => <option key={c} value={c}>{c.replace(/_/g, ' ')}</option>)}
        </select>
        <select className="form-select" style={{ width: 'auto' }} value={filters.severity} onChange={e => setFilter('severity', e.target.value)}>
          <option value="">All Severities</option>
          {SEVERITIES.filter(Boolean).map(s => <option key={s} value={s}>{s}</option>)}
        </select>
        <select className="form-select" style={{ width: 'auto' }} value={filters.review_status} onChange={e => setFilter('review_status', e.target.value)}>
          <option value="">All Statuses</option>
          {STATUSES.filter(Boolean).map(s => <option key={s} value={s}>{s.replace('_', ' ')}</option>)}
        </select>
        <select className="form-select" style={{ width: 'auto' }} value={filters.gateway} onChange={e => setFilter('gateway', e.target.value)}>
          <option value="">All Gateways</option>
          {GATEWAYS.filter(Boolean).map(g => <option key={g} value={g}>{g === 'gateway_a' ? 'Gateway A' : 'Gateway B'}</option>)}
        </select>
        <button className="btn btn-ghost btn-sm" onClick={() => { setFilters({ category: '', gateway: '', review_status: '', severity: '' }); setPage(1) }}>
          <X size={13} /> Clear
        </button>
        <button className="btn btn-ghost btn-sm" onClick={() => queryClient.invalidateQueries({ queryKey: ['exceptions'] })}>
          <RefreshCw size={13} />
        </button>
        <span style={{ marginLeft: 'auto', fontSize: 13, color: 'var(--color-text-muted)' }}>
          {total} exceptions
        </span>
      </div>

      {/* Table */}
      <div className="card">
        <div className="table-container" style={{ border: 'none', borderRadius: 0 }}>
          <table className="data-table">
            <thead>
              <tr>
                <th>Category</th>
                <th>Severity</th>
                <th>Gateway</th>
                <th>Currency</th>
                <th>Amount at Stake</th>
                <th>Difference</th>
                <th>Status</th>
                <th>Description</th>
                <th>Created</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {isLoading ? (
                <tr><td colSpan={10} style={{ textAlign: 'center', padding: 48 }}><span className="spinner spinner-lg" /></td></tr>
              ) : items.length === 0 ? (
                <tr>
                  <td colSpan={10}>
                    <div className="empty-state">
                      <div className="empty-state-icon">✅</div>
                      <p className="empty-state-title">No exceptions found</p>
                      <p className="empty-state-desc">Try clearing your filters or run reconciliation.</p>
                    </div>
                  </td>
                </tr>
              ) : items.map(e => (
                <tr key={e.id} style={{ cursor: 'pointer' }} onClick={() => openDetail(e.id)}>
                  <td>
                    <span style={{ fontSize: 12, textTransform: 'capitalize' }}>
                      {e.category.replace(/_/g, ' ')}
                    </span>
                  </td>
                  <td>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                      <span className={`severity-dot severity-${e.severity}`} />
                      <span className={`badge ${severityClass(e.severity)}`}>{e.severity}</span>
                    </div>
                  </td>
                  <td className="text-sm text-muted">{e.gateway ?? '—'}</td>
                  <td className="text-sm">{e.currency ?? '—'}</td>
                  <td className="td-amount">{e.amount_at_stake ?? '—'}</td>
                  <td className="td-mono" style={{ color: e.amount_difference && parseFloat(e.amount_difference) !== 0 ? 'var(--color-warning)' : 'inherit' }}>
                    {e.amount_difference ?? '—'}
                  </td>
                  <td><span className={`badge ${reviewStatusClass(e.review_status)}`}>{e.review_status.replace('_', ' ')}</span></td>
                  <td style={{ maxWidth: 200 }}>
                    <div className="truncate text-sm text-muted" title={e.description}>{e.description}</div>
                  </td>
                  <td className="text-sm text-muted">{formatDate(e.created_at)}</td>
                  <td>
                    <button className="btn btn-ghost btn-sm" onClick={ev => { ev.stopPropagation(); openDetail(e.id) }}>
                      View
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* Pagination */}
        {totalPages > 1 && (
          <div className="pagination" style={{ padding: '12px 20px' }}>
            <span className="pagination-info">{total} total · page {page}/{totalPages}</span>
            <button className="btn btn-ghost btn-sm" onClick={() => setPage(p => Math.max(1, p - 1))} disabled={page === 1}>
              <ChevronLeft size={14} />
            </button>
            <button className="btn btn-ghost btn-sm" onClick={() => setPage(p => Math.min(totalPages, p + 1))} disabled={page === totalPages}>
              <ChevronRight size={14} />
            </button>
          </div>
        )}
      </div>

      {/* Exception Detail Modal */}
      {showModal && selectedId && (
        <div className="modal-overlay" onClick={() => setShowModal(false)}>
          <div className="modal modal-wide" onClick={e => e.stopPropagation()} style={{ maxWidth: 820 }}>
            <div className="modal-header">
              <span className="modal-title">Exception Detail</span>
              <button className="btn btn-ghost btn-sm" onClick={() => setShowModal(false)}>
                <X size={16} />
              </button>
            </div>
            {detailLoading ? (
              <div style={{ padding: 64, textAlign: 'center' }}>
                <span className="spinner spinner-lg" />
              </div>
            ) : detail && (
              <ExceptionDetailPanel
                detail={detail}
                audit={auditData ?? []}
                onInvestigate={() => investigateMutation.mutate(detail.id)}
                investigating={investigateMutation.isPending}
                onReview={(action) => reviewMutation.mutate({ id: detail.id, action })}
                reviewing={reviewMutation.isPending}
              />
            )}
          </div>
        </div>
      )}
    </div>
  )
}

function ExceptionDetailPanel({
  detail, audit, onInvestigate, investigating, onReview, reviewing
}: {
  detail: ExceptionDetail
  audit: { id: string; event_type: string; actor: string; created_at: string }[]
  onInvestigate: () => void
  investigating: boolean
  onReview: (action: string) => void
  reviewing: boolean
}) {
  const [tab, setTab] = useState<'overview' | 'ai' | 'history'>('overview')
  const latestInvestigation = detail.investigations?.[0]

  return (
    <div className="modal-body" style={{ padding: 0 }}>
      <div style={{ padding: '0 24px', borderBottom: '1px solid var(--color-border)' }}>
        <div className="tabs" style={{ borderRadius: 0, border: 'none', background: 'transparent', padding: '12px 0 0', gap: 4 }}>
          {(['overview', 'ai', 'history'] as const).map(t => (
            <div key={t} className={`tab${tab === t ? ' active' : ''}`} onClick={() => setTab(t)} style={{ textTransform: 'capitalize' }}>
              {t === 'ai' ? '🤖 AI Investigation' : t.charAt(0).toUpperCase() + t.slice(1)}
            </div>
          ))}
        </div>
      </div>

      <div style={{ padding: 24 }}>
        {tab === 'overview' && (
          <div>
            <div style={{ display: 'flex', gap: 12, marginBottom: 20, flexWrap: 'wrap' }}>
              <span className={`badge ${severityClass(detail.severity)}`}>{detail.severity}</span>
              <span className={`badge ${reviewStatusClass(detail.review_status)}`}>{detail.review_status.replace('_', ' ')}</span>
              <span className="badge badge-muted">{detail.category.replace(/_/g, ' ')}</span>
              {detail.gateway && <span className="badge badge-purple">{detail.gateway}</span>}
            </div>

            <p style={{ fontSize: 14, color: 'var(--color-text-primary)', lineHeight: 1.7, marginBottom: 20 }}>
              {detail.description}
            </p>

            <div className="info-row">
              <span className="info-row-label">Amount at Stake</span>
              <span className="info-row-value td-amount">{detail.amount_at_stake ?? '—'}</span>
            </div>
            <div className="info-row">
              <span className="info-row-label">Amount Difference</span>
              <span className="info-row-value td-amount">{detail.amount_difference ?? '—'}</span>
            </div>
            <div className="info-row">
              <span className="info-row-label">Expected Value</span>
              <span className="info-row-value td-amount">{detail.expected_value ?? '—'}</span>
            </div>
            <div className="info-row">
              <span className="info-row-label">Observed Value</span>
              <span className="info-row-value td-amount">{detail.observed_value ?? '—'}</span>
            </div>
            <div className="info-row">
              <span className="info-row-label">Currency</span>
              <span className="info-row-value">{detail.currency ?? '—'}</span>
            </div>
            <div className="info-row">
              <span className="info-row-label">Source Payment ID</span>
              <span className="info-row-value font-mono">{detail.source_payment_id ?? '—'}</span>
            </div>
            <div className="info-row">
              <span className="info-row-label">Source Txn ID</span>
              <span className="info-row-value font-mono">{detail.source_txn_id ?? '—'}</span>
            </div>
            <div className="info-row">
              <span className="info-row-label">Created At</span>
              <span className="info-row-value">{formatDate(detail.created_at)}</span>
            </div>

            {/* Review actions */}
            <div className="divider" />
            <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
              <button className="btn btn-success btn-sm" onClick={() => onReview('resolved')} disabled={reviewing || detail.review_status === 'resolved'}>
                <CheckCircle2 size={13} /> Resolve
              </button>
              <button className="btn btn-secondary btn-sm" onClick={() => onReview('in_review')} disabled={reviewing || detail.review_status === 'in_review'}>
                <Clock size={13} /> Mark In Review
              </button>
              <button className="btn btn-ghost btn-sm" onClick={() => onReview('dismissed')} disabled={reviewing || detail.review_status === 'dismissed'}>
                <XCircle size={13} /> Dismiss
              </button>
            </div>
          </div>
        )}

        {tab === 'ai' && (
          <div>
            <div className="ai-panel">
              <div className="ai-panel-header">
                <span className="ai-badge">✨ AI</span>
                <span style={{ fontSize: 14, fontWeight: 600, color: 'var(--color-text-primary)' }}>AI-Powered Investigation</span>
              </div>
              {!latestInvestigation ? (
                <div style={{ textAlign: 'center', padding: '20px 0' }}>
                  <p style={{ fontSize: 13, color: 'var(--color-text-secondary)', marginBottom: 16 }}>
                    No investigation yet. Click to run an AI (or deterministic) analysis of this exception.
                  </p>
                  <button className="btn btn-primary" onClick={onInvestigate} disabled={investigating}>
                    {investigating ? <><span className="spinner" /> Investigating…</> : <><Bot size={15} /> Investigate</>}
                  </button>
                </div>
              ) : (
                <div>
                  <div style={{ display: 'flex', gap: 12, marginBottom: 16, alignItems: 'center', flexWrap: 'wrap' }}>
                    <span className={`badge ${latestInvestigation.is_ai_generated ? 'badge-purple' : 'badge-muted'}`}>
                      {latestInvestigation.is_ai_generated ? '✨ AI Generated' : '⚙️ Deterministic'}
                    </span>
                    <span className="text-xs text-muted">{latestInvestigation.provider} · {latestInvestigation.model}</span>
                    <span className="text-xs text-muted">{formatDate(latestInvestigation.created_at)}</span>
                    <button className="btn btn-ghost btn-sm" style={{ marginLeft: 'auto' }} onClick={onInvestigate} disabled={investigating}>
                      <RefreshCw size={13} /> Re-investigate
                    </button>
                  </div>

                  {latestInvestigation.summary && (
                    <div style={{ marginBottom: 16 }}>
                      <div style={{ fontSize: 12, color: 'var(--color-text-muted)', marginBottom: 6, textTransform: 'uppercase', letterSpacing: '0.5px' }}>Summary</div>
                      <p style={{ fontSize: 14, color: 'var(--color-text-primary)', lineHeight: 1.7 }}>{latestInvestigation.summary}</p>
                    </div>
                  )}

                  {latestInvestigation.verified_facts?.length ? (
                    <InvestigationList title="Verified Facts" items={latestInvestigation.verified_facts} color="var(--color-success)" />
                  ) : null}

                  {latestInvestigation.possible_explanations?.length ? (
                    <InvestigationList title="Possible Explanations" items={latestInvestigation.possible_explanations} color="var(--color-warning)" />
                  ) : null}

                  {latestInvestigation.recommended_steps?.length ? (
                    <InvestigationList title="Recommended Steps" items={latestInvestigation.recommended_steps} color="var(--color-accent)" />
                  ) : null}

                  {latestInvestigation.confidence_assessment && (
                    <div style={{ marginTop: 12, padding: '10px 14px', background: 'var(--color-accent-dim)', borderRadius: 8, fontSize: 13, color: 'var(--color-text-secondary)' }}>
                      <strong style={{ color: 'var(--color-accent)' }}>Confidence:</strong> {latestInvestigation.confidence_assessment}
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>
        )}

        {tab === 'history' && (
          <div>
            <div style={{ marginBottom: 16, fontSize: 14, fontWeight: 600, color: 'var(--color-text-primary)' }}>Review History</div>
            {detail.review_history?.length === 0 ? (
              <p className="text-muted text-sm">No review history yet.</p>
            ) : detail.review_history?.map(r => (
              <div key={r.id} style={{ padding: '12px 0', borderBottom: '1px solid var(--color-border)' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
                  <span style={{ fontSize: 13, fontWeight: 500, color: 'var(--color-text-primary)' }}>
                    <span className={`badge ${reviewStatusClass(r.action)}`}>{r.action.replace('_', ' ')}</span>
                    <span style={{ marginLeft: 8, color: 'var(--color-text-secondary)' }}>by {r.reviewer}</span>
                  </span>
                  <span style={{ fontSize: 11, color: 'var(--color-text-muted)' }}>{formatDate(r.created_at)}</span>
                </div>
                {r.notes && <p style={{ fontSize: 12, color: 'var(--color-text-muted)' }}>{r.notes}</p>}
              </div>
            ))}

            {audit.length > 0 && (
              <>
                <div className="divider" />
                <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--color-text-primary)', marginBottom: 12 }}>Audit Trail</div>
                {audit.map(a => (
                  <div key={a.id} style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '8px 0', borderBottom: '1px solid var(--color-border)', fontSize: 12 }}>
                    <span style={{ color: 'var(--color-accent)' }}>{a.event_type.replace(/_/g, ' ')}</span>
                    <span className="text-muted">by {a.actor}</span>
                    <span className="text-muted" style={{ marginLeft: 'auto' }}>{formatDate(a.created_at)}</span>
                  </div>
                ))}
              </>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

function InvestigationList({ title, items, color }: { title: string; items: string[]; color: string }) {
  return (
    <div style={{ marginTop: 14 }}>
      <div style={{ fontSize: 11, color: 'var(--color-text-muted)', marginBottom: 8, textTransform: 'uppercase', letterSpacing: '0.5px' }}>{title}</div>
      <ul style={{ listStyle: 'none', display: 'flex', flexDirection: 'column', gap: 6 }}>
        {items.map((item, i) => (
          <li key={i} style={{ display: 'flex', gap: 10, fontSize: 13, color: 'var(--color-text-primary)' }}>
            <span style={{ color, flexShrink: 0 }}>•</span>
            <span>{item}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}
