import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { DollarSign, Plus, Calculator, X, Pencil, Trash2 } from 'lucide-react'
import { fetchPricingRules, createPricingRule, createSavingsScenario, updatePricingRule, deletePricingRule, fetchSavingsScenarios } from '../api/client'
import { formatDate } from '../lib/format'
import type { PricingRule, SavingsScenario } from '../types'

export default function PricingPage() {
  const queryClient = useQueryClient()
  const [showAddRule, setShowAddRule] = useState(false)
  const [editRule, setEditRule] = useState<PricingRule | null>(null)
  const [showScenario, setShowScenario] = useState(false)
  const [scenarioResult, setScenarioResult] = useState<Record<string, unknown> | null>(null)

  const { data: rules, isLoading } = useQuery({
    queryKey: ['pricing-rules'],
    queryFn: fetchPricingRules,
  })
  const { data: savedScenarios, isLoading: scenariosLoading, error: scenariosError } = useQuery({
    queryKey: ['savings-scenarios'],
    queryFn: fetchSavingsScenarios,
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
      queryClient.invalidateQueries({ queryKey: ['savings-scenarios'] })
    },
  })

  const updateRuleMutation = useMutation({
    mutationFn: ({ id, body }: { id: string; body: unknown }) => updatePricingRule(id, body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['pricing-rules'] })
      setEditRule(null)
    },
  })

  const deleteRuleMutation = useMutation({
    mutationFn: deletePricingRule,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['pricing-rules'] }),
  })

  const pricingRules: PricingRule[] = rules ?? []
  const apiError = (error: unknown) => {
    const detail = (error as { response?: { data?: { detail?: unknown } }; message?: string })?.response?.data?.detail
    if (Array.isArray(detail)) {
      return detail.map(item => typeof item === 'object' && item !== null && 'msg' in item
        ? String((item as { msg: unknown }).msg) : String(item)).join('; ')
    }
    if (typeof detail === 'string') return detail
    if (detail && typeof detail === 'object' && 'message' in detail) {
      const issues = 'issues' in detail && Array.isArray((detail as { issues?: unknown }).issues)
        ? (detail as { issues: unknown[] }).issues.map(String).join('; ')
        : ''
      return `${String((detail as { message: unknown }).message)}${issues ? ` ${issues}` : ''}`
    }
    return (error as { message?: string })?.message ?? 'Request failed. Please try again.'
  }

  return (
    <div className="page-wrapper pricing-page">
      <div className="page-header" style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between' }}>
        <div>
          <h1 className="page-title">Pricing &amp; Savings</h1>
          <p className="page-subtitle">Compare configured gateway pricing assumptions for a specific currency, country and payment method</p>
        </div>
        <div style={{ display: 'flex', gap: 12 }}>
          <button className="btn btn-secondary" onClick={() => { scenarioMutation.reset(); setScenarioResult(null); setShowScenario(true) }}>
            <Calculator size={15} /> Savings Scenario
          </button>
          <button className="btn btn-primary pricing-primary" onClick={() => { createRuleMutation.reset(); setShowAddRule(true) }}>
            <Plus size={15} /> Add Pricing Rule
          </button>
        </div>
      </div>

      <div className="pricing-note">
        Pricing rules are entered assumptions, not verified contract rates. New rules are labelled <strong>Illustrative</strong>; estimates are not guaranteed savings.
      </div>

      {(deleteRuleMutation.error || createRuleMutation.error || updateRuleMutation.error) && (
        <div className="pricing-error" role="alert">{apiError(deleteRuleMutation.error || createRuleMutation.error || updateRuleMutation.error)}</div>
      )}

      {/* Pricing rules table */}
      <div className="pricing-card mb-8">
        <div className="card-header">
          <span className="pricing-card-title"><DollarSign size={17} />Pricing Rules</span>
          <span style={{ fontSize: 12, color: 'var(--color-text-muted)' }}>{pricingRules.length} rules</span>
        </div>
        <div className="table-container" style={{ border: 'none', borderRadius: 0 }}>
          <table className="data-table pricing-table">
            <colgroup>
              <col style={{ width: 220 }} /><col style={{ width: 120 }} /><col style={{ width: 95 }} />
              <col style={{ width: 130 }} /><col style={{ width: 150 }} /><col style={{ width: 150 }} />
              <col style={{ width: 150 }} /><col style={{ width: 145 }} /><col style={{ width: 185 }} />
              <col style={{ width: 165 }} /><col style={{ width: 105 }} />
            </colgroup>
            <thead>
              <tr>
                <th>Rule Name</th>
                <th>Gateway</th>
                <th>Currency</th>
                <th>Country</th>
                <th>Payment Method</th>
                <th>Fee Rate %</th>
                <th>Fixed Fee</th>
                <th>Tax on Fee %</th>
                <th>Type</th>
                <th>Created</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {isLoading ? (
                <tr><td colSpan={11} style={{ textAlign: 'center', padding: 48 }}><span className="spinner spinner-lg" /></td></tr>
              ) : pricingRules.length === 0 ? (
                <tr>
                  <td colSpan={11}>
                    <div className="empty-state">
                      <p className="empty-state-title">No pricing rules yet</p>
                      <p className="empty-state-desc">Add pricing rules to model gateway fees and compute savings scenarios.</p>
                    </div>
                  </td>
                </tr>
              ) : pricingRules.map(rule => (
                <tr key={rule.id}>
                  <td className="pricing-rule-name" title={rule.rule_name}>{rule.rule_name}</td>
                  <td><span className="pricing-gateway">{gatewayLabel(rule.gateway)}</span></td>
                  <td>{rule.currency ?? '—'}</td>
                  <td className="pricing-scope-value" title={rule.country ?? 'All / unspecified'}>{rule.country ?? 'All / unspecified'}</td>
                  <td className="text-sm text-muted pricing-scope-value" title={rule.payment_method ?? 'All'}>{rule.payment_method ?? 'All'}</td>
                  <td className="td-amount">{rule.fee_rate_pct === null || rule.fee_rate_pct === undefined ? <span title="No fee rate is configured for this rule">Not configured</span> : `${formatPercent(rule.fee_rate_pct)}%`}</td>
                  <td className="td-amount">{formatRuleFixedFee(rule)}</td>
                  <td className="td-amount">{rule.tax_on_fee_pct === null || rule.tax_on_fee_pct === undefined ? 'Not configured' : `${formatPercent(rule.tax_on_fee_pct)}%`}</td>
                  <td>
                    <span className={`badge pricing-type-badge ${rule.is_illustrative ? 'badge-warning' : 'badge-info'}`}>
                      {rule.is_illustrative ? 'Illustrative assumption' : 'Unverified input'}
                    </span>
                  </td>
                  <td className="text-sm text-muted pricing-created" title={formatDate(rule.created_at)}>{formatDate(rule.created_at)}</td>
                  <td><div className="pricing-row-actions">
                    <button className="pricing-icon-button" aria-label={`Edit ${rule.rule_name}`} title="Edit rule" onClick={() => { updateRuleMutation.reset(); setEditRule(rule) }}><Pencil size={15} /></button>
                    <button className="pricing-icon-button pricing-delete" aria-label={`Delete ${rule.rule_name}`} title="Delete rule" disabled={deleteRuleMutation.isPending} onClick={() => {
                      if (window.confirm(`Delete “${rule.rule_name}”? Saved scenarios that use this rule prevent deletion.`)) deleteRuleMutation.mutate(rule.id)
                    }}><Trash2 size={15} /></button>
                  </div></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="pricing-card pricing-history-card">
        <div className="card-header">
          <span className="pricing-card-title"><Calculator size={17} />Saved Scenarios</span>
          <span style={{ fontSize: 12, color: 'var(--color-text-muted)' }}>{savedScenarios?.length ?? 0} saved</span>
        </div>
        <p className="pricing-history-note">Configured fixed fees are added once per scenario, not per transaction; transaction count is not modeled.</p>
        {scenariosError ? (
          <div className="pricing-error" role="alert">Saved scenario history could not be loaded.</div>
        ) : (
          <div className="table-container pricing-history-scroll">
            <table className="data-table pricing-table pricing-history-table">
              <colgroup>
                <col style={{ width: 210 }} /><col style={{ width: 190 }} /><col style={{ width: 145 }} />
                <col style={{ width: 150 }} /><col style={{ width: 150 }} /><col style={{ width: 150 }} />
                <col style={{ width: 185 }} /><col style={{ width: 175 }} />
              </colgroup>
              <thead><tr>
                <th>Scenario</th><th>Gateway Comparison</th><th>Payment Scope</th><th>Payment Value</th>
                <th>Current Estimate</th><th>Alternative Estimate</th><th>Estimated Difference</th><th>Saved</th>
              </tr></thead>
              <tbody>
                {scenariosLoading ? (
                  <tr><td colSpan={8} style={{ textAlign: 'center', padding: 32 }}><span className="spinner" /></td></tr>
                ) : (savedScenarios ?? []).length === 0 ? (
                  <tr><td colSpan={8} className="text-muted">No saved scenarios yet. Run a scenario to keep its estimate here.</td></tr>
                ) : (savedScenarios ?? []).map((scenario: SavingsScenario) => {
                  const difference = scenario.estimated_difference == null ? null : Number(scenario.estimated_difference)
                  return <tr key={scenario.id ?? scenario.scenario_id}>
                    <td className="pricing-rule-name" title={scenario.name}>{scenario.name}</td>
                    <td>{gatewayLabel(scenario.current_gateway)} → {gatewayLabel(scenario.alternative_gateway)}</td>
                    <td className="pricing-scope-value">{[scenario.country, scenario.payment_method].filter(Boolean).join(' · ') || 'General'}</td>
                    <td className="td-amount">{formatMoney(scenario.eligible_volume, scenario.currency)}</td>
                    <td className="td-amount">{scenario.current_estimated_fee == null ? 'Not available' : formatMoney(scenario.current_estimated_fee, scenario.currency)}</td>
                    <td className="td-amount">{scenario.alternative_estimated_fee == null ? 'Not available' : formatMoney(scenario.alternative_estimated_fee, scenario.currency)}</td>
                    <td className={`td-amount ${difference !== null && difference > 0 ? 'pricing-positive' : difference !== null && difference < 0 ? 'pricing-negative' : ''}`}>
                      {difference === null ? 'Not available' : `${difference > 0 ? 'Lower estimate' : difference < 0 ? 'Higher estimate' : 'No difference'} · ${formatMoney(Math.abs(difference).toFixed(2), scenario.currency)}`}
                    </td>
                    <td className="pricing-created">{scenario.created_at ? formatDate(scenario.created_at) : '—'}</td>
                  </tr>
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Add Rule Modal */}
      {(showAddRule || editRule) && (
        <AddPricingRuleModal
          key={editRule?.id ?? 'new-pricing-rule'}
          rule={editRule}
          onClose={() => { setShowAddRule(false); setEditRule(null) }}
          onSubmit={(data) => editRule ? updateRuleMutation.mutate({ id: editRule.id, body: data }) : createRuleMutation.mutate(data)}
          loading={createRuleMutation.isPending || updateRuleMutation.isPending}
          error={(editRule ? updateRuleMutation.error : createRuleMutation.error) ? apiError(editRule ? updateRuleMutation.error : createRuleMutation.error) : null}
        />
      )}

      {/* Savings Scenario Modal */}
      {showScenario && (
        <SavingsScenarioModal
          rules={pricingRules}
          onClose={() => { setShowScenario(false); setScenarioResult(null) }}
          onSubmit={(data) => scenarioMutation.mutate(data)}
          loading={scenarioMutation.isPending}
          error={scenarioMutation.error ? apiError(scenarioMutation.error) : null}
          result={scenarioResult}
        />
      )}
    </div>
  )
}

function gatewayLabel(gateway: string | undefined): string {
  if (gateway === 'gateway_a') return 'Gateway A'
  if (gateway === 'gateway_b') return 'Gateway B'
  return 'Gateway unavailable'
}

function formatPercent(value: string): string {
  const number = Number(value)
  return Number.isFinite(number)
    ? new Intl.NumberFormat('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(number)
    : 'Not configured'
}

function formatMoney(value: string | number, currency?: string): string {
  const amount = Number(value)
  if (!Number.isFinite(amount)) return 'Not available'
  const code = currency?.trim().toUpperCase() || 'INR'
  try {
    return new Intl.NumberFormat('en-IN', {
      style: 'currency', currency: code, minimumFractionDigits: 2, maximumFractionDigits: 2,
    }).format(amount)
  } catch {
    return `${code} ${amount.toFixed(2)}`
  }
}

function formatRuleFixedFee(rule: PricingRule): string {
  if (rule.fixed_fee == null) return 'Not configured'
  const currency = rule.fixed_fee_currency || rule.currency
  if (currency) return formatMoney(rule.fixed_fee, currency)
  const amount = Number(rule.fixed_fee)
  return Number.isFinite(amount)
    ? `${new Intl.NumberFormat('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(amount)} (currency missing)`
    : 'Not available'
}

function toLocalDateTime(value?: string | null): string {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  const pad = (part: number) => String(part).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`
}

function fromLocalDateTime(value: string): string | null {
  return value ? new Date(value).toISOString() : null
}

function AddPricingRuleModal({ rule, onClose, onSubmit, loading, error }: {
  rule: PricingRule | null
  onClose: () => void
  onSubmit: (data: unknown) => void
  loading: boolean
  error: string | null
}) {
  const [form, setForm] = useState(() => ({
    rule_name: rule?.rule_name ?? '',
    gateway: rule?.gateway ?? 'gateway_a',
    currency: rule ? (rule.currency ?? '') : 'INR',
    fixed_fee_currency: rule ? (rule.fixed_fee_currency ?? '') : 'INR',
    country: rule?.country ?? '',
    payment_method: rule?.payment_method ?? '',
    fee_rate_pct: rule?.fee_rate_pct ?? '',
    fixed_fee: rule?.fixed_fee ?? '',
    tax_on_fee_pct: rule?.tax_on_fee_pct ?? '',
    min_fee: rule?.min_fee ?? '',
    max_fee: rule?.max_fee ?? '',
    effective_from: toLocalDateTime(rule?.effective_from),
    effective_to: toLocalDateTime(rule?.effective_to),
    is_international: rule?.is_international == null ? '' : rule.is_international ? 'true' : 'false',
    is_illustrative: rule?.is_illustrative ?? true,
    notes: rule?.notes ?? '',
  }))

  const set = (k: string, v: string | boolean) => setForm(p => ({ ...p, [k]: v }))
  const invalidNumbers = [
    { value: form.fee_rate_pct, max: 100 },
    { value: form.fixed_fee, max: undefined },
    { value: form.tax_on_fee_pct, max: 100 },
    { value: form.min_fee, max: undefined },
    { value: form.max_fee, max: undefined },
  ].some(({ value, max }) => {
    if (value === '') return false
    const number = Number(value)
    return !Number.isFinite(number) || number < 0 || (max !== undefined && number > max)
  })

  const invalidCurrency = form.currency !== '' && !/^[A-Z]{3}$/.test(form.currency.trim().toUpperCase())
  const invalidFeeCurrency = form.fixed_fee_currency !== '' && !/^[A-Z]{3}$/.test(form.fixed_fee_currency.trim().toUpperCase())
  const invalidCountry = form.country !== '' && !/^[A-Z]{2}$/.test(form.country.trim().toUpperCase())
  const invalidEffectiveRange = Boolean(form.effective_from && form.effective_to && form.effective_from > form.effective_to)

  const handleSubmit = () => {
    onSubmit({
      rule_name: form.rule_name,
      gateway: form.gateway,
      currency: form.currency.trim() ? form.currency.trim().toUpperCase() : null,
      country: form.country.trim() ? form.country.trim().toUpperCase() : null,
      is_international: form.is_international === '' ? null : form.is_international === 'true',
      payment_method: form.payment_method.trim() || null,
      fee_rate_pct: form.fee_rate_pct !== '' ? parseFloat(form.fee_rate_pct) : null,
      fixed_fee: form.fixed_fee !== '' ? parseFloat(form.fixed_fee) : null,
      fixed_fee_currency: form.fixed_fee_currency.trim() ? form.fixed_fee_currency.trim().toUpperCase() : null,
      tax_on_fee_pct: form.tax_on_fee_pct !== '' ? parseFloat(form.tax_on_fee_pct) : null,
      min_fee: form.min_fee !== '' ? parseFloat(form.min_fee) : null,
      max_fee: form.max_fee !== '' ? parseFloat(form.max_fee) : null,
      effective_from: rule && form.effective_from === toLocalDateTime(rule.effective_from)
        ? rule.effective_from ?? null : fromLocalDateTime(form.effective_from),
      effective_to: rule && form.effective_to === toLocalDateTime(rule.effective_to)
        ? rule.effective_to ?? null : fromLocalDateTime(form.effective_to),
      is_illustrative: form.is_illustrative,
      notes: form.notes.trim() || null,
    })
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" onClick={e => e.stopPropagation()}>
        <div className="modal-header">
          <span className="modal-title">{rule ? 'Edit Pricing Rule' : 'Add Pricing Rule'}</span>
          <button className="btn btn-ghost btn-sm" onClick={onClose}><X size={16} /></button>
        </div>
        <div className="modal-body">
          {error && <div role="alert" className="text-sm" style={{ color: 'var(--color-danger)', marginBottom: 16 }}>{error}</div>}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
            <div className="form-group" style={{ gridColumn: '1/-1' }}>
              <label className="form-label">Rule Name *</label>
              <input className="form-input" maxLength={255} placeholder="e.g. Gateway A India card (illustrative)" value={form.rule_name} onChange={e => set('rule_name', e.target.value)} />
            </div>
            <div className="form-group">
              <label className="form-label">Gateway</label>
              <select className="form-select" value={form.gateway} onChange={e => set('gateway', e.target.value)}>
                <option value="gateway_a">Gateway A</option>
                <option value="gateway_b">Gateway B</option>
              </select>
            </div>
            <div className="form-group">
              <label className="form-label">Rule currency</label>
              <input className="form-input" maxLength={3} placeholder="INR" value={form.currency} onChange={e => {
                const value = e.target.value.toUpperCase()
                setForm(previous => ({ ...previous, currency: value,
                  fixed_fee_currency: !previous.fixed_fee_currency || previous.fixed_fee_currency === previous.currency ? value : previous.fixed_fee_currency,
                }))
              }} />
              <small className="pricing-help">Three-letter code, for example INR or USD.</small>
            </div>
            <div className="form-group">
              <label className="form-label">Payment method</label>
              <input className="form-input" maxLength={50} placeholder="card, upi, netbanking" value={form.payment_method} onChange={e => set('payment_method', e.target.value.toLowerCase())} />
              <small className="pricing-help">Use the same lower-case method value in scenarios.</small>
            </div>
            <div className="form-group">
              <label className="form-label">Country code (optional)</label>
              <input className="form-input" maxLength={2} placeholder="IN" value={form.country} onChange={e => set('country', e.target.value.toUpperCase())} />
              <small className="pricing-help">Two-letter code, for example IN or US.</small>
            </div>
            <div className="form-group">
              <label className="form-label">Percentage fee (%)</label>
              <input className="form-input" type="number" min="0" max="100" step="0.01" placeholder="2.0" value={form.fee_rate_pct} onChange={e => set('fee_rate_pct', e.target.value)} />
              <small className="pricing-help">Applied to eligible payment value; enter 0–100.</small>
            </div>
            <div className="form-group">
              <label className="form-label">Fixed fee</label>
              <input className="form-input" type="number" min="0" step="0.01" placeholder="0.00" value={form.fixed_fee} onChange={e => set('fixed_fee', e.target.value)} />
              <small className="pricing-help">Added once per scenario, not once per transaction.</small>
            </div>
            <div className="form-group">
              <label className="form-label">Fixed-fee currency</label>
              <input className="form-input" maxLength={3} placeholder="Defaults to rule currency" value={form.fixed_fee_currency} onChange={e => set('fixed_fee_currency', e.target.value.toUpperCase())} />
              <small className="pricing-help">Defaults to rule currency when left blank.</small>
            </div>
            <div className="form-group" style={{ gridColumn: '1/-1' }}>
              <label className="form-label">Tax on fee (%)</label>
              <input className="form-input" type="number" min="0" max="100" step="0.01" placeholder="18.0" value={form.tax_on_fee_pct} onChange={e => set('tax_on_fee_pct', e.target.value)} />
              <small className="pricing-help">Applied to the calculated fee after any minimum/maximum cap.</small>
            </div>
            <div className="form-group">
              <label className="form-label">Minimum fee (optional)</label>
              <input className="form-input" type="number" min="0" step="0.01" placeholder="No minimum" value={form.min_fee} onChange={e => set('min_fee', e.target.value)} />
            </div>
            <div className="form-group">
              <label className="form-label">Maximum fee (optional)</label>
              <input className="form-input" type="number" min="0" step="0.01" placeholder="No maximum" value={form.max_fee} onChange={e => set('max_fee', e.target.value)} />
            </div>
            <div className="form-group">
              <label className="form-label">Effective from (optional)</label>
              <input className="form-input" type="datetime-local" value={form.effective_from} onChange={e => set('effective_from', e.target.value)} />
            </div>
            <div className="form-group">
              <label className="form-label">Effective to (optional)</label>
              <input className="form-input" type="datetime-local" value={form.effective_to} onChange={e => set('effective_to', e.target.value)} />
            </div>
            <div className="form-group">
              <label className="form-label">International scope</label>
              <select className="form-select" value={form.is_international} onChange={e => set('is_international', e.target.value)}>
                <option value="">Unspecified</option>
                <option value="false">Domestic</option>
                <option value="true">International</option>
              </select>
            </div>
            <div className="form-group" style={{ gridColumn: '1/-1' }}>
              <label className="form-label">Notes / source</label>
              <input className="form-input" placeholder="Reference the signed schedule or label this as hypothetical" value={form.notes} onChange={e => set('notes', e.target.value)} />
            </div>
            <div className="form-group" style={{ gridColumn: '1/-1', flexDirection: 'row', alignItems: 'center' }}>
              <input type="checkbox" id="is_illustrative" checked={form.is_illustrative} onChange={e => set('is_illustrative', e.target.checked)} style={{ marginRight: 8, accentColor: 'var(--color-accent)' }} />
              <label htmlFor="is_illustrative" className="pricing-checkbox-label">Illustrative assumption — keep checked unless this input is supported by an approved contract source.</label>
            </div>
          </div>
          <div style={{ marginTop: 24, display: 'flex', justifyContent: 'flex-end', gap: 12 }}>
            {(invalidNumbers || invalidCurrency || invalidFeeCurrency || invalidCountry || invalidEffectiveRange) && <span role="alert" className="text-sm" style={{ color: 'var(--color-danger)', alignSelf: 'center' }}>Check currency/country formats, percentages (0–100), non-negative fees, and effective dates.</span>}
            <button className="btn btn-secondary" onClick={onClose}>Cancel</button>
            <button className="btn btn-primary pricing-primary" onClick={handleSubmit} disabled={!form.rule_name.trim() || invalidNumbers || invalidCurrency || invalidFeeCurrency || invalidCountry || invalidEffectiveRange || loading}>
              {loading ? <><span className="spinner" />Saving…</> : rule ? 'Save Changes' : 'Save Rule'}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

function SavingsScenarioModal({ rules, onClose, onSubmit, loading, error, result }: {
  rules: PricingRule[]
  onClose: () => void
  onSubmit: (data: unknown) => void
  loading: boolean
  error: string | null
  result: Record<string, unknown> | null
}) {
  const [form, setForm] = useState({
    name: '',
    current_gateway: 'gateway_a',
    alternative_gateway: 'gateway_b',
    currency: 'INR',
    country: '',
    payment_method: '',
    eligible_payment_value: '',
    current_pricing_rule_id: '',
    alternative_pricing_rule_id: '',
  })

  const set = (k: string, v: string) => setForm(p => ({ ...p, [k]: v }))
  const normalizedCurrency = form.currency.trim().toUpperCase()
  const normalizedCountry = form.country.trim().toUpperCase()
  const normalizedMethod = form.payment_method.trim().toLowerCase()
  const compatible = (gateway: string) => rules.filter(rule =>
    rule.gateway === gateway &&
    (!rule.currency || rule.currency.toUpperCase() === normalizedCurrency) &&
    (!rule.country || (normalizedCountry && rule.country.toUpperCase() === normalizedCountry)) &&
    (!rule.payment_method || (normalizedMethod && rule.payment_method.toLowerCase() === normalizedMethod)) &&
    (rule.fixed_fee == null || !rule.fixed_fee_currency || rule.fixed_fee_currency.toUpperCase() === normalizedCurrency) &&
    rule.fee_rate_pct != null
  )
  const currentRules = compatible(form.current_gateway)
  const alternativeRules = compatible(form.alternative_gateway)
  const currentRule = currentRules.find(rule => rule.id === form.current_pricing_rule_id)
  const alternativeRule = alternativeRules.find(rule => rule.id === form.alternative_pricing_rule_id)
  const valueNumber = Number(form.eligible_payment_value)
  const invalidScenarioCurrency = !/^[A-Z]{3}$/.test(normalizedCurrency)
  const invalidScenarioCountry = Boolean(normalizedCountry && !/^[A-Z]{2}$/.test(normalizedCountry))
  const sameGateway = form.current_gateway === form.alternative_gateway
  const canCalculate = Boolean(form.name.trim() && !invalidScenarioCurrency && !invalidScenarioCountry &&
    !sameGateway && currentRule && alternativeRule && currentRule.id !== alternativeRule.id &&
    form.eligible_payment_value !== '' && Number.isFinite(valueNumber) && valueNumber >= 0 && !loading)
  const difference = result?.estimated_difference == null ? null : Number(result.estimated_difference)
  const differencePct = result?.estimated_difference_pct == null ? null : Number(result.estimated_difference_pct)
  const estimateMessage = difference === null
    ? 'A complete comparison is unavailable. Select compatible rules with a configured fee rate.'
    : difference > 0
      ? 'Estimated savings against the current gateway; this is not a verified contract comparison.'
      : difference < 0
        ? 'The alternative has a higher estimated fee than the current gateway.'
        : 'The configured rules produce no estimated difference.'

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal pricing-modal" onClick={e => e.stopPropagation()}>
        <div className="modal-header">
          <span className="modal-title">Savings Scenario</span>
          <button className="btn btn-ghost btn-sm" onClick={onClose}><X size={16} /></button>
        </div>
        <div className="modal-body">
          {result ? (
            <div>
              <p className="pricing-result-kicker">Estimate only · illustrative or unverified pricing inputs</p>
              <h3 className="pricing-result-title">{String(result.name ?? 'Scenario comparison')}</h3>
              <p className="pricing-result-context">{formatMoney(String(result.eligible_volume ?? '0'), String(result.currency ?? 'INR'))} eligible payment value</p>
              <div className="pricing-comparison">
                <div className="pricing-comparison-side">
                  <span>Current · {gatewayLabel(String(result.current_gateway ?? form.current_gateway))}</span>
                  <strong>{result.current_estimated_fee == null ? 'Not available' : formatMoney(String(result.current_estimated_fee), String(result.currency ?? 'INR'))}</strong>
                </div>
                <div className="pricing-comparison-side">
                  <span>Alternative · {gatewayLabel(String(result.alternative_gateway ?? form.alternative_gateway))}</span>
                  <strong>{result.alternative_estimated_fee == null ? 'Not available' : formatMoney(String(result.alternative_estimated_fee), String(result.currency ?? 'INR'))}</strong>
                </div>
              </div>
              <div className={`pricing-estimate-difference ${difference !== null && difference > 0 ? 'is-saving' : difference !== null && difference < 0 ? 'is-increase' : ''}`}>
                <span>{difference === null ? 'Comparison unavailable' : difference > 0 ? 'Estimated savings' : difference < 0 ? 'Estimated cost increase' : 'Estimated difference'}</span>
                <strong>{difference === null ? '—' : formatMoney(Math.abs(difference).toFixed(2), String(result.currency ?? 'INR'))}</strong>
                {differencePct !== null && <small>{Math.abs(differencePct).toFixed(2)}% of current estimated fee</small>}
                <p>{estimateMessage}</p>
                {difference !== null && difference > 0 && <small>Lower estimated fee: {gatewayLabel(String(result.estimated_lower_cost_gateway))}. This is not a verified routing recommendation.</small>}
              </div>
              {(result.limitations as string[] | undefined)?.length ? (
                <div className="pricing-limitations">
                  <strong>Assumptions and limitations</strong>
                  {(result.limitations as string[]).map((item, index) => <p key={index}>{item}</p>)}
                  <p>{String(result.assumptions_note ?? '')}</p>
                </div>
              ) : null}
              <div className="pricing-modal-actions"><button className="btn btn-secondary" onClick={onClose}>Close</button></div>
            </div>
          ) : (
            <div>
              {error && <div role="alert" className="pricing-error">{error}</div>}
              <div className="pricing-form-grid">
                <div className="form-group" style={{ gridColumn: '1/-1' }}>
                  <label className="form-label">Scenario name</label>
                  <input className="form-input" placeholder="Q4 Gateway Switch Analysis" value={form.name} onChange={e => set('name', e.target.value)} />
                </div>
                <div className="form-group">
                  <label className="form-label">Current Gateway</label>
                  <select className="form-select" value={form.current_gateway} onChange={e => set('current_gateway', e.target.value)}>
                    <option value="gateway_a" disabled={form.alternative_gateway === 'gateway_a'}>Gateway A</option>
                    <option value="gateway_b" disabled={form.alternative_gateway === 'gateway_b'}>Gateway B</option>
                  </select>
                </div>
                <div className="form-group">
                  <label className="form-label">Alternative Gateway</label>
                  <select className="form-select" value={form.alternative_gateway} onChange={e => set('alternative_gateway', e.target.value)}>
                    <option value="gateway_b" disabled={form.current_gateway === 'gateway_b'}>Gateway B</option>
                    <option value="gateway_a" disabled={form.current_gateway === 'gateway_a'}>Gateway A</option>
                  </select>
                </div>
                <div className="form-group">
                  <label className="form-label">Currency code</label>
                  <input className="form-input" maxLength={3} placeholder="INR" value={form.currency} onChange={e => set('currency', e.target.value.toUpperCase())} />
                </div>
                <div className="form-group">
                  <label className="form-label">Country code</label>
                  <input className="form-input" placeholder="IN, US…" value={form.country} onChange={e => set('country', e.target.value.toUpperCase())} />
                </div>
                <div className="form-group">
                  <label className="form-label">Payment method</label>
                  <input className="form-input" placeholder="card, upi, netbanking" value={form.payment_method} onChange={e => set('payment_method', e.target.value.toLowerCase())} />
                </div>
                <div className="form-group">
                  <label className="form-label">Eligible payment value</label>
                  <input className="form-input" type="number" min="0" step="0.01" placeholder="10000.00" value={form.eligible_payment_value} onChange={e => set('eligible_payment_value', e.target.value)} />
                  <small className="pricing-help">Fee rate applies to this total value. Fixed fee is added once per scenario.</small>
                </div>
                <div className="form-group">
                  <label className="form-label">Current Pricing Rule</label>
                  <select className="form-select" value={currentRule?.id ?? ''} onChange={e => set('current_pricing_rule_id', e.target.value)}>
                    <option value="">None</option>
                    {currentRules.map(r => <option key={r.id} value={r.id}>{r.rule_name} ({gatewayLabel(r.gateway)}){r.is_illustrative ? ' · Illustrative' : ''}</option>)}
                  </select>
                  {currentRules.length === 0 && <small className="pricing-help">No rule matches these inputs. Current cost will be unavailable.</small>}
                </div>
                <div className="form-group">
                  <label className="form-label">Alternative Pricing Rule</label>
                  <select className="form-select" value={alternativeRule?.id ?? ''} onChange={e => set('alternative_pricing_rule_id', e.target.value)}>
                    <option value="">None</option>
                    {alternativeRules.map(r => <option key={r.id} value={r.id}>{r.rule_name} ({gatewayLabel(r.gateway)}){r.is_illustrative ? ' · Illustrative' : ''}</option>)}
                  </select>
                  {alternativeRules.length === 0 && <small className="pricing-help">No rule matches these inputs. Alternative cost will be unavailable.</small>}
                </div>
              </div>
              {sameGateway && <div role="alert" className="pricing-error">Choose a different current and alternative gateway.</div>}
              {(!currentRule || !alternativeRule) && <div role="status" className="pricing-help pricing-selection-help">Choose a configured fee rule for each gateway. Rules with missing fee rates or incompatible currency, country, or payment method cannot be selected.</div>}
              <p className="pricing-form-note">Rules with a different gateway, currency, country, or payment method are excluded. Unscoped rules may still be selected and will be flagged as generic assumptions.</p>
              {(invalidScenarioCurrency || invalidScenarioCountry) && <div role="alert" className="pricing-error">Use a three-letter currency code and, when entered, a two-letter country code.</div>}
              <div className="pricing-modal-actions">
                <button className="btn btn-secondary" onClick={onClose}>Cancel</button>
                <button className="btn btn-primary pricing-primary" onClick={() => onSubmit({
                  name: form.name.trim(), current_gateway: form.current_gateway,
                  alternative_gateway: form.alternative_gateway, currency: normalizedCurrency,
                  country: normalizedCountry || undefined, payment_method: normalizedMethod || undefined,
                  eligible_volume: valueNumber, current_pricing_rule_id: currentRule?.id || undefined,
                  alternative_pricing_rule_id: alternativeRule?.id || undefined,
                })} disabled={!canCalculate}>
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
