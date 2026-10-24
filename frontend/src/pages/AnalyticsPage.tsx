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
  const [chartCurrencySelection, setChartCurrencySelection] = useState('')

  const { data: costsData, isLoading: costsLoading } = useQuery({
    queryKey: ['gateway-costs', gateway],
    queryFn: () => fetchGatewayCosts(gateway || undefined),
  })

  const { data: settlData } = useQuery({
    queryKey: ['settlements'],
    queryFn: fetchSettlements,
  })

  const breakdowns = costsData?.breakdowns ?? []
  const monthlyBreakdowns = costsData?.monthly_breakdowns ?? []
  const monthlySettlementMetrics = settlData?.monthly_settlement_metrics ?? []
  const summary = costsData?.summary ?? {}

  // Prepare bar chart data: group by currency
  const comparableCurrencies: string[] = Array.from(new Set<string>(breakdowns
    .filter((b: { currency: string; fee_currency?: string }) => b.currency === b.fee_currency)
    .map((b: { currency: string }) => b.currency))).sort()
  const chartCurrency = comparableCurrencies.includes(chartCurrencySelection)
    ? chartCurrencySelection
    : comparableCurrencies.includes('INR') ? 'INR' : comparableCurrencies[0] ?? ''
  const barData = breakdowns.filter((b: { currency: string; fee_currency?: string }) => b.currency === b.fee_currency && b.currency === chartCurrency).slice(0, 10).map((b: { gateway: string; currency: string; payment_count: number; gross_volume: number; total_fees: number; effective_rate_pct: number }) => ({
    name: `${b.gateway?.toUpperCase() ?? ''} ${b.currency ?? ''}`,
    'Gross Volume': Math.round(b.gross_volume ?? 0),
    'Total Fees': Math.round(b.total_fees ?? 0),
    'Eff. Rate %': b.effective_rate_pct ? parseFloat(b.effective_rate_pct.toFixed(3)) : 0,
  }))

  // Pie for gateway split by volume
  const gatewayVolumes: Record<string, number> = {}
  breakdowns.forEach((b: { gateway: string; payment_count: number }) => {
    const gw = b.gateway ?? 'unknown'
    gatewayVolumes[gw] = (gatewayVolumes[gw] ?? 0) + (b.payment_count ?? 0)
  })
  const pieData = Object.entries(gatewayVolumes).map(([name, value]) => ({ name, value: Math.round(value) }))

  // Settlement data
  const gwbPayouts = settlData?.gateway_b_payout_summary?.sample_payouts ?? []
  const gwaSettlement = settlData?.gateway_a_settlement_summary ?? []

  return (
    <div className="page-wrapper">
      <div className="page-header">
        <h1 className="page-title">Analytics</h1>
            <p className="page-subtitle">Observed fees from imported gateway records, grouped by currency. These are not verified contract rates.</p>
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

      <div className="card mb-8">
        <div className="card-header">
          <span className="card-title"><LineChartIcon size={16} color="var(--color-accent)" /> Month-wise Gateway Costs</span>
          <span className="text-sm text-muted">Observed imported data</span>
        </div>
        <div className="table-container" style={{ border: 'none', borderRadius: 0 }}>
          {monthlyBreakdowns.length === 0 ? (
            <div className="empty-state" style={{ padding: 32 }}>
              <p className="empty-state-title">No dated payment records yet</p>
              <p className="empty-state-desc">Monthly figures use transaction dates from captured payments and gateway charge rows.</p>
            </div>
          ) : (
            <table className="data-table">
              <thead><tr><th>Month</th><th>Gateway</th><th>Payment currency</th><th>Transactions</th><th>Gross Volume</th><th>Observed Fees</th><th>Observed Tax</th><th>Observed cost</th><th>Effective Fee Rate</th></tr></thead>
              <tbody>{monthlyBreakdowns
                .filter((row: { gateway: string }) => !gateway || row.gateway === gateway)
                .map((row: { month: string; gateway: string; currency: string; fee_currency: string; tax_currency: string; transaction_count: number; gross_volume: number; observed_fees: number; observed_tax: number; observed_cost: number | null; observed_cost_currency: string | null; observed_cost_unavailable_reason: string | null; fee_records_missing_amount: number; tax_records_missing_amount: number; effective_fee_rate_pct: number | null }, i: number) => (
                  <tr key={`${row.month}-${row.gateway}-${row.currency}-${row.fee_currency}-${row.tax_currency}-${i}`}>
                    <td>{row.month}</td>
                    <td><span className="badge badge-purple">{row.gateway}</span></td>
                    <td>{row.currency}</td>
                    <td>{row.transaction_count.toLocaleString('en-IN')}</td>
                    <td className="td-amount">{row.currency} {row.gross_volume.toLocaleString('en-IN', { maximumFractionDigits: 2 })}</td>
                    <td className="td-amount">{row.fee_currency} {row.observed_fees.toLocaleString('en-IN', { maximumFractionDigits: 2 })}{row.fee_records_missing_amount ? ` (${row.fee_records_missing_amount} missing)` : ''}</td>
                    <td className="td-amount">{row.tax_currency} {row.observed_tax.toLocaleString('en-IN', { maximumFractionDigits: 2 })}{row.tax_records_missing_amount ? ` (${row.tax_records_missing_amount} missing)` : ''}</td>
                    <td className="td-amount">{row.observed_cost == null ? (row.observed_cost_unavailable_reason === 'missing_amounts' ? 'Incomplete amounts' : 'Currencies differ') : `${row.observed_cost_currency} ${row.observed_cost.toLocaleString('en-IN', { maximumFractionDigits: 2 })}`}</td>
                    <td>{row.effective_fee_rate_pct == null ? 'Not comparable across currencies' : `${row.effective_fee_rate_pct.toFixed(3)}%`}</td>
                  </tr>
                ))}</tbody>
            </table>
          )}
        </div>
        <p className="text-sm text-muted" style={{ padding: '0 16px 16px' }}>{costsData?.monthly_data_note}</p>
      </div>

      <div className="card mb-8">
        <div className="card-header">
          <span className="card-title"><LineChartIcon size={16} color="var(--color-cyan)" /> Monthly Settlement Timing</span>
          <span className="text-sm text-muted">Source-reported timing</span>
        </div>
        <div className="table-container" style={{ border: 'none', borderRadius: 0 }}>
          {monthlySettlementMetrics.length === 0 ? (
            <div className="empty-state" style={{ padding: 24 }}><p className="empty-state-title">No dated settlement records</p></div>
          ) : (
            <table className="data-table">
              <thead><tr><th>Transaction month</th><th>Gateway</th><th>Currency</th><th>Timing basis</th><th>Rows timed</th><th>Median hours</th><th>Average hours</th><th>Linked / settled</th><th>Explicitly unsettled</th><th>Unknown status</th><th>Missing time</th><th>Time/status conflict</th><th>Invalid negative</th></tr></thead>
              <tbody>{monthlySettlementMetrics
                .filter((row: { gateway: string }) => !gateway || row.gateway === gateway)
                .map((row: { month: string; gateway: string; currency: string; timing_basis: string; source_rows: number; timed_rows: number; median_hours: number | null; average_hours: number | null; settled_or_payout_linked: number; explicitly_unsettled: number; settlement_status_unknown: number; missing_completion_time: number; completion_time_unsettled_conflict: number; invalid_negative_duration: number }, i: number) => (
                  <tr key={`${row.month}-${row.gateway}-${row.currency}-${row.timing_basis}-${i}`}>
                    <td>{row.month}</td><td><span className="badge badge-purple">{row.gateway}</span></td><td>{row.currency}</td><td>{row.timing_basis}</td>
                    <td>{row.timed_rows} / {row.source_rows}</td><td>{row.median_hours == null ? '—' : `${row.median_hours.toLocaleString('en-IN')} h`}</td><td>{row.average_hours == null ? '—' : `${row.average_hours.toLocaleString('en-IN')} h`}</td><td>{row.settled_or_payout_linked}</td><td>{row.explicitly_unsettled}</td><td>{row.settlement_status_unknown}</td><td>{row.missing_completion_time}</td><td>{row.completion_time_unsettled_conflict}</td><td>{row.invalid_negative_duration}</td>
                  </tr>
                ))}</tbody>
            </table>
          )}
        </div>
        <p className="text-sm text-muted" style={{ padding: '0 16px 16px' }}>{settlData?.timing_data_note}</p>
      </div>

      <div className="grid-2 mb-8">
        {/* Gateway cost bar chart */}
        <div className="card">
          <div className="card-header">
            <span className="card-title">
              <DollarSign size={16} color="var(--color-accent)" />
              Volume vs Fees (same-currency rows only)
            </span>
          {comparableCurrencies.length > 1 && <select className="form-select" style={{ width: 'auto' }} value={chartCurrency} onChange={e => setChartCurrencySelection(e.target.value)} aria-label="Chart currency"><option value="" disabled>Select currency</option>{comparableCurrencies.map((currency: string) => <option key={currency} value={currency}>{currency}</option>)}</select>}
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
              Record Count by Gateway
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
                        {d.value.toLocaleString('en-IN')} records
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
                  <th>Total Fees ({'fee currency'})</th>
                  <th>Tax ({'tax currency'})</th>
                  <th>Eff. Rate %</th>
                </tr>
              </thead>
              <tbody>
                {breakdowns.slice(0, 20).map((b: { gateway: string; currency: string; fee_currency?: string; tax_currency?: string; payment_method: string | null; payment_count: number; gross_volume: number; total_fees: number; total_tax: number; effective_rate_pct: number | null }, i: number) => (
                  <tr key={i}>
                    <td><span className="badge badge-purple">{b.gateway}</span></td>
                    <td>{b.currency}</td>
                    <td className="text-sm text-muted">{b.payment_method ?? 'All'}</td>
                    <td>{b.payment_count?.toLocaleString('en-IN')}</td>
                    <td className="td-amount">{b.gross_volume?.toLocaleString('en-IN', { maximumFractionDigits: 2 })}</td>
                    <td className="td-amount text-danger">{b.fee_currency ?? b.currency} {b.total_fees?.toLocaleString('en-IN', { maximumFractionDigits: 2 })}</td>
                    <td className="td-amount">{b.tax_currency ?? b.currency} {b.total_tax?.toLocaleString('en-IN', { maximumFractionDigits: 2 })}</td>
                    <td>
                      <span style={{ color: b.effective_rate_pct == null ? 'var(--color-text-muted)' : effectiveRateColor(b.effective_rate_pct) }}>
                        {b.effective_rate_pct == null ? 'Not comparable across currencies' : `${b.effective_rate_pct.toFixed(3)}%`}
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
      {gwaSettlement.length > 0 && (
        <div className="card mb-8">
          <div className="card-header"><span className="card-title">Gateway A — Settlement Entries</span></div>
          <div className="table-container" style={{ border: 'none', borderRadius: 0 }}>
            <table className="data-table"><thead><tr><th>Entry Type</th><th>Currency</th><th>Settlement Records</th><th>Observed Credit</th></tr></thead>
              <tbody>{gwaSettlement.map((s: { transaction_type: string; currency: string; settlement_records: number; observed_credit: number }, i: number) => <tr key={i}>
                <td>{s.transaction_type.replace(/_/g, ' ')}</td><td>{s.currency}</td><td>{s.settlement_records.toLocaleString('en-IN')}</td><td>{s.currency} {s.observed_credit.toLocaleString('en-IN', { maximumFractionDigits: 2 })}</td>
              </tr>)}</tbody>
            </table>
          </div>
        </div>
      )}
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
                  <th>Currency</th>
                  <th>Charges / Balance Rows</th>
                  <th>Observed Net</th>
                </tr>
              </thead>
              <tbody>
                {gwbPayouts.map((p: { payout_id: string; currency: string; charge_count: number; balance_record_count: number; total_net: number }) => (
                  <tr key={`${p.payout_id}-${p.currency}`}>
                    <td className="td-mono">{p.payout_id}</td>
                    <td>{p.currency}</td>
                    <td>{p.charge_count} / {p.balance_record_count}</td>
                    <td className="td-amount">{p.currency} {p.total_net?.toLocaleString('en-IN', { maximumFractionDigits: 2 })}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="text-sm text-muted" style={{ padding: 12 }}>{settlData?.gateway_b_payout_summary?.amount_basis}</p>
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
