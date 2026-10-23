import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { DollarSign, Plus, Calculator, X, CheckCircle2 } from 'lucide-react'
import { fetchPricingRules, createPricingRule, createSavingsScenario } from '../api/client'
import { formatDate } from '../lib/format'
import type { PricingRule } from '../types'

export default function PricingPage() {
  const queryClient = useQueryClient()
  const [showAddRule, setShowAddRule] = useState(false)
  const [showScenario, setShowScenario] = useState(false)
  const [scenarioResult, setScenarioResult] = useState<Record<string, unknown> | null>(null)

  const { data: rules, isLoading } = useQuery({
    queryKey: ['pricing-rules'],
    queryFn: fetchPricingRules,
  })

  const createRuleMutation = useMutation({
    mutationFn: createPricingRule,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['pricing-rules'] })
      setShowAddRule(false)
    },
  })

  const scenarioMutation = useMutation({
    mutationFn: createSavingsScenario,
    onSuccess: (data) => {
      setScenarioResult(data)
    },
  })

  const pricingRules: PricingRule[] = rules ?? []

  return (
    <div className="page-wrapper">
      <div className="page-header" style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between' }}>
        <div>
          <h1 className="page-title">Pricing &amp; Savings</h1>
          <p className="page-subtitle">Configure gateway pricing rules and model cost-saving scenarios</p>
        </div>
        <div style={{ display: 'flex', gap: 12 }}>
          <button className="btn btn-secondary" onClick={() => setShowScenario(true)}>
            <Calculator size={15} /> Savings Scenario
          </button>
          <button className="btn btn-primary" onClick={() => setShowAddRule(true)}>
            <Plus size={15} /> Add Pricing Rule
          </button>
        </div>
      </div>

      {/* Pricing rules table */}
      <div className="card mb-8">
        <div className="card-header">
          <span className="card-title">
            <DollarSign size={16} color="var(--color-accent)" />
            Pricing Rules
          </span>
          <span style={{ fontSize: 12, color: 'var(--color-text-muted)' }}>{pricingRules.length} rules</span>
        </div>
        <div className="table-container" style={{ border: 'none', borderRadius: 0 }}>
          <table className="data-table">
            <thead>
              <tr>
                <th>Rule Name</th>
                <th>Gateway</th>
                <th>Currency</th>
                <th>Payment Method</th>
                <th>Fee Rate %</th>
                <th>Fixed Fee</th>
                <th>Tax on Fee %</th>
                <th>Type</th>
                <th>Created</th>
              </tr>
            </thead>
            <tbody>
              {isLoading ? (
                <tr><td colSpan={9} style={{ textAlign: 'center', padding: 48 }}><span className="spinner spinner-lg" /></td></tr>
              ) : pricingRules.length === 0 ? (
                <tr>
                  <td colSpan={9}>
                    <div className="empty-state">
                      <div className="empty-state-icon">💰</div>
                      <p className="empty-state-title">No pricing rules yet</p>
                      <p className="empty-state-desc">Add pricing rules to model gateway fees and compute savings scenarios.</p>
                    </div>
                  </td>
                </tr>
              ) : pricingRules.map(rule => (
                <tr key={rule.id}>
                  <td style={{ fontWeight: 500 }}>{rule.rule_name}</td>
                  <td><span className="badge badge-purple">{rule.gateway}</span></td>
                  <td>{rule.currency ?? '—'}</td>
                  <td className="text-sm text-muted">{rule.payment_method ?? 'All'}</td>
                  <td className="td-amount">{rule.fee_rate_pct ? `${rule.fee_rate_pct}%` : '—'}</td>
                  <td className="td-amount">{rule.fixed_fee ?? '—'}</td>
                  <td className="td-amount">{rule.tax_on_fee_pct ? `${rule.tax_on_fee_pct}%` : '—'}</td>
                  <td>
                    <span className={`badge ${rule.is_illustrative ? 'badge-warning' : 'badge-success'}`}>
                      {rule.is_illustrative ? 'Illustrative' : 'Contract'}
                    </span>
                  </td>
                  <td className="text-sm text-muted">{formatDate(rule.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Add Rule Modal */}
      {showAddRule && (
        <AddPricingRuleModal
          onClose={() => setShowAddRule(false)}
          onSubmit={(data) => createRuleMutation.mutate(data)}
          loading={createRuleMutation.isPending}
        />
      )}

      {/* Savings Scenario Modal */}
      {showScenario && (
        <SavingsScenarioModal
          rules={pricingRules}
          onClose={() => { setShowScenario(false); setScenarioResult(null) }}
          onSubmit={(data) => scenarioMutation.mutate(data)}
          loading={scenarioMutation.isPending}
          result={scenarioResult}
        />
      )}
    </div>
  )
}

function AddPricingRuleModal({ onClose, onSubmit, loading }: {
  onClose: () => void
  onSubmit: (data: unknown) => void
  loading: boolean
}) {
  const [form, setForm] = useState({
    rule_name: '',
    gateway: 'gateway_a',
    currency: 'INR',
    payment_method: '',
    fee_rate_pct: '',
    fixed_fee: '',
    tax_on_fee_pct: '',
    is_illustrative: true,
    notes: '',
  })

  const set = (k: string, v: string | boolean) => setForm(p => ({ ...p, [k]: v }))

  const handleSubmit = () => {
    onSubmit({
      rule_name: form.rule_name,
      gateway: form.gateway,
      currency: form.currency || undefined,
      payment_method: form.payment_method || undefined,
      fee_rate_pct: form.fee_rate_pct ? parseFloat(form.fee_rate_pct) : undefined,
      fixed_fee: form.fixed_fee ? parseFloat(form.fixed_fee) : undefined,
      tax_on_fee_pct: form.tax_on_fee_pct ? parseFloat(form.tax_on_fee_pct) : undefined,
      is_illustrative: form.is_illustrative,
      notes: form.notes || undefined,
    })
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" onClick={e => e.stopPropagation()}>
        <div className="modal-header">
          <span className="modal-title">Add Pricing Rule</span>
          <button className="btn btn-ghost btn-sm" onClick={onClose}><X size={16} /></button>
        </div>
        <div className="modal-body">
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
            <div className="form-group" style={{ gridColumn: '1/-1' }}>
              <label className="form-label">Rule Name *</label>
              <input className="form-input" placeholder="e.g. GWA Standard INR" value={form.rule_name} onChange={e => set('rule_name', e.target.value)} />
            </div>
            <div className="form-group">
              <label className="form-label">Gateway</label>
              <select className="form-select" value={form.gateway} onChange={e => set('gateway', e.target.value)}>
                <option value="gateway_a">Gateway A</option>
                <option value="gateway_b">Gateway B</option>
              </select>
            </div>
            <div className="form-group">
              <label className="form-label">Currency</label>
              <input className="form-input" placeholder="INR, USD…" value={form.currency} onChange={e => set('currency', e.target.value)} />
            </div>
            <div className="form-group">
              <label className="form-label">Payment Method</label>
              <input className="form-input" placeholder="credit_card, upi…" value={form.payment_method} onChange={e => set('payment_method', e.target.value)} />
            </div>
            <div className="form-group">
              <label className="form-label">Fee Rate %</label>
              <input className="form-input" type="number" step="0.01" placeholder="2.0" value={form.fee_rate_pct} onChange={e => set('fee_rate_pct', e.target.value)} />
            </div>
            <div className="form-group">
              <label className="form-label">Fixed Fee</label>
              <input className="form-input" type="number" step="0.01" placeholder="0.00" value={form.fixed_fee} onChange={e => set('fixed_fee', e.target.value)} />
            </div>
            <div className="form-group">
              <label className="form-label">Tax on Fee %</label>
              <input className="form-input" type="number" step="0.01" placeholder="18.0" value={form.tax_on_fee_pct} onChange={e => set('tax_on_fee_pct', e.target.value)} />
            </div>
            <div className="form-group" style={{ gridColumn: '1/-1' }}>
              <label className="form-label">Notes</label>
              <input className="form-input" placeholder="Contract notes…" value={form.notes} onChange={e => set('notes', e.target.value)} />
            </div>
            <div className="form-group" style={{ gridColumn: '1/-1', flexDirection: 'row', alignItems: 'center' }}>
              <input type="checkbox" id="is_illustrative" checked={form.is_illustrative} onChange={e => set('is_illustrative', e.target.checked)} style={{ marginRight: 8, accentColor: 'var(--color-accent)' }} />
              <label htmlFor="is_illustrative" className="form-label" style={{ marginBottom: 0 }}>Mark as Illustrative (not a verified contract rate)</label>
            </div>
          </div>
          <div style={{ marginTop: 24, display: 'flex', justifyContent: 'flex-end', gap: 12 }}>
            <button className="btn btn-secondary" onClick={onClose}>Cancel</button>
            <button className="btn btn-primary" onClick={handleSubmit} disabled={!form.rule_name || loading}>
              {loading ? <><span className="spinner" />Saving…</> : 'Save Rule'}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

function SavingsScenarioModal({ rules, onClose, onSubmit, loading, result }: {
  rules: PricingRule[]
  onClose: () => void
  onSubmit: (data: unknown) => void
  loading: boolean
  result: Record<string, unknown> | null
}) {
  const [form, setForm] = useState({
    name: '',
    current_gateway: 'gateway_a',
    alternative_gateway: 'gateway_b',
    currency: 'INR',
    eligible_volume: '',
    current_pricing_rule_id: '',
    alternative_pricing_rule_id: '',
  })

  const set = (k: string, v: string) => setForm(p => ({ ...p, [k]: v }))

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" onClick={e => e.stopPropagation()} style={{ maxWidth: 700 }}>
        <div className="modal-header">
          <span className="modal-title">Savings Scenario</span>
          <button className="btn btn-ghost btn-sm" onClick={onClose}><X size={16} /></button>
        </div>
        <div className="modal-body">
          {result ? (
            <div>
              <div className="ai-panel" style={{ marginBottom: 20 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 16 }}>
                  <CheckCircle2 size={20} color="var(--color-success)" />
                  <span style={{ fontSize: 16, fontWeight: 700, color: 'var(--color-text-primary)' }}>Scenario: {result.name as string}</span>
                </div>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 16 }}>
                  {[
                    { label: 'Eligible Volume', value: result.eligible_volume as string },
                    { label: 'Current Est. Fee', value: result.current_estimated_fee as string ?? 'N/A' },
                    { label: 'Alternative Est. Fee', value: result.alternative_estimated_fee as string ?? 'N/A' },
                  ].map(({ label, value }) => (
                    <div key={label} style={{ textAlign: 'center' }}>
                      <div style={{ fontSize: 11, color: 'var(--color-text-muted)', textTransform: 'uppercase', letterSpacing: '0.5px' }}>{label}</div>
                      <div style={{ fontSize: 20, fontWeight: 800, color: 'var(--color-text-primary)', marginTop: 4, fontFamily: 'var(--font-mono)' }}>{value}</div>
                    </div>
                  ))}
                </div>
                {Boolean(result.estimated_difference) && (
                  <div style={{ marginTop: 20, textAlign: 'center' }}>
                    <div style={{ fontSize: 11, color: 'var(--color-text-muted)', textTransform: 'uppercase', letterSpacing: '0.5px', marginBottom: 4 }}>Estimated Difference</div>
                    <div style={{ fontSize: 32, fontWeight: 800, color: parseFloat(result.estimated_difference as string) > 0 ? 'var(--color-success)' : 'var(--color-danger)', fontFamily: 'var(--font-mono)' }}>
                      {result.estimated_difference as string}
                    </div>
                  </div>
                )}
              </div>
              {(result.limitations as string[])?.length > 0 && (
                <div style={{ padding: '12px 16px', background: 'var(--color-warning-dim)', borderRadius: 10, border: '1px solid rgba(245,158,11,0.2)' }}>
                  <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--color-warning)', marginBottom: 8 }}>⚠ Limitations</div>
                  {(result.limitations as string[]).map((l, i) => (
                    <div key={i} style={{ fontSize: 12, color: 'var(--color-text-secondary)', marginBottom: 4 }}>• {l}</div>
                  ))}
                  <div style={{ fontSize: 11, color: 'var(--color-text-muted)', marginTop: 8 }}>{result.assumptions_note as string}</div>
                </div>
              )}
              <div style={{ marginTop: 20, textAlign: 'right' }}>
                <button className="btn btn-secondary" onClick={onClose}>Close</button>
              </div>
            </div>
          ) : (
            <div>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
                <div className="form-group" style={{ gridColumn: '1/-1' }}>
                  <label className="form-label">Scenario Name</label>
                  <input className="form-input" placeholder="Q4 Gateway Switch Analysis" value={form.name} onChange={e => set('name', e.target.value)} />
                </div>
                <div className="form-group">
                  <label className="form-label">Current Gateway</label>
                  <select className="form-select" value={form.current_gateway} onChange={e => set('current_gateway', e.target.value)}>
                    <option value="gateway_a">Gateway A</option>
                    <option value="gateway_b">Gateway B</option>
                  </select>
                </div>
                <div className="form-group">
                  <label className="form-label">Alternative Gateway</label>
                  <select className="form-select" value={form.alternative_gateway} onChange={e => set('alternative_gateway', e.target.value)}>
                    <option value="gateway_b">Gateway B</option>
                    <option value="gateway_a">Gateway A</option>
                  </select>
                </div>
                <div className="form-group">
                  <label className="form-label">Currency</label>
                  <input className="form-input" placeholder="INR" value={form.currency} onChange={e => set('currency', e.target.value)} />
                </div>
                <div className="form-group">
                  <label className="form-label">Eligible Volume</label>
                  <input className="form-input" type="number" placeholder="1000000" value={form.eligible_volume} onChange={e => set('eligible_volume', e.target.value)} />
                </div>
                <div className="form-group">
                  <label className="form-label">Current Pricing Rule</label>
                  <select className="form-select" value={form.current_pricing_rule_id} onChange={e => set('current_pricing_rule_id', e.target.value)}>
                    <option value="">None</option>
                    {rules.map(r => <option key={r.id} value={r.id}>{r.rule_name} ({r.gateway})</option>)}
                  </select>
                </div>
                <div className="form-group">
                  <label className="form-label">Alternative Pricing Rule</label>
                  <select className="form-select" value={form.alternative_pricing_rule_id} onChange={e => set('alternative_pricing_rule_id', e.target.value)}>
                    <option value="">None</option>
                    {rules.map(r => <option key={r.id} value={r.id}>{r.rule_name} ({r.gateway})</option>)}
                  </select>
                </div>
              </div>
              <div style={{ marginTop: 24, display: 'flex', justifyContent: 'flex-end', gap: 12 }}>
                <button className="btn btn-secondary" onClick={onClose}>Cancel</button>
                <button className="btn btn-primary" onClick={() => onSubmit({ ...form, eligible_volume: parseFloat(form.eligible_volume || '0'), current_pricing_rule_id: form.current_pricing_rule_id || undefined, alternative_pricing_rule_id: form.alternative_pricing_rule_id || undefined })} disabled={!form.name || !form.eligible_volume || loading}>
                  {loading ? <><span className="spinner" />Calculating…</> : <><Calculator size={15} />Calculate</>}
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
