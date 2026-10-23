import { useQuery } from '@tanstack/react-query'
import {
  AreaChart, Area, BarChart, Bar, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer, PieChart, Pie, Cell
} from 'recharts'
import {
  Activity, AlertTriangle, CheckCircle2, RefreshCw,
  TrendingUp, Upload, DollarSign, ShieldCheck
} from 'lucide-react'
import { fetchOverview, fetchExceptions, fetchReconciliationRuns } from '../api/client'
import { formatNumber, formatDate, reviewStatusClass } from '../lib/format'
import type { ReconciliationRun, ReconciliationException } from '../types'

const COLORS = ['#4f9cf9', '#7c3aed', '#10b981', '#f59e0b', '#ef4444', '#06b6d4']

const CUSTOM_TOOLTIP_STYLE = {
  backgroundColor: '#111827',
  border: '1px solid rgba(255,255,255,0.1)',
  borderRadius: 10,
  color: '#f1f5f9',
  fontSize: 12,
}

export default function DashboardPage() {
  const { data: overview, isLoading: ovLoading } = useQuery({
    queryKey: ['overview'],
    queryFn: fetchOverview,
    refetchInterval: 30_000,
  })

  const { data: excData } = useQuery({
    queryKey: ['exceptions', { page: 1, page_size: 5 }],
    queryFn: () => fetchExceptions({ page: 1, page_size: 5 }),
  })

  const { data: runs } = useQuery({
    queryKey: ['reconciliation-runs'],
    queryFn: fetchReconciliationRuns,
  })

  const recentRuns: ReconciliationRun[] = runs?.slice(0, 6) ?? []
  const recentExceptions: ReconciliationException[] = excData?.items?.slice(0, 5) ?? []

  // Build chart data from runs
  const runChartData = recentRuns
    .filter(r => r.completed_at)
    .slice(0, 5)
    .reverse()
    .map((r, i) => ({
      name: `Run ${i + 1}`,
      matched: r.matched_records ?? 0,
      unmatched: r.unmatched_records ?? 0,
      exceptions: r.exception_count ?? 0,
    }))

  // Exception category distribution
  const categories = excData?.items?.reduce((acc: Record<string, number>, e: ReconciliationException) => {
    acc[e.category] = (acc[e.category] ?? 0) + 1
    return acc
  }, {}) ?? {}
  const pieData = Object.entries(categories).map(([name, value]) => ({ name, value }))

  const statCards = [
    {
      label: 'Total Payments',
      value: formatNumber(overview?.total_payments),
      icon: TrendingUp,
      accent: '#4f9cf9',
      accentBg: 'rgba(79,156,249,0.12)',
    },
    {
      label: 'Gateway Transactions',
      value: formatNumber(overview?.total_transactions),
      icon: Activity,
      accent: '#7c3aed',
      accentBg: 'rgba(124,58,237,0.12)',
    },
    {
      label: 'Recon Runs',
      value: formatNumber(overview?.reconciliation_runs),
      icon: RefreshCw,
      accent: '#10b981',
      accentBg: 'rgba(16,185,129,0.12)',
    },
    {
      label: 'Open Exceptions',
      value: formatNumber(overview?.open_exceptions),
      icon: AlertTriangle,
      accent: '#ef4444',
      accentBg: 'rgba(239,68,68,0.12)',
    },
    {
      label: 'Matched Records',
      value: formatNumber(overview?.matched_records),
      icon: CheckCircle2,
      accent: '#10b981',
      accentBg: 'rgba(16,185,129,0.12)',
    },
    {
      label: 'Total Refunds',
      value: formatNumber(overview?.total_refunds),
      icon: DollarSign,
      accent: '#f59e0b',
      accentBg: 'rgba(245,158,11,0.12)',
    },
  ]

  return (
    <div className="page-wrapper">
      <div className="page-header">
        <h1 className="page-title">Dashboard</h1>
        <p className="page-subtitle">Payment reconciliation &amp; gateway cost overview</p>
      </div>

      {/* Stat cards */}
      <div className="stats-grid">
        {statCards.map(({ label, value, icon: Icon, accent, accentBg }) => (
          <div
            key={label}
            className="stat-card"
            style={{ '--card-accent-color': accent, '--card-accent-bg': accentBg } as React.CSSProperties}
          >
            <div className="stat-icon">
              <Icon size={18} />
            </div>
            <div className="stat-label">{label}</div>
            <div className="stat-value">
              {ovLoading ? <span className="skeleton skeleton-title" style={{ width: 80 }} /> : value}
            </div>
          </div>
        ))}
      </div>

      {/* Charts row */}
      <div className="grid-2 mb-8">
        {/* Reconciliation runs bar chart */}
        <div className="card">
          <div className="card-header">
            <span className="card-title">
              <ShieldCheck size={16} color="var(--color-accent)" />
              Reconciliation Runs
            </span>
          </div>
          <div className="card-body">
            {runChartData.length === 0 ? (
              <div className="empty-state" style={{ padding: '40px 0' }}>
                <div className="empty-state-icon">📊</div>
                <p className="empty-state-title">No runs yet</p>
                <p className="empty-state-desc">Trigger a reconciliation run to see data here.</p>
              </div>
            ) : (
              <div className="chart-container" style={{ height: 220 }}>
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={runChartData} barGap={4} barSize={22}>
                    <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.04)" />
                    <XAxis dataKey="name" tick={{ fill: '#475569', fontSize: 11 }} axisLine={false} tickLine={false} />
                    <YAxis tick={{ fill: '#475569', fontSize: 11 }} axisLine={false} tickLine={false} />
                    <Tooltip contentStyle={CUSTOM_TOOLTIP_STYLE} cursor={{ fill: 'rgba(255,255,255,0.03)' }} />
                    <Bar dataKey="matched" name="Matched" fill="#4f9cf9" radius={[4, 4, 0, 0]} />
                    <Bar dataKey="exceptions" name="Exceptions" fill="#ef4444" radius={[4, 4, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            )}
          </div>
        </div>

        {/* Exception categories pie */}
        <div className="card">
          <div className="card-header">
            <span className="card-title">
              <AlertTriangle size={16} color="var(--color-warning)" />
              Exception Categories
            </span>
          </div>
          <div className="card-body">
            {pieData.length === 0 ? (
              <div className="empty-state" style={{ padding: '40px 0' }}>
                <div className="empty-state-icon">🎉</div>
                <p className="empty-state-title">No exceptions</p>
                <p className="empty-state-desc">Run a reconciliation to detect exceptions.</p>
              </div>
            ) : (
              <div style={{ display: 'flex', alignItems: 'center', gap: 24 }}>
                <div style={{ width: 180, height: 180, flexShrink: 0 }}>
                  <ResponsiveContainer width="100%" height="100%">
                    <PieChart>
                      <Pie
                        data={pieData}
                        cx="50%" cy="50%"
                        innerRadius={50} outerRadius={80}
                        paddingAngle={3}
                        dataKey="value"
                      >
                        {pieData.map((_, i) => (
                          <Cell key={i} fill={COLORS[i % COLORS.length]} />
                        ))}
                      </Pie>
                      <Tooltip contentStyle={CUSTOM_TOOLTIP_STYLE} />
                    </PieChart>
                  </ResponsiveContainer>
                </div>
                <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 8 }}>
                  {pieData.map((d, i) => (
                    <div key={d.name} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                      <span style={{ width: 10, height: 10, borderRadius: '50%', background: COLORS[i % COLORS.length], flexShrink: 0 }} />
                      <span style={{ fontSize: 12, color: 'var(--color-text-secondary)', flex: 1, textTransform: 'capitalize' }}>
                        {d.name.replace(/_/g, ' ')}
                      </span>
                      <span style={{ fontSize: 12, fontWeight: 600, color: 'var(--color-text-primary)' }}>{d.value}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Recent items */}
      <div className="grid-2">
        {/* Recent reconciliation runs */}
        <div className="card">
          <div className="card-header">
            <span className="card-title">
              <RefreshCw size={16} color="var(--color-cyan)" />
              Recent Runs
            </span>
          </div>
          <div className="table-container" style={{ border: 'none', borderRadius: 0 }}>
            <table className="data-table">
              <thead>
                <tr>
                  <th>Run ID</th>
                  <th>Status</th>
                  <th>Matched</th>
                  <th>Exceptions</th>
                  <th>Date</th>
                </tr>
              </thead>
              <tbody>
                {recentRuns.length === 0 ? (
                  <tr><td colSpan={5} style={{ textAlign: 'center', color: 'var(--color-text-muted)', padding: 32 }}>No runs found</td></tr>
                ) : recentRuns.map(run => (
                  <tr key={run.id}>
                    <td className="td-mono">{run.id.slice(0, 8)}…</td>
                    <td><span className={`badge ${reconciliationStatusBadge(run.status)}`}>{run.status}</span></td>
                    <td>{formatNumber(run.matched_records)}</td>
                    <td>{formatNumber(run.exception_count)}</td>
                    <td className="text-muted text-sm">{formatDate(run.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        {/* Recent exceptions */}
        <div className="card">
          <div className="card-header">
            <span className="card-title">
              <AlertTriangle size={16} color="var(--color-danger)" />
              Recent Exceptions
            </span>
          </div>
          <div className="table-container" style={{ border: 'none', borderRadius: 0 }}>
            <table className="data-table">
              <thead>
                <tr>
                  <th>Category</th>
                  <th>Severity</th>
                  <th>Gateway</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {recentExceptions.length === 0 ? (
                  <tr><td colSpan={4} style={{ textAlign: 'center', color: 'var(--color-text-muted)', padding: 32 }}>No exceptions</td></tr>
                ) : recentExceptions.map(e => (
                  <tr key={e.id}>
                    <td style={{ textTransform: 'capitalize', fontSize: 12 }}>{e.category.replace(/_/g, ' ')}</td>
                    <td><span className={`badge ${severityBadge(e.severity)}`}>{e.severity}</span></td>
                    <td className="text-sm text-muted">{e.gateway ?? '—'}</td>
                    <td><span className={`badge ${reviewStatusClass(e.review_status)}`}>{e.review_status.replace('_', ' ')}</span></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  )
}

function reconciliationStatusBadge(status: string) {
  switch (status) {
    case 'completed': return 'badge-success'
    case 'running': return 'badge-info'
    case 'pending': return 'badge-warning'
    case 'failed': return 'badge-danger'
    default: return 'badge-muted'
  }
}

function severityBadge(severity: string) {
  switch (severity) {
    case 'critical': return 'badge-danger'
    case 'high': return 'badge-warning'
    case 'medium': return 'badge-info'
    case 'low': return 'badge-success'
    default: return 'badge-muted'
  }
}
