import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  BarChart, Bar, LineChart, Line, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer, Legend, PieChart, Pie, Cell
} from 'recharts'
import { LineChart as LineChartIcon, DollarSign, Globe, TrendingUp } from 'lucide-react'
import { fetchGatewayCosts, fetchSettlements } from '../api/client'

const TOOLTIP_STYLE = {
  backgroundColor: '#111827',
  border: '1px solid rgba(255,255,255,0.1)',
  borderRadius: 10,
  color: '#f1f5f9',
  fontSize: 12,
}

const COLORS = ['#4f9cf9', '#7c3aed', '#10b981', '#f59e0b', '#ef4444', '#06b6d4']

export default function AnalyticsPage() {
  const [gateway, setGateway] = useState('')

  const { data: costsData, isLoading: costsLoading } = useQuery({
    queryKey: ['gateway-costs', gateway],
    queryFn: () => fetchGatewayCosts(gateway || undefined),
  })

  const { data: settlData } = useQuery({
    queryKey: ['settlements'],
    queryFn: fetchSettlements,
  })

  const breakdowns = costsData?.breakdowns ?? []
  const summary = costsData?.summary ?? {}

  // Prepare bar chart data: group by currency
  const barData = breakdowns.slice(0, 10).map((b: { gateway: string; currency: string; payment_count: number; gross_volume: number; total_fees: number; effective_rate_pct: number }) => ({
    name: `${b.gateway?.toUpperCase() ?? ''} ${b.currency ?? ''}`,
    'Gross Volume': Math.round(b.gross_volume ?? 0),
    'Total Fees': Math.round(b.total_fees ?? 0),
    'Eff. Rate %': b.effective_rate_pct ? parseFloat(b.effective_rate_pct.toFixed(3)) : 0,
  }))

  // Pie for gateway split by volume
  const gatewayVolumes: Record<string, number> = {}
  breakdowns.forEach((b: { gateway: string; gross_volume: number }) => {
    const gw = b.gateway ?? 'unknown'
    gatewayVolumes[gw] = (gatewayVolumes[gw] ?? 0) + (b.gross_volume ?? 0)
  })
  const pieData = Object.entries(gatewayVolumes).map(([name, value]) => ({ name, value: Math.round(value) }))

  // Settlement data
  const gwbPayouts = settlData?.gateway_b_payout_summary?.sample_payouts ?? []
  const gwaSettlement = settlData?.gateway_a_settlement_summary ?? []

  return (
    <div className="page-wrapper">
      <div className="page-header">
        <h1 className="page-title">Analytics</h1>
        <p className="page-subtitle">Gateway cost breakdown, settlement analysis, and volume trends</p>
      </div>

      {/* Summary stats */}
      {Object.keys(summary).length > 0 && (
        <div className="stats-grid mb-8">
          {Object.entries(summary).slice(0, 4).map(([key, val]) => (
            <div key={key} className="stat-card" style={{ '--card-accent-color': '#4f9cf9', '--card-accent-bg': 'rgba(79,156,249,0.12)' } as React.CSSProperties}>
              <div className="stat-label">{key.replace(/_/g, ' ')}</div>
              <div className="stat-value" style={{ fontSize: 22 }}>
                {typeof val === 'number' ? val.toLocaleString('en-IN', { maximumFractionDigits: 2 }) : String(val)}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Gateway filter */}
      <div className="filters-bar">
        <select className="form-select" style={{ width: 'auto' }} value={gateway} onChange={e => setGateway(e.target.value)}>
          <option value="">All Gateways</option>
          <option value="gateway_a">Gateway A</option>
          <option value="gateway_b">Gateway B</option>
        </select>
      </div>

      <div className="grid-2 mb-8">
        {/* Gateway cost bar chart */}
        <div className="card">
          <div className="card-header">
            <span className="card-title">
              <DollarSign size={16} color="var(--color-accent)" />
              Volume vs Fees by Gateway &amp; Currency
            </span>
          </div>
          <div className="card-body">
            {costsLoading ? (
              <div style={{ height: 280, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                <span className="spinner spinner-lg" />
              </div>
            ) : barData.length === 0 ? (
              <div className="empty-state" style={{ height: 280 }}>
                <div className="empty-state-icon">📊</div>
                <p className="empty-state-title">No cost data yet</p>
                <p className="empty-state-desc">Import gateway data to see cost analysis.</p>
              </div>
            ) : (
              <div style={{ height: 280 }}>
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={barData} barGap={4} barSize={18}>
                    <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.04)" />
                    <XAxis dataKey="name" tick={{ fill: '#475569', fontSize: 10 }} axisLine={false} tickLine={false} />
                    <YAxis tick={{ fill: '#475569', fontSize: 10 }} axisLine={false} tickLine={false} />
                    <Tooltip contentStyle={TOOLTIP_STYLE} />
                    <Legend iconType="circle" iconSize={8} wrapperStyle={{ fontSize: 12, color: '#94a3b8' }} />
                    <Bar dataKey="Gross Volume" fill="#4f9cf9" radius={[4, 4, 0, 0]} />
                    <Bar dataKey="Total Fees" fill="#ef4444" radius={[4, 4, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            )}
          </div>
        </div>

        {/* Gateway volume split pie */}
        <div className="card">
          <div className="card-header">
            <span className="card-title">
              <TrendingUp size={16} color="var(--color-cyan)" />
              Volume Split by Gateway
            </span>
          </div>
          <div className="card-body">
            {pieData.length === 0 ? (
              <div className="empty-state" style={{ height: 280 }}>
                <div className="empty-state-icon">🍕</div>
                <p className="empty-state-title">No data</p>
              </div>
            ) : (
              <div style={{ display: 'flex', alignItems: 'center', height: 280, gap: 24 }}>
                <div style={{ flex: 1, height: '100%' }}>
                  <ResponsiveContainer width="100%" height="100%">
                    <PieChart>
                      <Pie data={pieData} cx="50%" cy="50%" innerRadius={60} outerRadius={100} paddingAngle={3} dataKey="value">
                        {pieData.map((_, i) => <Cell key={i} fill={COLORS[i % COLORS.length]} />)}
                      </Pie>
                      <Tooltip contentStyle={TOOLTIP_STYLE} formatter={(v: any) => Number(v ?? 0).toLocaleString('en-IN')} />
                    </PieChart>
                  </ResponsiveContainer>
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                  {pieData.map((d, i) => (
                    <div key={d.name} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                      <span style={{ width: 10, height: 10, borderRadius: '50%', background: COLORS[i % COLORS.length], flexShrink: 0 }} />
                      <span style={{ fontSize: 13, color: 'var(--color-text-secondary)' }}>
                        {d.name === 'gateway_a' ? 'Gateway A' : 'Gateway B'}
                      </span>
                      <span style={{ fontSize: 13, fontWeight: 600, marginLeft: 8, color: 'var(--color-text-primary)' }}>
                        {d.value.toLocaleString('en-IN')}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Effective rate table */}
      {breakdowns.length > 0 && (
        <div className="card mb-8">
          <div className="card-header">
            <span className="card-title">
              <LineChartIcon size={16} color="var(--color-warning)" />
              Effective Rate Breakdown
            </span>
          </div>
          <div className="table-container" style={{ border: 'none', borderRadius: 0 }}>
            <table className="data-table">
              <thead>
                <tr>
                  <th>Gateway</th>
                  <th>Currency</th>
                  <th>Payment Method</th>
                  <th>Payments</th>
                  <th>Gross Volume</th>
                  <th>Total Fees</th>
                  <th>Tax</th>
                  <th>Eff. Rate %</th>
                </tr>
              </thead>
              <tbody>
                {breakdowns.slice(0, 20).map((b: { gateway: string; currency: string; payment_method: string | null; payment_count: number; gross_volume: number; total_fees: number; total_tax: number; effective_rate_pct: number }, i: number) => (
                  <tr key={i}>
                    <td><span className="badge badge-purple">{b.gateway}</span></td>
                    <td>{b.currency}</td>
                    <td className="text-sm text-muted">{b.payment_method ?? 'All'}</td>
                    <td>{b.payment_count?.toLocaleString('en-IN')}</td>
                    <td className="td-amount">{b.gross_volume?.toLocaleString('en-IN', { maximumFractionDigits: 2 })}</td>
                    <td className="td-amount text-danger">{b.total_fees?.toLocaleString('en-IN', { maximumFractionDigits: 2 })}</td>
                    <td className="td-amount">{b.total_tax?.toLocaleString('en-IN', { maximumFractionDigits: 2 })}</td>
                    <td>
                      <span style={{ color: effectiveRateColor(b.effective_rate_pct) }}>
                        {b.effective_rate_pct?.toFixed(3)}%
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Gateway B payout summary */}
      {gwbPayouts.length > 0 && (
        <div className="card">
          <div className="card-header">
            <span className="card-title">
              <Globe size={16} color="var(--color-success)" />
              Gateway B — Payout Summary
            </span>
          </div>
          <div className="table-container" style={{ border: 'none', borderRadius: 0 }}>
            <table className="data-table">
              <thead>
                <tr>
                  <th>Payout ID</th>
                  <th>Charge Count</th>
                  <th>Total Net</th>
                </tr>
              </thead>
              <tbody>
                {gwbPayouts.map((p: { payout_id: string; charge_count: number; total_net: number }) => (
                  <tr key={p.payout_id}>
                    <td className="td-mono">{p.payout_id}</td>
                    <td>{p.charge_count}</td>
                    <td className="td-amount">{p.total_net?.toLocaleString('en-IN', { maximumFractionDigits: 2 })}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}

function effectiveRateColor(rate: number) {
  if (rate > 3) return 'var(--color-danger)'
  if (rate > 2) return 'var(--color-warning)'
  return 'var(--color-success)'
}
