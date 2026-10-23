import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { AlertTriangle, Database, RefreshCw, ScanSearch, ShieldCheck } from 'lucide-react'
import {
  fetchVendors, fetchVendorExceptions, fetchVendorCleanup, fetchVendorRules,
  runVendorChecks, seedVendorData, scanVendorMaster, createVendorRule, approveVendorRule,
} from '../api/client'

type Vendor = {
  id: string; vendor_code: string; legal_name: string; pan: string | null; gstin: string | null
  vendor_type: string; msme_type: string; is_synthetic: boolean
  scorecard: null | { status: string; risk_score: number; total_amount_at_stake: string; currency: string; summary_reasons: string[]; evidence_coverage: Record<string, number> }
}
type VendorException = { id: string; vendor_id: string; category: string; severity: string; title: string; description: string; amount_at_stake: string | null; currency: string; missing_information: string[]; is_synthetic_warning: boolean }
type CleanupItem = { id: string; vendor_id: string; issue_type: string; severity: string; field_name: string; description: string; recommended_fix: string }
type TaxRule = { id: string; rule_code: string; tax_category: string; section_1961: string | null; section_2025: string | null; description: string; rate_pct: string; threshold_amount: string; effective_from: string; effective_to: string | null; verification_status: string; version: string; source_reference: string | null; is_sample_rule: boolean }

export default function VendorCompliancePage() {
  const qc = useQueryClient()
  const [showRuleForm, setShowRuleForm] = useState(false)
  const vendors = useQuery({ queryKey: ['vendor-compliance', 'vendors'], queryFn: fetchVendors })
  const exceptions = useQuery({ queryKey: ['vendor-compliance', 'exceptions'], queryFn: fetchVendorExceptions })
  const cleanup = useQuery({ queryKey: ['vendor-compliance', 'cleanup'], queryFn: fetchVendorCleanup })
  const rules = useQuery({ queryKey: ['vendor-compliance', 'rules'], queryFn: fetchVendorRules })
  const refresh = () => qc.invalidateQueries({ queryKey: ['vendor-compliance'] })
  const seed = useMutation({ mutationFn: seedVendorData, onSuccess: refresh })
  const run = useMutation({ mutationFn: runVendorChecks, onSuccess: refresh })
  const scan = useMutation({ mutationFn: scanVendorMaster, onSuccess: refresh })
  const createRule = useMutation({ mutationFn: createVendorRule, onSuccess: () => { refresh(); setShowRuleForm(false) } })
  const approveRule = useMutation({ mutationFn: ({ id, who }: { id: string; who: string }) => approveVendorRule(id, who), onSuccess: refresh })
  const rows: Vendor[] = vendors.data ?? []
  const issues: VendorException[] = exceptions.data ?? []
  const cleanupRows: CleanupItem[] = cleanup.data ?? []
  const ruleRows: TaxRule[] = rules.data ?? []
  const assessed = rows.filter(v => v.scorecard)
  const inReview = issues.filter(e => e.missing_information.length > 0).length
  const error = [vendors.error, exceptions.error, cleanup.error, rules.error, seed.error, run.error, scan.error, createRule.error, approveRule.error].find(Boolean) as Error | undefined

  return <div className="page-wrapper">
    <div className="page-header">
      <h1 className="page-title">Vendor Compliance</h1>
      <p className="page-subtitle">GST, TDS, MSME payment deadlines and vendor master evidence</p>
    </div>
    <div className="card mb-8"><div className="card-body" style={{ display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'center' }}>
      <button className="btn btn-secondary" onClick={() => seed.mutate()} disabled={seed.isPending}><Database size={15} /> {seed.isPending ? 'Seeding…' : 'Load synthetic demo data'}</button>
      <button className="btn btn-primary" onClick={() => run.mutate()} disabled={run.isPending || rows.length === 0}><RefreshCw size={15} /> {run.isPending ? 'Checking…' : 'Run compliance checks'}</button>
      <button className="btn btn-secondary" onClick={() => scan.mutate()} disabled={scan.isPending || rows.length === 0}><ScanSearch size={15} /> {scan.isPending ? 'Scanning…' : 'Scan vendor master'}</button>
      <span className="text-muted text-sm">Synthetic records are labeled. Tax rules need approval before rate-based checks apply.</span>
    </div></div>
    {error && <div className="card mb-8"><div className="card-body" style={{ color: 'var(--color-danger)' }}>API error: {error.message}. Confirm the backend is running and migrations are applied.</div></div>}
    <div className="stats-grid mb-8">
      <Kpi icon={<ShieldCheck size={17} />} label="Vendors" value={rows.length} />
      <Kpi icon={<RefreshCw size={17} />} label="Assessed" value={assessed.length} />
      <Kpi icon={<AlertTriangle size={17} />} label="Exceptions" value={issues.length} />
      <Kpi icon={<ScanSearch size={17} />} label="Missing evidence" value={inReview} />
    </div>
    <section className="card mb-8"><div className="card-header"><span className="card-title">Vendor scorecards</span></div>
      <div className="table-container"><table className="data-table"><thead><tr><th>Vendor</th><th>GSTIN / PAN</th><th>MSME</th><th>Status</th><th>Risk</th><th>Exposure</th><th>Evidence</th></tr></thead>
      <tbody>{vendors.isLoading ? <tr><td colSpan={7}>Loading vendor data…</td></tr> : rows.length === 0 ? <tr><td colSpan={7}>No vendors loaded. Use “Load synthetic demo data” or connect vendor records.</td></tr> : rows.map(v => <tr key={v.id}>
        <td><strong>{v.legal_name}</strong><div className="text-muted text-sm">{v.vendor_code}{v.is_synthetic ? ' · synthetic' : ''}</div></td>
        <td className="text-sm">{v.gstin ?? 'GSTIN missing'}<div className="text-muted">{v.pan ?? 'PAN missing'}</div></td>
        <td>{v.msme_type}</td>
        <td><span className={`badge ${statusClass(v.scorecard?.status)}`}>{v.scorecard?.status?.replace('_', ' ') ?? 'not assessed'}</span></td>
        <td>{v.scorecard?.risk_score ?? '—'}</td>
        <td>{v.scorecard ? `${v.scorecard.currency} ${Number(v.scorecard.total_amount_at_stake).toLocaleString()}` : '—'}</td>
        <td>{v.scorecard ? `${v.scorecard.evidence_coverage.invoices_checked ?? 0} invoices` : '—'}</td>
      </tr>)}</tbody></table></div>
    </section>
    <section className="card mb-8"><div className="card-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}><span className="card-title">Versioned tax rules</span><button className="btn btn-secondary btn-sm" onClick={() => setShowRuleForm(v => !v)}>{showRuleForm ? 'Close' : 'Add rule'}</button></div>
      <div className="card-body">
        <p className="text-sm text-muted" style={{ marginBottom: 12 }}>Rules stay pending review until explicitly approved. Only approved rules with matching effective dates are used for TDS rate checks. Enter values from a reviewed source; the application does not supply legal rates.</p>
        {showRuleForm && <form onSubmit={e => { e.preventDefault(); const d = new FormData(e.currentTarget); createRule.mutate({
          rule_code: String(d.get('rule_code')), tax_category: String(d.get('tax_category')), description: String(d.get('description')),
          rate_pct: String(d.get('rate_pct')), threshold_amount: String(d.get('threshold_amount') || '0'), tax_base: String(d.get('tax_base')),
          effective_from: String(d.get('effective_from')), effective_to: String(d.get('effective_to') || '') || null,
          section_1961: String(d.get('section_1961') || '') || null, section_2025: String(d.get('section_2025') || '') || null,
          source_reference: String(d.get('source_reference')), version: String(d.get('version')),
        }) }} style={{ display: 'grid', gridTemplateColumns: 'repeat(3, minmax(0, 1fr))', gap: 10, marginBottom: 18 }}>
          <input className="form-input" name="rule_code" placeholder="Rule code" required />
          <select className="form-select" name="tax_category"><option value="tds">TDS</option><option value="gst">GST</option></select>
          <input className="form-input" name="version" placeholder="Version" defaultValue="1.0" required />
          <input className="form-input" name="description" placeholder="Description" required />
          <input className="form-input" name="section_1961" placeholder="Section 1961 (if verified)" />
          <input className="form-input" name="section_2025" placeholder="Section 2025 (if verified)" />
          <input className="form-input" name="rate_pct" type="number" step="0.0001" placeholder="Rate %" required />
          <input className="form-input" name="threshold_amount" type="number" step="0.01" placeholder="Threshold" defaultValue="0" />
          <select className="form-select" name="tax_base"><option value="EXCLUDE_GST">Exclude GST</option><option value="GROSS">Gross</option><option value="NET">Net</option></select>
          <input className="form-input" name="effective_from" type="date" required />
          <input className="form-input" name="effective_to" type="date" />
          <input className="form-input" name="source_reference" placeholder="Source reference" required />
          <button className="btn btn-primary" type="submit" disabled={createRule.isPending}>Save as pending review</button>
        </form>}
        <div className="table-container"><table className="data-table"><thead><tr><th>Rule</th><th>Category / Section</th><th>Rate</th><th>Effective</th><th>Version</th><th>Approval</th></tr></thead><tbody>
          {ruleRows.length === 0 ? <tr><td colSpan={6}>No configured tax rules.</td></tr> : ruleRows.map(rule => <tr key={rule.id}><td><strong>{rule.rule_code}{rule.is_sample_rule ? ' · sample' : ''}</strong><div className="text-muted text-sm">{rule.description}</div><div className="text-muted text-sm">{rule.source_reference ?? 'Source reference missing'}</div></td>
            <td>{rule.tax_category.toUpperCase()} · {rule.section_1961 ?? rule.section_2025 ?? 'section not mapped'}</td><td>{rule.rate_pct}%</td><td>{rule.effective_from}{rule.effective_to ? ` → ${rule.effective_to}` : ' onward'}</td><td>{rule.version}</td>
            <td>{rule.verification_status === 'approved' ? <span className="badge badge-success">Approved</span> : rule.is_sample_rule ? <span className="badge badge-warning">Sample only</span> : <button className="btn btn-secondary btn-sm" onClick={() => { const who = window.prompt('Approver name'); if (who?.trim()) approveRule.mutate({ id: rule.id, who: who.trim() }) }}>Approve</button>}</td></tr>)}
        </tbody></table></div>
      </div>
    </section>
    <div className="grid-2">
      <section className="card"><div className="card-header"><span className="card-title">Compliance exceptions</span></div><div className="card-body" style={{ display: 'grid', gap: 12 }}>
        {issues.length === 0 ? <p className="text-muted">No checks have produced exceptions yet.</p> : issues.slice(0, 30).map(e => <article key={e.id} style={{ padding: 12, border: '1px solid var(--color-border)', borderRadius: 8 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12 }}><strong>{e.title}</strong><span className={`badge ${e.severity === 'high' ? 'badge-danger' : 'badge-warning'}`}>{e.severity}</span></div>
          <p className="text-sm text-muted" style={{ marginTop: 6 }}>{e.description}</p>
          {e.amount_at_stake && <p className="text-sm">Exposure: {e.currency} {Number(e.amount_at_stake).toLocaleString()}</p>}
          {e.missing_information.length > 0 && <p className="text-sm" style={{ color: 'var(--color-warning)', marginTop: 6 }}>Missing evidence: {e.missing_information.join('; ')}</p>}
          {e.is_synthetic_warning && <span className="badge badge-info" style={{ marginTop: 6 }}>Synthetic example</span>}
        </article>)}
      </div></section>
      <section className="card"><div className="card-header"><span className="card-title">Vendor master cleanup</span></div><div className="card-body" style={{ display: 'grid', gap: 12 }}>
        {cleanupRows.length === 0 ? <p className="text-muted">Run a scan to find format and evidence issues. Vendor records are not changed automatically.</p> : cleanupRows.map(item => <article key={item.id} style={{ padding: 12, border: '1px solid var(--color-border)', borderRadius: 8 }}>
          <strong>{item.issue_type.replace(/_/g, ' ')}</strong><p className="text-sm text-muted">{item.description}</p><p className="text-sm">{item.recommended_fix}</p>
        </article>)}
      </div></section>
    </div>
  </div>
}

function Kpi({ icon, label, value }: { icon: React.ReactNode; label: string; value: number }) {
  return <div className="stat-card"><div className="stat-icon">{icon}</div><div className="stat-label">{label}</div><div className="stat-value">{value}</div></div>
}
function statusClass(status?: string) {
  if (status === 'compliant') return 'badge-success'
  if (status === 'high_risk') return 'badge-danger'
  if (status === 'needs_attention') return 'badge-warning'
  return 'badge-muted'
}
