import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { AlertTriangle, Database, RefreshCw, ScanSearch, ShieldCheck, Upload, FileText, Info } from 'lucide-react'
import {
  fetchVendors, fetchVendorExceptions, fetchVendorCleanup, fetchVendorRules,
  runVendorChecks, seedVendorData, scanVendorMaster, createVendorRule, approveVendorRule,
  fetchVendorDocuments, fetchVendorDocumentBatches, importVendorDocuments,
} from '../api/client'

type Vendor = {
  id: string; vendor_code: string; legal_name: string; pan: string | null; gstin: string | null
  vendor_type: string; msme_type: string; is_synthetic: boolean
  scorecard: null | { status: string; risk_score: number; total_amount_at_stake: string | null; currency: string; summary_reasons: string[]; evidence_coverage: Record<string, number | boolean> }
}
type VendorException = { id: string; vendor_id: string; category: string; severity: string; title: string; description: string; amount_at_stake: string | null; currency: string; missing_information: string[]; suggested_action: string; is_synthetic_warning: boolean; source_filename?: string | null; invoice_number?: string | null }
type CleanupItem = { id: string; vendor_id: string; issue_type: string; severity: string; field_name: string; description: string; recommended_fix: string }
type TaxRule = { id: string; rule_code: string; tax_category: string; section_1961: string | null; section_2025: string | null; description: string; rate_pct: string; threshold_amount: string; effective_from: string; effective_to: string | null; verification_status: string; version: string; source_reference: string | null; is_sample_rule: boolean }

export default function VendorCompliancePage() {
  const qc = useQueryClient()
  const [showRuleForm, setShowRuleForm] = useState(false)
  const [source, setSource] = useState<'synthetic' | 'hr'>('hr')
  const [selectedFiles, setSelectedFiles] = useState<File[]>([])
  const vendors = useQuery({ queryKey: ['vendor-compliance', 'vendors', source], queryFn: () => fetchVendors(source) })
  const exceptions = useQuery({ queryKey: ['vendor-compliance', 'exceptions', source], queryFn: () => fetchVendorExceptions(source) })
  const cleanup = useQuery({ queryKey: ['vendor-compliance', 'cleanup', source], queryFn: () => fetchVendorCleanup(source) })
  const rules = useQuery({ queryKey: ['vendor-compliance', 'rules'], queryFn: fetchVendorRules })
  const documents = useQuery({ queryKey: ['vendor-compliance', 'documents'], queryFn: fetchVendorDocuments })
  const batches = useQuery({ queryKey: ['vendor-compliance', 'batches'], queryFn: fetchVendorDocumentBatches })
  const refresh = () => qc.invalidateQueries({ queryKey: ['vendor-compliance'] })
  const seed = useMutation({ mutationFn: seedVendorData, onSuccess: refresh })
  const run = useMutation({ mutationFn: () => runVendorChecks(source), onSuccess: refresh })
  const scan = useMutation({ mutationFn: () => scanVendorMaster(source), onSuccess: refresh })
  const importDocs = useMutation({ mutationFn: importVendorDocuments, onSuccess: refresh })
  const createRule = useMutation({ mutationFn: createVendorRule, onSuccess: () => { refresh(); setShowRuleForm(false) } })
  const approveRule = useMutation({ mutationFn: ({ id, who }: { id: string; who: string }) => approveVendorRule(id, who), onSuccess: refresh })
  const rows: Vendor[] = vendors.data ?? []
  const issues: VendorException[] = exceptions.data ?? []
  const cleanupRows: CleanupItem[] = cleanup.data ?? []
  const ruleRows: TaxRule[] = rules.data ?? []
  const assessed = rows.filter(v => v.scorecard)
  const needingReview = rows.filter(v => !v.scorecard || v.scorecard.status !== 'compliant').length
  const missingEvidence = issues.filter(e => e.missing_information.length > 0).length
  const validationFindings = issues.filter(e => e.missing_information.length === 0).length
  const latestBatch = batches.data?.[0] as { id: string; dataset_name: string; source_kind: string; total_files: number; parsed_files: number; failed_files: number; duplicate_files: number; review_required_files: number; created_at: string } | undefined
  const documentCount = documents.data?.length ?? 0
  const error = [vendors.error, exceptions.error, cleanup.error, rules.error, documents.error, batches.error, seed.error, run.error, scan.error, createRule.error, approveRule.error, importDocs.error].find(Boolean) as Error | undefined

  return <div className="page-wrapper">
    <div className="page-header">
      <h1 className="page-title">HR Invoice Compliance Review</h1>
      <p className="page-subtitle">Review invoice evidence, identify missing compliance records, and prepare vendor scorecards and cleanup reports.</p>
    </div>
    <div className="card mb-8"><div className="card-body" style={{ display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'center' }}>
      <label className="text-sm">Dataset <select className="form-select" value={source} onChange={e => setSource(e.target.value as 'synthetic' | 'hr')} style={{ display: 'inline-block', width: 240, marginLeft: 8 }}><option value="hr">HR Sample_Invoices PDFs</option><option value="synthetic">Synthetic demo / test data</option></select></label>
      <button className="btn btn-primary" onClick={() => run.mutate()} disabled={run.isPending || rows.length === 0}><RefreshCw size={15} /> {run.isPending ? 'Checking…' : 'Run compliance checks'}</button>
      <button className="btn btn-secondary" onClick={() => scan.mutate()} disabled={scan.isPending || rows.length === 0}><ScanSearch size={15} /> {scan.isPending ? 'Scanning…' : 'Scan vendor master'}</button>
      <details style={{ position: 'relative' }}><summary className="btn btn-secondary" style={{ display: 'inline-flex', alignItems: 'center', gap: 8, cursor: 'pointer', listStyle: 'none' }}><Database size={15} /> Developer Demo / Test Data</summary><div className="card" style={{ position: 'absolute', zIndex: 2, right: 0, top: '100%', minWidth: 260, padding: 12, boxShadow: 'var(--shadow-md)' }}><p className="text-sm text-muted" style={{ marginBottom: 10 }}>Synthetic records are separate from the HR invoice dataset.</p><button className="btn btn-secondary" onClick={() => seed.mutate()} disabled={seed.isPending}><Database size={15} /> {seed.isPending ? 'Loading…' : 'Load synthetic demo data'}</button></div></details>
    </div></div>
    <section className="card mb-8" aria-label="Active dataset">
      <div className="card-header"><span className="card-title"><FileText size={16} /> Active dataset: {source === 'hr' ? 'HR Sample_Invoices' : 'Synthetic Demo / Test Data'}</span><span className={`badge ${source === 'hr' ? (documentCount ? 'badge-success' : 'badge-warning') : 'badge-info'}`}>{source === 'hr' ? (documentCount ? 'HR records loaded' : 'No HR documents imported') : 'Synthetic only'}</span></div>
      <div className="card-body" style={{ display: 'flex', gap: 24, flexWrap: 'wrap' }}>
        <div style={{ flex: '1 1 220px', minWidth: 0 }}><div className="text-muted text-sm">Dataset source</div><strong>{source === 'hr' ? 'Sample_Invoices · HR-provided PDFs' : 'Vendor compliance demo seeder'}</strong></div>
        <div style={{ flex: '1 1 180px', minWidth: 0 }}><div className="text-muted text-sm">Documents</div><strong>{source === 'hr' ? `${documentCount} PDF document${documentCount === 1 ? '' : 's'}` : 'No HR PDFs (synthetic records)'}</strong></div>
        <div style={{ flex: '2 1 360px', minWidth: 0 }}><div className="text-muted text-sm">Latest import status</div><strong title={latestBatch?.created_at ?? ''}>{source === 'hr' ? (latestBatch ? `${latestBatch.parsed_files}/${latestBatch.total_files} parsed · ${latestBatch.failed_files} failed · ${latestBatch.duplicate_files} duplicate · ${latestBatch.review_required_files} need review` : 'No import batch yet') : 'Not applicable'}</strong></div>
      </div>
    </section>
    {source === 'hr' && <section className="card mb-8"><div className="card-body" style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'center' }}>
      <strong>Assignment deliverables</strong>
      <a className="btn btn-primary" href="/api/v1/vendor-compliance/reports/scorecards.csv?source=hr">Vendor scorecard CSV</a>
      <a className="btn btn-primary" href="/api/v1/vendor-compliance/reports/exceptions.csv?source=hr">Compliance exception report CSV</a>
      <a className="btn btn-primary" href="/api/v1/vendor-compliance/reports/cleanup.csv?source=hr">Vendor master cleanup CSV</a>
      <a className="btn btn-secondary" href="/api/v1/vendor-compliance/documents/export.csv">Import Review CSV</a>
    </div></section>}
    <section className="card mb-8"><div className="card-header"><span className="card-title"><Info size={16} /> How to read these results</span></div><div className="card-body text-sm text-muted">
      Invoice PDFs provide invoice-level evidence only. GSTR-2B, payment/bank records, TDS challans/returns, and authoritative GST, PAN, or MSME evidence are not available unless separately supplied. “Needs review” and “Missing evidence” are not confirmed tax violations; rule findings still require human review and approved tax rules.
    </div></section>
    {source === 'hr' && <>
      <section className="card mb-8"><div className="card-header"><span className="card-title"><Upload size={16} /> Import HR invoice PDFs</span></div><div className="card-body" style={{ display: 'grid', gap: 12 }}>
        <p className="text-sm text-muted">Choose one ZIP or multiple PDFs from <strong>Sample_Invoices</strong>. Original filenames and SHA-256 hashes are retained. Text extraction only; scanned PDFs are marked for review because OCR is not configured.</p>
        <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'center' }}><input type="file" accept=".pdf,.zip,application/pdf,application/zip" multiple onChange={e => setSelectedFiles(Array.from(e.target.files ?? []))} /><button className="btn btn-primary" disabled={!selectedFiles.length || importDocs.isPending} onClick={() => importDocs.mutate(selectedFiles)}><Upload size={15} /> {importDocs.isPending ? 'Importing…' : `Import ${selectedFiles.length || ''} file(s)`}</button><a className="btn btn-secondary" href="/api/v1/vendor-compliance/documents/export.csv">Export import review CSV</a></div>
        {importDocs.data && <p className="text-sm">Batch: {importDocs.data.batch_id} · PDFs: {importDocs.data.total_files} · parsed: {importDocs.data.parsed_files} · failed: {importDocs.data.failed_files} · duplicates: {importDocs.data.duplicate_files} · review required: {importDocs.data.review_required_files}</p>}
        <div className="text-sm text-muted">{(batches.data ?? []).slice(0, 3).map((b: { id: string; created_at: string; total_files: number; parsed_files: number; failed_files: number; duplicate_files: number; review_required_files: number }) => <div key={b.id}>Batch {b.id.slice(0, 8)} · {b.total_files} files · parsed {b.parsed_files} · failed {b.failed_files} · duplicates {b.duplicate_files} · review {b.review_required_files} · {b.created_at}</div>)}</div>
      </div></section>
      <section className="card mb-8"><div className="card-header"><span className="card-title"><FileText size={16} /> Imported source documents ({documents.data?.length ?? 0})</span></div><div className="table-container"><table className="data-table"><thead><tr><th>Source file</th><th>Type</th><th>Extraction</th><th>Mapping</th><th>Vendor</th><th>Invoice / date</th><th>Currency / total</th><th>Review note</th></tr></thead><tbody>
        {(documents.data ?? []).length === 0 ? <tr><td colSpan={8}>No HR documents imported yet.</td></tr> : (documents.data ?? []).map((d: { id: string; filename: string; document_type: string; extraction_status: string; mapping_status: string; fields: Record<string, { value: string | null }>; review_reasons: string[] }) => <tr key={d.id}><td title={d.filename}>{d.filename}</td><td>{formatStatus(d.document_type)}</td><td><span className={`badge ${d.extraction_status === 'parsed' ? 'badge-success' : 'badge-warning'}`}>{formatStatus(d.extraction_status)}</span></td><td><span className={`badge ${d.mapping_status === 'mapped' ? 'badge-success' : 'badge-warning'}`}>{formatStatus(d.mapping_status)}</span></td><td>{d.fields.vendor_legal_name?.value ?? 'Unresolved'}</td><td>{d.fields.invoice_number?.value ?? '—'}<div className="text-muted text-sm">{d.fields.invoice_date?.value ?? 'Date missing'}</div></td><td>{d.fields.currency?.value ?? 'Unknown'} {d.fields.total_invoice_value?.value ?? 'amount missing'}</td><td>{d.review_reasons.join('; ') || 'No review note'}</td></tr>)}
      </tbody></table></div></section>
    </>}
    {error && <div className="card mb-8"><div className="card-body" style={{ color: 'var(--color-danger)' }}>API error: {error.message}. Confirm the backend is running and migrations are applied.</div></div>}
    <div className="stats-grid mb-8">
      <Kpi icon={<ShieldCheck size={17} />} label="Vendors needing review" value={needingReview} help="Vendors not yet assessed or whose scorecard is not marked compliant. This is a review queue, not a count of legal violations." />
      <Kpi icon={<ScanSearch size={17} />} label="Findings with missing evidence" value={missingEvidence} help="Recorded findings that list required information as unavailable. Multiple findings may refer to one vendor or invoice." />
      <Kpi icon={<AlertTriangle size={17} />} label="Validation findings" value={validationFindings} help="Recorded checks with no missing-information flag. These are review findings, not an official or final tax-compliance determination." />
      <Kpi icon={<RefreshCw size={17} />} label="Vendors assessed" value={assessed.length} help="Vendors in this selected dataset that currently have a scorecard." />
    </div>
    <section className="card mb-8"><div className="card-header"><span className="card-title">Vendor scorecards · {source === 'hr' ? 'HR invoices' : 'synthetic demo'}</span></div>
      <div className="table-container"><table className="data-table"><thead><tr><th>Vendor</th><th>GSTIN / PAN</th><th>MSME</th><th>Status</th><th>Risk</th><th>Exposure</th><th>Evidence</th></tr></thead>
      <tbody>{vendors.isLoading ? <tr><td colSpan={7}>Loading {source === 'hr' ? 'HR' : 'synthetic'} vendor data…</td></tr> : rows.length === 0 ? <tr><td colSpan={7}>{source === 'hr' ? 'No HR-linked vendors yet. Import the Sample_Invoices PDFs above.' : 'No synthetic records loaded. Open Developer Demo / Test Data to load examples.'}</td></tr> : rows.map(v => <tr key={v.id}>
        <td><strong>{v.legal_name}</strong><div className="text-muted text-sm">{v.vendor_code}{v.is_synthetic ? ' · synthetic' : ''}</div></td>
        <td className="text-sm">{v.gstin ?? 'GSTIN missing'}<div className="text-muted">{v.pan ?? 'PAN missing'}</div></td>
        <td>{v.msme_type}</td>
        <td><span className={`badge ${statusClass(v.scorecard?.status)}`}>{v.scorecard?.status === 'needs_attention' ? 'Needs review' : v.scorecard?.status?.replace('_', ' ') ?? 'Not assessed'}</span></td>
        <td>{v.scorecard?.risk_score ?? '—'}</td>
        <td>{v.scorecard?.total_amount_at_stake !== null && v.scorecard?.total_amount_at_stake !== undefined ? `${v.scorecard.currency} ${Number(v.scorecard.total_amount_at_stake).toLocaleString()}` : 'Not quantifiable from available evidence'}</td>
        <td>{v.scorecard ? `${v.scorecard.evidence_coverage.source_documents ?? v.scorecard.evidence_coverage.invoices_checked ?? 0} documents` : '—'}</td>
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
      <section className="card"><div className="card-header"><span className="card-title">Compliance findings · {source === 'hr' ? 'HR invoices' : 'synthetic demo'}</span></div><div className="card-body" style={{ display: 'grid', gap: 12 }}>
        {issues.length === 0 ? <p className="text-muted">No checks have produced exceptions yet.</p> : issues.slice(0, 30).map(e => <article key={e.id} style={{ padding: 12, border: '1px solid var(--color-border)', borderRadius: 8 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap' }}><strong>{e.title}</strong><div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}><span className={`badge ${e.missing_information.length ? 'badge-warning' : 'badge-info'}`}>{e.missing_information.length ? 'Missing evidence' : 'Validation finding'}</span><span className={`badge ${e.severity === 'high' ? 'badge-danger' : 'badge-warning'}`}>{e.severity} severity</span></div></div>
          <p className="text-sm text-muted" style={{ marginTop: 6 }}>{e.description}</p>
          {(e.source_filename || e.invoice_number) && <p className="text-sm">Source: {e.source_filename ?? '—'}{e.invoice_number ? ` · Invoice ${e.invoice_number}` : ''}</p>}
          {e.amount_at_stake && <p className="text-sm">Exposure: {e.currency} {Number(e.amount_at_stake).toLocaleString()}</p>}
          <p className="text-sm">Suggested action: {e.suggested_action}</p>
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

function Kpi({ icon, label, value, help }: { icon: React.ReactNode; label: string; value: number; help: string }) {
  return <div className="stat-card" title={help} aria-label={`${label}: ${value}. ${help}`}><div className="stat-icon">{icon}</div><div className="stat-label" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>{label}<Info size={12} aria-hidden="true" /></div><div className="stat-value">{value}</div></div>
}
function statusClass(status?: string) {
  if (status === 'compliant') return 'badge-success'
  if (status === 'high_risk') return 'badge-danger'
  if (status === 'needs_attention') return 'badge-warning'
  return 'badge-muted'
}
function formatStatus(status: string) {
  return status.replace(/_/g, ' ').replace(/\b\w/g, character => character.toUpperCase())
}
