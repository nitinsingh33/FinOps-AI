import { Fragment, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Database, Info, RefreshCw, ScanSearch, Upload } from 'lucide-react'
import {
  approveVendorRule, createVendorRule, fetchVendorCleanup, fetchVendorDocumentBatches,
  fetchVendorDocuments, fetchVendorExceptions, fetchVendorRules, fetchVendors,
  importVendorDocuments, runVendorChecks, scanVendorMaster, seedVendorData,
} from '../api/client'

type View = 'overview' | 'invoices' | 'exceptions' | 'cleanup' | 'rules'
type Vendor = {
  id: string; vendor_code: string; legal_name: string; pan: string | null; gstin: string | null
  vendor_type: string; msme_type: string; is_synthetic: boolean
  scorecard: null | { status: string; risk_score: number; total_amount_at_stake: string | null; currency: string; summary_reasons: string[]; evidence_coverage: Record<string, number | boolean> }
}
type VendorException = {
  id: string; vendor_id: string; invoice_id?: string | null; check_code: string; category: string
  severity: string; title: string; description: string; amount_at_stake: string | null; currency: string
  missing_information: string[]; suggested_action: string; is_synthetic_warning: boolean
  source_filename?: string | null; invoice_number?: string | null
}
type CleanupItem = { id: string; vendor_id: string; issue_type: string; severity: string; field_name: string; description: string; recommended_fix: string }
type TaxRule = { id: string; rule_code: string; tax_category: string; section_1961: string | null; section_2025: string | null; description: string; rate_pct: string; threshold_amount: string; effective_from: string; effective_to: string | null; verification_status: string; version: string; source_reference: string | null; is_sample_rule: boolean }
type SourceDocument = { id: string; filename: string; document_type: string; extraction_status: string; mapping_status: string; fields: Record<string, { value: string | null; status?: string; evidence?: string | null }>; review_reasons: string[] }
type ImportBatch = { id: string; dataset_name: string; source_kind: string; total_files: number; parsed_files: number; failed_files: number; duplicate_files: number; review_required_files: number; created_at: string }

const tabs: { id: View; label: string }[] = [
  { id: 'overview', label: 'Overview' }, { id: 'invoices', label: 'Invoices' },
  { id: 'exceptions', label: 'Exceptions' }, { id: 'cleanup', label: 'Vendor Master' },
  { id: 'rules', label: 'Tax Rules' },
]

export default function VendorCompliancePage() {
  const qc = useQueryClient()
  const [source, setSource] = useState<'synthetic' | 'hr'>('hr')
  const [view, setView] = useState<View>('overview')
  const [selectedFiles, setSelectedFiles] = useState<File[]>([])
  const [showImportForm, setShowImportForm] = useState(false)
  const [showRuleForm, setShowRuleForm] = useState(false)
  const [expandedException, setExpandedException] = useState<string | null>(null)
  const [expandedDocument, setExpandedDocument] = useState<string | null>(null)
  const [exceptionSearch, setExceptionSearch] = useState('')
  const [exceptionStatus, setExceptionStatus] = useState('all')
  const [exceptionCategory, setExceptionCategory] = useState('all')
  const [exceptionSeverity, setExceptionSeverity] = useState('all')
  const [invoiceSearch, setInvoiceSearch] = useState('')
  const [invoiceMappingStatus, setInvoiceMappingStatus] = useState('all')
  const [cleanupVendor, setCleanupVendor] = useState('all')
  const [cleanupField, setCleanupField] = useState('all')

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
  const importDocs = useMutation({ mutationFn: importVendorDocuments, onSuccess: () => { refresh(); setShowImportForm(false) } })
  const createRule = useMutation({ mutationFn: createVendorRule, onSuccess: () => { refresh(); setShowRuleForm(false) } })
  const approveRule = useMutation({ mutationFn: ({ id, who }: { id: string; who: string }) => approveVendorRule(id, who), onSuccess: refresh })

  const rows: Vendor[] = useMemo(() => vendors.data ?? [], [vendors.data])
  const issues: VendorException[] = exceptions.data ?? []
  const cleanupRows: CleanupItem[] = cleanup.data ?? []
  const ruleRows: TaxRule[] = rules.data ?? []
  const docs: SourceDocument[] = documents.data ?? []
  const importBatches: ImportBatch[] = batches.data ?? []
  const latestBatch = importBatches[0]
  const documentCount = source === 'hr' ? docs.length : 0
  const visibleDocs = docs.filter(d => {
    const search = invoiceSearch.trim().toLowerCase()
    const matchesStatus = invoiceMappingStatus === 'all'
      || (invoiceMappingStatus === 'failed' ? d.extraction_status === 'failed' : d.mapping_status === invoiceMappingStatus)
    return matchesStatus
      && (!search || [d.filename, d.fields.vendor_legal_name?.value, d.fields.invoice_number?.value].some(x => x?.toLowerCase().includes(search)))
  })
  const missingEvidence = issues.filter(e => exceptionState(e) === 'missing_evidence').length
  const validationFindings = issues.filter(e => exceptionState(e) === 'validation_finding').length
  const vendorById = useMemo(() => new Map(rows.map(v => [v.id, v])), [rows])
  const categories = [...new Set(issues.map(e => e.category))].sort()
  const fields = [...new Set(cleanupRows.map(i => i.field_name))].sort()
  const visibleIssues = issues.filter(e => {
    const vendor = vendorById.get(e.vendor_id)
    const state = exceptionState(e)
    const search = exceptionSearch.trim().toLowerCase()
    return (exceptionStatus === 'all' || state === exceptionStatus)
      && (exceptionCategory === 'all' || e.category === exceptionCategory)
      && (exceptionSeverity === 'all' || e.severity === exceptionSeverity)
      && (!search || [vendor?.legal_name, vendor?.vendor_code, e.invoice_number, e.source_filename, e.title, e.check_code].some(x => x?.toLowerCase().includes(search)))
  })
  const visibleCleanup = cleanupRows.filter(item =>
    (cleanupVendor === 'all' || item.vendor_id === cleanupVendor)
    && (cleanupField === 'all' || item.field_name === cleanupField),
  )
  const priorityIssues = [...issues].sort((a, b) => severityRank(a.severity) - severityRank(b.severity)).slice(0, 3)
  const switchDataset = (next: 'hr' | 'synthetic') => {
    setSource(next)
    setExceptionSearch(''); setExceptionStatus('all'); setExceptionCategory('all'); setExceptionSeverity('all')
    setCleanupVendor('all'); setCleanupField('all'); setInvoiceSearch(''); setInvoiceMappingStatus('all')
    setExpandedException(null); setExpandedDocument(null)
  }
  const errors = [vendors.error, exceptions.error, cleanup.error, rules.error, documents.error, batches.error, seed.error, run.error, scan.error, createRule.error, approveRule.error, importDocs.error]
  const error = errors.find(Boolean) as Error | undefined

  return <div className="page-wrapper vendor-compliance-page">
    <header className="page-header">
      <h1 className="page-title">Vendor Compliance</h1>
      <p className="page-subtitle">Review supplier invoices and resolve GST, TDS, and MSME evidence gaps.</p>
    </header>

    <section className="card mb-8"><div className="card-body vc-toolbar">
      <span className="text-sm vc-active-source">Dataset: <strong>{source === 'hr' ? 'Supplier Invoices' : 'Developer test records'}</strong></span>
      <button className="btn btn-primary" onClick={() => run.mutate()} disabled={run.isPending || rows.length === 0}><RefreshCw size={15} />{run.isPending ? 'Checking…' : 'Run compliance checks'}</button>
      <button className="btn btn-secondary" onClick={() => scan.mutate()} disabled={scan.isPending || rows.length === 0}><ScanSearch size={15} />{scan.isPending ? 'Scanning…' : 'Scan vendor master'}</button>
    </div></section>

    <section className="card vc-source-summary mb-8">
      <div><div className="text-muted text-sm">Active dataset</div><strong>{source === 'hr' ? 'Supplier Invoices' : 'Developer test records'}</strong></div>
      <div><div className="text-muted text-sm">Documents processed</div><strong>{source === 'hr' ? (documents.isLoading ? 'Loading…' : documentCount + ' invoices') : 'Not applicable to test records'}</strong></div>
      <div><div className="text-muted text-sm">Latest import status</div><strong title={latestBatch?.created_at ?? ''}>{source === 'hr' ? (batches.isLoading ? 'Loading…' : latestBatch ? latestBatch.parsed_files + '/' + latestBatch.total_files + ' parsed · ' + latestBatch.failed_files + ' failed · ' + latestBatch.review_required_files + ' need review' : 'No import yet') : 'Test records only'}</strong></div>
      <span className={'badge ' + (source === 'hr' ? (documentCount ? 'badge-success' : 'badge-warning') : 'badge-info')}>{source === 'hr' ? (documentCount ? 'Dataset ready' : 'No invoices imported') : 'Test dataset'}</span>
    </section>

    <nav className="vc-tabs" role="tablist" aria-label="Vendor compliance sections">
      {tabs.map(tab => <button key={tab.id} id={'tab-' + tab.id} type="button" role="tab" aria-controls={'panel-' + tab.id} aria-selected={view === tab.id} tabIndex={view === tab.id ? 0 : -1} className={view === tab.id ? 'vc-tab active' : 'vc-tab'} onClick={() => setView(tab.id)} onKeyDown={event => {
        if (event.key !== 'ArrowRight' && event.key !== 'ArrowLeft') return
        event.preventDefault()
        const nextIndex = (tabs.findIndex(t => t.id === tab.id) + (event.key === 'ArrowRight' ? 1 : tabs.length - 1)) % tabs.length
        setView(tabs[nextIndex].id)
        document.getElementById('tab-' + tabs[nextIndex].id)?.focus()
      }}>
        {tab.label}{tab.id === 'invoices' && source === 'hr' ? <span>{documentCount}</span> : tab.id === 'exceptions' ? <span>{issues.length}</span> : tab.id === 'cleanup' ? <span>{cleanupRows.length}</span> : null}
      </button>)}
    </nav>

    {error && <div className="card mb-8"><div className="card-body vc-error">API error: {error.message}. Confirm the backend is running and migrations are applied.</div></div>}

    {view === 'overview' && <section id="panel-overview" aria-labelledby="tab-overview" role="tabpanel" className="vc-panel">
      <div className="vc-metrics">
        <Metric label="Documents processed" value={source === 'hr' ? (documents.isLoading ? '…' : documentCount) : '—'} help="Invoice documents imported into the selected dataset." />
        <Metric label="Vendors identified" value={vendors.isLoading ? '…' : rows.length} help="Vendors returned by the API for the selected dataset only." />
        <Metric label="Validation findings" value={exceptions.isLoading ? '…' : validationFindings} help="Recorded checks without a missing-information flag. Review findings are not official tax determinations." />
        <Metric label="Missing-evidence findings" value={exceptions.isLoading ? '…' : missingEvidence} help="Findings classified as missing evidence; several can relate to one vendor or invoice. Manual-review findings are counted separately." />
      </div>
      <div className="vc-overview-grid">
        <section className="card">
          <div className="card-header"><span className="card-title">Priority exceptions</span><button className="btn btn-ghost btn-sm" onClick={() => setView('exceptions')}>View all</button></div>
          <div className="table-container vc-priority-table"><table className="data-table"><thead><tr><th>Vendor</th><th>Issue</th><th>Source</th><th>Status</th><th>Severity</th></tr></thead><tbody>
            {priorityIssues.length === 0 ? <tr><td colSpan={5}>No findings for this dataset yet.</td></tr> : priorityIssues.map(e => <tr key={e.id}><td>{vendorById.get(e.vendor_id)?.legal_name ?? 'Vendor'}</td><td>{e.title}</td><td>{e.invoice_number ? 'Invoice ' + e.invoice_number : e.source_filename ?? 'Vendor-level'}</td><td>{exceptionStateLabel(e)}</td><td><span className={'badge ' + (e.severity === 'high' ? 'badge-danger' : 'badge-warning')}>{formatStatus(e.severity)}</span></td></tr>)}
          </tbody></table></div>
        </section>
        <section className="card">
          <div className="card-header"><span className="card-title">Reports &amp; Exports</span></div>
          <div className="card-body vc-deliverables">
            <a className="btn btn-primary" href={reportUrl('scorecards', source)}>Vendor scorecard CSV</a>
            <a className="btn btn-primary" href={reportUrl('exceptions', source)}>Compliance exception report CSV</a>
            <a className="btn btn-primary" href={reportUrl('cleanup', source)}>Vendor master cleanup CSV</a>
            {source === 'hr' && <a className="btn btn-secondary" href="/api/v1/vendor-compliance/documents/export.csv">Document review CSV</a>}
          </div>
        </section>
      </div>
      <details className="card vc-how-to"><summary><Info size={15} />How to read these results</summary><p className="text-sm text-muted">Invoices provide invoice-level evidence. GSTR-2B, payment/bank records, TDS challans/returns, and authoritative GST, PAN, or MSME evidence are unavailable unless separately supplied. Missing evidence is a follow-up item, not proof of a tax violation.</p></details>
    </section>}

    {view === 'invoices' && <section id="panel-invoices" aria-labelledby="tab-invoices" role="tabpanel" className="vc-panel">
      {source === 'hr' ? <>
      <section className="card mb-8">
        <div className="card-header"><span className="card-title">Invoice documents</span><button className="btn btn-secondary btn-sm" onClick={() => setShowImportForm(v => !v)}><Upload size={14} />{showImportForm ? 'Close import' : 'Import invoices'}</button></div>
        {showImportForm && <div className="card-body vc-import-body">
          <p className="text-sm text-muted">Select invoice PDFs or a ZIP archive. Previously imported files are detected by hash and will not be duplicated.</p>
          <div className="vc-import-controls"><input type="file" accept=".pdf,.zip,application/pdf,application/zip" multiple onChange={e => setSelectedFiles(Array.from(e.target.files ?? []))} /><button className="btn btn-primary" disabled={!selectedFiles.length || importDocs.isPending} onClick={() => importDocs.mutate(selectedFiles)}><Upload size={15} />{importDocs.isPending ? 'Importing…' : 'Import ' + (selectedFiles.length || '') + ' file(s)'}</button></div>
          {importDocs.data && <p className="text-sm">Latest upload: {importDocs.data.parsed_files}/{importDocs.data.total_files} parsed · {importDocs.data.failed_files} failed · {importDocs.data.duplicate_files} duplicates · {importDocs.data.review_required_files} require review.</p>}
        </div>}
      </section>
      <section className="card">
        <div className="card-header"><span className="card-title">Invoice register</span><span className="text-muted text-sm">{visibleDocs.length} of {documentCount} documents</span></div>
        <div className="card-body vc-filters">
          <input className="form-input" value={invoiceSearch} onChange={e => setInvoiceSearch(e.target.value)} placeholder="Search vendor, invoice or source file" aria-label="Search invoices" />
          <select className="form-select" value={invoiceMappingStatus} onChange={e => setInvoiceMappingStatus(e.target.value)} aria-label="Filter invoices by processing status"><option value="all">All processing statuses</option><option value="mapped">Mapped</option><option value="review_required">Review required</option><option value="failed">Failed extraction</option></select>
        </div>
        <div className="table-container vc-scroll-table"><table className="data-table vc-invoice-table">
          <thead><tr><th>Source document</th><th>Document type</th><th>Extraction</th><th>Mapping</th><th>Vendor</th><th>Invoice / date</th><th>Currency / total</th><th>Review notes</th><th>Details</th></tr></thead>
          <tbody>{visibleDocs.length === 0 ? <tr><td colSpan={9}>{docs.length ? 'No invoices match these filters.' : 'No invoice documents imported. Use Import invoices to add files.'}</td></tr> : visibleDocs.map(d => {
            const expanded = expandedDocument === d.id
            return <Fragment key={d.id}><tr>
              <td className="vc-invoice-source" title={d.filename} aria-label={d.filename}>{d.filename}</td>
              <td className="vc-invoice-type">{formatStatus(d.document_type)}</td>
              <td className="vc-invoice-status"><span className={'badge ' + (d.extraction_status === 'parsed' ? 'badge-success' : 'badge-warning')}>{formatStatus(d.extraction_status)}</span></td>
              <td className="vc-invoice-status"><span className={'badge ' + (d.mapping_status === 'mapped' ? 'badge-success' : 'badge-warning')}>{formatStatus(d.mapping_status)}</span></td>
              <td className="vc-invoice-vendor">{d.fields.vendor_legal_name?.value ?? 'Unresolved'}</td>
              <td className="vc-invoice-identity"><div>{d.fields.invoice_number?.value ?? '—'}</div><div className="text-muted text-sm">{d.fields.invoice_date?.value ?? 'Date missing'}</div></td>
              <td className="vc-invoice-total">{d.fields.currency?.value ?? 'Unknown'} {d.fields.total_invoice_value?.value ?? 'amount missing'}</td>
              <td className="vc-invoice-notes">{d.review_reasons.length ? <details className="vc-note-details"><summary className="vc-truncate">{d.review_reasons.join('; ')}</summary><div>{d.review_reasons.join('; ')}</div></details> : 'No review note'}</td>
              <td className="vc-invoice-details"><button className="btn btn-ghost btn-sm" aria-expanded={expanded} onClick={() => setExpandedDocument(expanded ? null : d.id)}>{expanded ? 'Hide' : 'Inspect'}</button></td>
            </tr>{expanded && <tr className="vc-document-detail"><td colSpan={9}><div className="vc-document-fields">{Object.entries(d.fields).map(([key, field]) => <div key={key}><strong>{formatStatus(key)}</strong>{field.value ?? formatStatus(field.status ?? 'not provided')}{field.evidence ? <div className="text-muted text-sm">Evidence: {field.evidence}</div> : null}</div>)}</div></td></tr>}</Fragment>
          })}</tbody>
        </table></div>
      </section>
      </> : <section className="card"><div className="card-body text-muted">Invoice documents are available in the Supplier Invoices dataset. Return to that dataset in Developer testing tools to inspect the production invoice records.</div></section>}
    </section>}

    {view === 'exceptions' && <section id="panel-exceptions" aria-labelledby="tab-exceptions" role="tabpanel" className="vc-panel">
      <section className="card">
        <div className="card-header"><span className="card-title">Compliance findings</span><span className="text-muted text-sm">{visibleIssues.length} of {issues.length}</span></div>
        <div className="card-body vc-filters">
          <input className="form-input" value={exceptionSearch} onChange={e => setExceptionSearch(e.target.value)} placeholder="Search vendor, invoice or issue" aria-label="Search exceptions" />
          <select className="form-select" value={exceptionStatus} onChange={e => setExceptionStatus(e.target.value)} aria-label="Filter by finding status"><option value="all">All statuses</option><option value="missing_evidence">Missing evidence</option><option value="validation_finding">Validation finding</option><option value="manual_review">Manual review</option></select>
          <select className="form-select" value={exceptionCategory} onChange={e => setExceptionCategory(e.target.value)} aria-label="Filter by category"><option value="all">All categories</option>{categories.map(c => <option key={c} value={c}>{formatStatus(c)}</option>)}</select>
          <select className="form-select" value={exceptionSeverity} onChange={e => setExceptionSeverity(e.target.value)} aria-label="Filter by severity"><option value="all">All severities</option><option value="high">High</option><option value="medium">Medium</option><option value="low">Low</option></select>
        </div>
        <div className="table-container vc-scroll-table"><table className="data-table vc-exception-table">
          <thead><tr><th>Vendor</th><th>Source invoice / document</th><th>Issue / category</th><th>Status</th><th>Severity</th><th>Amount at stake</th><th>Suggested action</th><th>Details</th></tr></thead>
          <tbody>{visibleIssues.length === 0 ? <tr><td colSpan={8}>No findings match these filters.</td></tr> : visibleIssues.map(e => {
            const vendor = vendorById.get(e.vendor_id)
            const expanded = expandedException === e.id
            return <Fragment key={e.id}>
              <tr><td className="vc-exception-vendor">{vendor?.legal_name ?? 'Unknown vendor'}</td>
                <td className="vc-exception-source">{e.invoice_number && <div className="vc-exception-invoice">Invoice {e.invoice_number}</div>}{e.source_filename ? <div className="vc-exception-filename text-muted text-sm" title={e.source_filename}>{e.source_filename}</div> : !e.invoice_number ? 'Vendor-level finding' : null}</td>
                <td className="vc-exception-issue"><div>{e.title}</div><div className="vc-exception-category text-muted text-sm">{formatStatus(e.category)} · {e.check_code}</div></td>
                <td className="vc-exception-status"><span className={'badge ' + (exceptionState(e) === 'missing_evidence' ? 'badge-warning' : exceptionState(e) === 'manual_review' ? 'badge-info' : 'badge-muted')}>{exceptionStateLabel(e)}</span></td>
                <td className="vc-exception-severity"><span className={'badge ' + (e.severity === 'high' ? 'badge-danger' : 'badge-warning')}>{formatStatus(e.severity)}</span></td>
                <td className="vc-exception-amount">{e.amount_at_stake ? e.currency + ' ' + Number(e.amount_at_stake).toLocaleString() : '—'}</td>
                <td className="vc-exception-action"><span className="vc-truncate" title={e.suggested_action} aria-label={e.suggested_action}>{e.suggested_action}</span></td>
                <td><button className="btn btn-ghost btn-sm" aria-expanded={expanded} onClick={() => setExpandedException(expanded ? null : e.id)}>{expanded ? 'Hide' : 'Inspect'}</button></td>
              </tr>
              {expanded && <tr className="vc-detail-row"><td colSpan={8}><strong>{e.title}</strong><p>{e.description}</p>{e.missing_information.length > 0 && <p><strong>Missing evidence:</strong> {e.missing_information.join('; ')}</p>}<p><strong>Suggested action:</strong> {e.suggested_action}</p><p className="text-muted text-sm">Check {e.check_code} · {vendor?.vendor_code ?? 'Vendor'}{e.invoice_number ? ' · Invoice ' + e.invoice_number : ''}{e.source_filename ? ' · ' + e.source_filename : ''}</p></td></tr>}
            </Fragment>
          })}</tbody>
        </table></div>
      </section>
    </section>}

    {view === 'cleanup' && <section id="panel-cleanup" aria-labelledby="tab-cleanup" role="tabpanel" className="vc-panel">
      <section className="card">
        <div className="card-header"><span className="card-title">Vendor master data issues</span><div className="vc-inline-actions"><span className="text-muted text-sm">{visibleCleanup.length} findings</span><a className="btn btn-secondary btn-sm" href={reportUrl('cleanup', source)}>Vendor master cleanup CSV</a></div></div>
        <div className="card-body vc-filters">
          <select className="form-select" value={cleanupVendor} onChange={e => setCleanupVendor(e.target.value)} aria-label="Filter cleanup by vendor"><option value="all">All vendors</option>{rows.map(v => <option key={v.id} value={v.id}>{v.legal_name}</option>)}</select>
          <select className="form-select" value={cleanupField} onChange={e => setCleanupField(e.target.value)} aria-label="Filter cleanup by field"><option value="all">All fields</option>{fields.map(f => <option key={f} value={f}>{formatStatus(f)}</option>)}</select>
        </div>
        <div className="table-container vc-scroll-table"><table className="data-table vc-cleanup-table"><thead><tr><th>Vendor</th><th>Field</th><th>Current value / status</th><th>Reason</th><th>Suggested action</th></tr></thead>
          <tbody>{visibleCleanup.length === 0 ? <tr><td colSpan={5}>No cleanup findings match these filters.</td></tr> : visibleCleanup.map(item => {
            const vendor = vendorById.get(item.vendor_id)
            return <tr key={item.id}><td>{vendor?.legal_name ?? 'Unknown vendor'}</td><td>{formatStatus(item.field_name)}</td><td>{cleanupValue(vendor, item.field_name, item.issue_type)}</td><td><span className="vc-truncate" title={item.description}>{item.description}</span></td><td><span className="vc-truncate" title={item.recommended_fix}>{item.recommended_fix}</span></td></tr>
          })}</tbody>
        </table></div>
      </section>
    </section>}

    {view === 'rules' && <section id="panel-rules" aria-labelledby="tab-rules" role="tabpanel" className="vc-panel">
      <section className="card">
        <div className="card-header"><span className="card-title">Versioned tax rules</span><button className="btn btn-secondary btn-sm" onClick={() => setShowRuleForm(v => !v)}>{showRuleForm ? 'Close' : 'Add rule'}</button></div>
        <div className="card-body">
          <p className="text-sm text-muted">Rules stay pending review until explicitly approved. Only approved, effective rules apply to rate checks. Sample rules are illustrative and never treated as approved legal rules.</p>
          {showRuleForm && <form onSubmit={e => { e.preventDefault(); const d = new FormData(e.currentTarget); createRule.mutate({
            rule_code: String(d.get('rule_code')), tax_category: String(d.get('tax_category')), description: String(d.get('description')),
            rate_pct: String(d.get('rate_pct')), threshold_amount: String(d.get('threshold_amount') || '0'), tax_base: String(d.get('tax_base')),
            effective_from: String(d.get('effective_from')), effective_to: String(d.get('effective_to') || '') || null,
            section_1961: String(d.get('section_1961') || '') || null, section_2025: String(d.get('section_2025') || '') || null,
            source_reference: String(d.get('source_reference')), version: String(d.get('version')),
          }) }} className="vc-rule-form">
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
        </div>
        <div className="table-container"><table className="data-table vc-rules-table"><thead><tr><th>Rule</th><th>Category / section</th><th>Rate / threshold</th><th>Effective dates</th><th>Version</th><th>Source reference</th><th>Approval</th></tr></thead><tbody>
          {ruleRows.length === 0 ? <tr><td colSpan={7}>No configured tax rules.</td></tr> : ruleRows.map(rule => <tr key={rule.id}>
            <td><strong>{rule.rule_code}{rule.is_sample_rule ? ' · Sample only' : ''}</strong><div className="text-muted text-sm">{rule.description}</div></td>
            <td>{formatStatus(rule.tax_category)} · {rule.section_1961 ?? rule.section_2025 ?? 'Section not mapped'}</td>
            <td>{rule.rate_pct}%<div className="text-muted text-sm">Threshold {rule.threshold_amount}</div></td>
            <td>{rule.effective_from}{rule.effective_to ? ' → ' + rule.effective_to : ' onward'}</td><td>{rule.version}</td><td>{rule.source_reference ?? 'Missing source'}</td>
            <td>{rule.verification_status === 'approved' ? <span className="badge badge-success">Approved</span> : rule.is_sample_rule ? <span className="badge badge-warning">Sample only</span> : <button className="btn btn-secondary btn-sm" onClick={() => { const who = window.prompt('Approver name'); if (who?.trim()) approveRule.mutate({ id: rule.id, who: who.trim() }) }}>Approve</button>}</td>
          </tr>)}
        </tbody></table></div>
      </section>
    </section>}

    <details className="vc-developer-tools">
      <summary><Database size={14} />Developer testing tools</summary>
      <div className="vc-developer-actions">
        <span className="text-sm text-muted">Test data is isolated from Supplier Invoices and is only shown when selected.</span>
        {source === 'hr' ? <button className="btn btn-secondary btn-sm" onClick={() => switchDataset('synthetic')}>Use test dataset</button> : <button className="btn btn-secondary btn-sm" onClick={() => switchDataset('hr')}>Return to Supplier Invoices</button>}
        <button className="btn btn-secondary btn-sm" onClick={() => { switchDataset('synthetic'); seed.mutate() }} disabled={seed.isPending}><Database size={14} />{seed.isPending ? 'Loading…' : 'Load synthetic test records'}</button>
      </div>
    </details>
  </div>
}

function Metric({ label, value, help }: { label: string; value: string | number; help: string }) {
  return <div className="stat-card" title={help}><div className="stat-label">{label} <Info size={12} /></div><div className="stat-value">{value}</div></div>
}
function exceptionState(e: VendorException): string {
  if (/MANUAL|REVIEW|SOURCE_DOCUMENT|UNCONFIRMED|UNVERIFIED|AMBIGUOUS/i.test(e.check_code)) return 'manual_review'
  return e.missing_information.length ? 'missing_evidence' : 'validation_finding'
}
function exceptionStateLabel(e: VendorException) {
  const state = exceptionState(e)
  return state === 'missing_evidence' ? 'Missing evidence' : state === 'manual_review' ? 'Manual review' : 'Validation finding'
}
function severityRank(severity: string) { return severity === 'high' ? 0 : severity === 'medium' ? 1 : 2 }
function cleanupValue(vendor: Vendor | undefined, field: string, issueType: string) {
  if (!vendor) return 'Vendor record unavailable'
  const values: Record<string, string | null | undefined> = { pan: vendor.pan, gstin: vendor.gstin, msme_type: vendor.msme_type }
  if (field in values) return values[field] || 'Missing'
  if (/missing|required/i.test(issueType)) return 'Missing'
  if (/invalid|malformed|inconsistent|mismatch/i.test(issueType)) return 'Present; validation issue'
  return 'Requires source-record review'
}
function reportUrl(name: string, source: string) { return '/api/v1/vendor-compliance/reports/' + name + '.csv?source=' + source }
function formatStatus(status: string) {
  return status.replace(/_/g, ' ').replace(/\b\w/g, character => character.toUpperCase())
}
