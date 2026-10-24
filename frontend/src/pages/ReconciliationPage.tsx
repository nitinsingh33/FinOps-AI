import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { RefreshCw, Play, ChevronLeft, ChevronRight, CheckCircle2, AlertTriangle } from 'lucide-react'
import {
  fetchReconciliationRuns, triggerReconciliation,
  fetchRunMatches, fetchRunExceptions
} from '../api/client'
import { formatDate, formatNumber, reconciliationStatusClass } from '../lib/format'
import type { ReconciliationRun } from '../types'

export default function ReconciliationPage() {
  const queryClient = useQueryClient()
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null)
  const [activeTab, setActiveTab] = useState<'matches' | 'exceptions'>('matches')
  const [page, setPage] = useState(1)

  const { data: runs, isLoading } = useQuery({
    queryKey: ['reconciliation-runs'],
    queryFn: fetchReconciliationRuns,
    refetchInterval: 8_000,
  })

  const triggerMutation = useMutation({
    mutationFn: triggerReconciliation,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['reconciliation-runs'] })
    },
  })

  const selectedRun: ReconciliationRun | undefined = runs?.find((r: ReconciliationRun) => r.id === selectedRunId)

  const { data: matchesData } = useQuery({
    queryKey: ['run-matches', selectedRunId, page],
    queryFn: () => fetchRunMatches(selectedRunId!, page),
    enabled: !!selectedRunId && activeTab === 'matches',
  })

  const { data: exceptionsData } = useQuery({
    queryKey: ['run-exceptions', selectedRunId, page],
    queryFn: () => fetchRunExceptions(selectedRunId!, page),
    enabled: !!selectedRunId && activeTab === 'exceptions',
  })

  const handleTabChange = (tab: 'matches' | 'exceptions') => {
    setActiveTab(tab)
    setPage(1)
  }

  return (
    <div className="page-wrapper">
      <div className="page-header" style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between' }}>
        <div>
          <h1 className="page-title">Reconciliation</h1>
          <p className="page-subtitle">Run payment reconciliation and review matched/unmatched records</p>
        </div>
        <div style={{ display: 'flex', gap: 12, marginTop: 4 }}>
          <button
            className="btn btn-ghost btn-sm"
            onClick={() => queryClient.invalidateQueries({ queryKey: ['reconciliation-runs'] })}
          >
            <RefreshCw size={13} /> Refresh
          </button>
          <button
            className="btn btn-primary"
            onClick={() => triggerMutation.mutate()}
            disabled={triggerMutation.isPending}
          >
            {triggerMutation.isPending
              ? <><span className="spinner" />Running…</>
              : <><Play size={15} />Trigger Reconciliation</>
            }
          </button>
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '320px 1fr', gap: 24, alignItems: 'start' }}>
        {/* Runs list */}
        <div className="card" style={{ position: 'sticky', top: 80 }}>
          <div className="card-header">
            <span className="card-title">
              <RefreshCw size={15} color="var(--color-cyan)" />
              Runs
            </span>
            <span style={{ fontSize: 12, color: 'var(--color-text-muted)' }}>{runs?.length ?? 0} total</span>
          </div>
          <div style={{ maxHeight: '70vh', overflowY: 'auto' }}>
            {isLoading ? (
              <div style={{ padding: 32, textAlign: 'center' }}><span className="spinner" /></div>
            ) : !runs?.length ? (
              <div className="empty-state" style={{ padding: '32px 16px' }}>
                <div className="empty-state-icon">🔄</div>
                <p className="empty-state-title" style={{ fontSize: 15 }}>No runs yet</p>
                <p className="empty-state-desc">Click "Trigger Reconciliation" above.</p>
              </div>
            ) : (runs as ReconciliationRun[]).map(run => (
              <div
                key={run.id}
                onClick={() => { setSelectedRunId(run.id); setPage(1) }}
                style={{
                  padding: '14px 20px',
                  borderBottom: '1px solid var(--color-border)',
                  cursor: 'pointer',
                  background: selectedRunId === run.id ? 'var(--color-accent-dim)' : 'transparent',
                  transition: 'background var(--transition-fast)',
                }}
                onMouseEnter={e => { if (selectedRunId !== run.id) (e.currentTarget as HTMLElement).style.background = 'rgba(255,255,255,0.03)' }}
                onMouseLeave={e => { if (selectedRunId !== run.id) (e.currentTarget as HTMLElement).style.background = 'transparent' }}
              >
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 6 }}>
                  <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--color-text-secondary)' }}>
                    {run.id.slice(0, 12)}…
                  </span>
                  <span className={`badge ${reconciliationStatusClass(run.status)}`}>{run.status}</span>
                </div>
                <div style={{ display: 'flex', gap: 16, fontSize: 12, color: 'var(--color-text-muted)' }}>
                  <span>✓ {formatNumber(run.matched_records)}</span>
                  <span>⚠ {formatNumber(run.exception_count)}</span>
                </div>
                <div style={{ fontSize: 11, color: 'var(--color-text-muted)', marginTop: 4 }}>
                  {formatDate(run.created_at)}
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Run detail */}
        {!selectedRun ? (
          <div className="card">
            <div className="empty-state" style={{ padding: '80px 32px' }}>
              <div className="empty-state-icon">👈</div>
              <p className="empty-state-title">Select a run</p>
              <p className="empty-state-desc">Click a reconciliation run on the left to view its matches and exceptions.</p>
            </div>
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
            {/* Run summary */}
            <div className="card">
              <div className="card-header">
                <span className="card-title">Run Details</span>
                <span className={`badge ${reconciliationStatusClass(selectedRun.status)}`}>{selectedRun.status}</span>
              </div>
              <div className="card-body">
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 20 }}>
                  {[
                    { label: 'Source Rows Scanned', value: formatNumber(selectedRun.total_records) },
                    { label: 'Matched', value: formatNumber(selectedRun.matched_records), color: 'var(--color-success)' },
                    { label: 'Unmatched', value: formatNumber(selectedRun.unmatched_records), color: 'var(--color-warning)' },
                    { label: 'Exceptions', value: formatNumber(selectedRun.exception_count), color: 'var(--color-danger)' },
                  ].map(({ label, value, color }) => (
                    <div key={label}>
                      <div style={{ fontSize: 11, color: 'var(--color-text-muted)', textTransform: 'uppercase', letterSpacing: '0.5px', marginBottom: 4 }}>{label}</div>
                      <div style={{ fontSize: 24, fontWeight: 800, color: color ?? 'var(--color-text-primary)' }}>{value}</div>
                    </div>
                  ))}
                </div>
                <p className="text-sm text-muted" style={{ marginTop: 16 }}>
                  Source Rows Scanned counts input rows across all imported ledgers. Matched counts linked Gateway A payment/transaction pairs;
                  Unmatched counts missing-side rows. Exceptions count issue flags and may apply to matched or unmatched rows, so these figures are not parts of one sum.
                  Gateway B rows are checked separately for net amounts and payout links.
                </p>
                <div className="divider" />
                <div style={{ display: 'flex', gap: 40 }}>
                  <div>
                    <div style={{ fontSize: 11, color: 'var(--color-text-muted)', marginBottom: 2 }}>Started</div>
                    <div style={{ fontSize: 13 }}>{formatDate(selectedRun.started_at)}</div>
                  </div>
                  <div>
                    <div style={{ fontSize: 11, color: 'var(--color-text-muted)', marginBottom: 2 }}>Completed</div>
                    <div style={{ fontSize: 13 }}>{formatDate(selectedRun.completed_at)}</div>
                  </div>
                  <div>
                    <div style={{ fontSize: 11, color: 'var(--color-text-muted)', marginBottom: 2 }}>Rule Version</div>
                    <div style={{ fontSize: 13 }}>{selectedRun.rule_version}</div>
                  </div>
                </div>
                {selectedRun.error_message && (
                  <div style={{ marginTop: 16, padding: '12px 16px', background: 'var(--color-danger-dim)', borderRadius: 10, color: 'var(--color-danger)', fontSize: 13 }}>
                    {selectedRun.error_message}
                  </div>
                )}
              </div>
            </div>

            {/* Tabs */}
            <div>
              <div className="tabs mb-4">
                <div className={`tab${activeTab === 'matches' ? ' active' : ''}`} onClick={() => handleTabChange('matches')}>
                  <CheckCircle2 size={13} style={{ marginRight: 6 }} /> Matches
                </div>
                <div className={`tab${activeTab === 'exceptions' ? ' active' : ''}`} onClick={() => handleTabChange('exceptions')}>
                  <AlertTriangle size={13} style={{ marginRight: 6 }} /> Exceptions
                </div>
              </div>

              {activeTab === 'matches' && (
                <div className="card">
                  <div className="table-container" style={{ border: 'none', borderRadius: 0 }}>
                    <table className="data-table">
                      <thead>
                        <tr>
                          <th>Match ID</th>
                          <th>Method</th>
                          <th>Confidence</th>
                          <th>Payment ID</th>
                          <th>Txn ID</th>
                          <th>Difference</th>
                          <th>Currency</th>
                        </tr>
                      </thead>
                      <tbody>
                        {!matchesData ? (
                          <tr><td colSpan={7} style={{ textAlign: 'center', padding: 32 }}><span className="spinner" /></td></tr>
                        ) : matchesData.items?.length === 0 ? (
                          <tr><td colSpan={7} style={{ textAlign: 'center', padding: 32, color: 'var(--color-text-muted)' }}>No matches</td></tr>
                        ) : matchesData.items?.map((m: { id: string; match_method: string; confidence: string; payment_id: string | null; gateway_txn_id: string | null; amount_difference: string | null; currency: string | null }) => (
                          <tr key={m.id}>
                            <td className="td-mono">{m.id.slice(0, 10)}…</td>
                            <td><span className="badge badge-info">{m.match_method}</span></td>
                            <td>
                              <span style={{ color: confidenceColor(m.confidence) }}>{m.confidence}</span>
                            </td>
                            <td className="td-mono">{m.payment_id?.slice(0, 12) ?? '—'}</td>
                            <td className="td-mono">{m.gateway_txn_id?.slice(0, 12) ?? '—'}</td>
                            <td className="td-mono" style={{ color: m.amount_difference && parseFloat(m.amount_difference) !== 0 ? 'var(--color-warning)' : 'inherit' }}>
                              {m.amount_difference ?? '0'}
                            </td>
                            <td>{m.currency ?? '—'}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  {matchesData && <Pagination data={matchesData} page={page} setPage={setPage} />}
                </div>
              )}

              {activeTab === 'exceptions' && (
                <div className="card">
                  <div className="table-container" style={{ border: 'none', borderRadius: 0 }}>
                    <p className="text-sm text-muted" style={{ padding: '12px 16px 0' }}>
                      Amount at stake is shown only when the source records provide enough information to calculate it; “—” means unavailable, not zero.
                    </p>
                    <table className="data-table">
                      <thead>
                        <tr>
                          <th>Category</th>
                          <th>Severity</th>
                          <th>Gateway</th>
                          <th>Amount at Stake</th>
                          <th>Difference</th>
                          <th>Status</th>
                          <th>Created</th>
                        </tr>
                      </thead>
                      <tbody>
                        {!exceptionsData ? (
                          <tr><td colSpan={7} style={{ textAlign: 'center', padding: 32 }}><span className="spinner" /></td></tr>
                        ) : exceptionsData.items?.length === 0 ? (
                          <tr><td colSpan={7} style={{ textAlign: 'center', padding: 32, color: 'var(--color-text-muted)' }}>No exceptions for this run</td></tr>
                        ) : exceptionsData.items?.map((e: { id: string; category: string; severity: string; gateway: string | null; currency: string | null; amount_at_stake: string | null; amount_difference: string | null; review_status: string; created_at: string }) => (
                          <tr key={e.id}>
                            <td style={{ textTransform: 'capitalize', fontSize: 12 }}>{e.category.replace(/_/g, ' ')}</td>
                            <td><span className={`badge ${severityBadge(e.severity)}`}>{e.severity}</span></td>
                            <td className="text-sm text-muted">{e.gateway ?? '—'}</td>
                            <td className="td-amount">{e.amount_at_stake == null ? '—' : `${e.currency ?? ''} ${e.amount_at_stake}`}</td>
                            <td className="td-amount">{e.amount_difference == null ? '—' : `${e.currency ?? ''} ${e.amount_difference}`}</td>
                            <td><span className={`badge ${reviewBadge(e.review_status)}`}>{e.review_status.replace('_', ' ')}</span></td>
                            <td className="text-sm text-muted">{formatDate(e.created_at)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  {exceptionsData && <Pagination data={exceptionsData} page={page} setPage={setPage} />}
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

function Pagination({ data, page, setPage }: { data: { total: number; page_size: number }; page: number; setPage: (p: number) => void }) {
  const totalPages = Math.ceil(data.total / data.page_size)
  if (totalPages <= 1) return null
  return (
    <div className="pagination" style={{ padding: '12px 20px' }}>
      <span className="pagination-info">{data.total} total</span>
      <button className="btn btn-ghost btn-sm" onClick={() => setPage(Math.max(1, page - 1))} disabled={page === 1}>
        <ChevronLeft size={14} />
      </button>
      <span style={{ fontSize: 13, color: 'var(--color-text-secondary)' }}>
        {page} / {totalPages}
      </span>
      <button className="btn btn-ghost btn-sm" onClick={() => setPage(Math.min(totalPages, page + 1))} disabled={page === totalPages}>
        <ChevronRight size={14} />
      </button>
    </div>
  )
}

function confidenceColor(c: string) {
  if (c === 'high') return 'var(--color-success)'
  if (c === 'medium') return 'var(--color-warning)'
  return 'var(--color-danger)'
}

function severityBadge(s: string) {
  switch (s) {
    case 'critical': return 'badge-danger'
    case 'high': return 'badge-warning'
    case 'medium': return 'badge-info'
    case 'low': return 'badge-success'
    default: return 'badge-muted'
  }
}

function reviewBadge(s: string) {
  switch (s) {
    case 'open': return 'badge-danger'
    case 'in_review': return 'badge-warning'
    case 'resolved': return 'badge-success'
    case 'dismissed': return 'badge-muted'
    default: return 'badge-muted'
  }
}
