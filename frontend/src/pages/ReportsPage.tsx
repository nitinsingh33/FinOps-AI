import { FileDown, Download, AlertTriangle, CreditCard, RefreshCw, RotateCcw, Printer } from 'lucide-react'

const BASE = '/api/v1/reports'

interface ReportCard {
  title: string
  description: string
  endpoint: string
  params?: Record<string, string>
  icon: React.ElementType
  accent: string
  accentBg: string
  filename: string
}

const REPORTS: ReportCard[] = [
  {
    title: 'Reconciliation Exceptions',
    description: 'All exceptions with category, severity, review status, amounts and descriptions.',
    endpoint: `${BASE}/exceptions/download`,
    icon: AlertTriangle,
    accent: 'var(--color-danger)',
    accentBg: 'var(--color-danger-dim)',
    filename: 'reconciliation_exceptions.csv',
  },
  {
    title: 'Payment Records',
    description: 'Gateway payment data including status, fees, tax, payment method and card details.',
    endpoint: `${BASE}/payments/download`,
    icon: CreditCard,
    accent: 'var(--color-accent)',
    accentBg: 'var(--color-accent-dim)',
    filename: 'payments.csv',
  },
  {
    title: 'Gateway Transactions',
    description: 'All gateway B/A transaction entries with settlement, payout and net amount info.',
    endpoint: `${BASE}/transactions/download`,
    icon: RefreshCw,
    accent: 'var(--color-cyan)',
    accentBg: 'var(--color-cyan-dim)',
    filename: 'transactions.csv',
  },
  {
    title: 'Refund Records',
    description: 'All refund entries with ARN, status, amounts and gateway identifiers.',
    endpoint: `${BASE}/refunds/download`,
    icon: RotateCcw,
    accent: 'var(--color-warning)',
    accentBg: 'var(--color-warning-dim)',
    filename: 'refunds.csv',
  },
]

const FILTERED_DOWNLOADS = [
  {
    title: 'Open Exceptions',
    endpoint: `${BASE}/exceptions/download?review_status=open`,
    description: 'Only open (unresolved) exceptions',
    badge: 'badge-danger',
  },
  {
    title: 'GWA Exceptions',
    endpoint: `${BASE}/exceptions/download?gateway=gateway_a`,
    description: 'Gateway A exceptions only',
    badge: 'badge-purple',
  },
  {
    title: 'GWB Exceptions',
    endpoint: `${BASE}/exceptions/download?gateway=gateway_b`,
    description: 'Gateway B exceptions only',
    badge: 'badge-purple',
  },
  {
    title: 'Critical Exceptions',
    endpoint: `${BASE}/exceptions/download?severity=critical`,
    description: 'Critical severity exceptions only',
    badge: 'badge-danger',
  },
  {
    title: 'GWA Payments',
    endpoint: `${BASE}/payments/download?gateway=gateway_a`,
    description: 'Gateway A payment records',
    badge: 'badge-info',
  },
  {
    title: 'GWB Transactions',
    endpoint: `${BASE}/transactions/download?gateway=gateway_b`,
    description: 'Gateway B transaction records',
    badge: 'badge-info',
  },
]

export default function ReportsPage() {
  const handleDownload = (endpoint: string, filename: string) => {
    const link = document.createElement('a')
    link.href = endpoint
    link.download = filename
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
  }

  return (
    <div className="page-wrapper">
      <div className="page-header">
        <h1 className="page-title">Reports</h1>
        <p className="page-subtitle">Download reconciliation data, exceptions, and payment records as CSV</p>
      </div>

      <div className="card mb-8"><div className="card-body" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 16 }}>
        <div><strong>One-page Executive Summary</strong><p className="text-sm text-muted">Generated from persisted API data, with transaction currency groups kept separate.</p></div>
        <a className="btn btn-secondary" href={`${BASE}/executive-summary`} target="_blank" rel="noreferrer"><Printer size={15} /> Open summary</a>
      </div></div>

      {/* Main report cards */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 24, marginBottom: 40 }}>
        {REPORTS.map(report => {
          const Icon = report.icon
          return (
            <div
              key={report.title}
              className="card"
              style={{ position: 'relative', overflow: 'hidden' }}
            >
              <div style={{
                position: 'absolute', top: 0, left: 0, right: 0, height: 2,
                background: report.accent, opacity: 0.7,
              }} />
              <div className="card-body" style={{ display: 'flex', gap: 20, alignItems: 'flex-start' }}>
                <div style={{
                  width: 48, height: 48, borderRadius: 12, background: report.accentBg,
                  display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0,
                }}>
                  <Icon size={22} color={report.accent} />
                </div>
                <div style={{ flex: 1 }}>
                  <div style={{ fontSize: 16, fontWeight: 700, color: 'var(--color-text-primary)', marginBottom: 6 }}>
                    {report.title}
                  </div>
                  <p style={{ fontSize: 13, color: 'var(--color-text-secondary)', lineHeight: 1.6, marginBottom: 16 }}>
                    {report.description}
                  </p>
                  <button
                    className="btn btn-secondary"
                    onClick={() => handleDownload(report.endpoint, report.filename)}
                  >
                    <Download size={14} /> Download CSV
                  </button>
                </div>
              </div>
            </div>
          )
        })}
      </div>

      {/* Filtered downloads */}
      <div className="card">
        <div className="card-header">
          <span className="card-title">
            <FileDown size={16} color="var(--color-accent-2)" />
            Filtered Downloads
          </span>
        </div>
        <div className="card-body">
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 16 }}>
            {FILTERED_DOWNLOADS.map(d => (
              <button
                key={d.title}
                className="btn btn-secondary"
                style={{
                  height: 'auto', padding: '14px 16px', flexDirection: 'column',
                  alignItems: 'flex-start', gap: 6, textAlign: 'left',
                }}
                onClick={() => handleDownload(d.endpoint, `${d.title.toLowerCase().replace(/\s/g, '_')}.csv`)}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <Download size={13} />
                  <span style={{ fontWeight: 600, fontSize: 13 }}>{d.title}</span>
                </div>
                <div style={{ fontSize: 11, color: 'var(--color-text-muted)' }}>{d.description}</div>
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Info box */}
      <div style={{
        marginTop: 32, padding: '16px 20px',
        background: 'var(--color-accent-dim)', border: '1px solid rgba(79,156,249,0.15)',
        borderRadius: 12, display: 'flex', alignItems: 'flex-start', gap: 12,
      }}>
        <FileDown size={18} color="var(--color-accent)" style={{ flexShrink: 0, marginTop: 2 }} />
        <div>
          <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--color-accent)', marginBottom: 4 }}>About Exports</div>
          <p style={{ fontSize: 13, color: 'var(--color-text-secondary)', lineHeight: 1.7 }}>
            All CSV exports are generated in real-time from the database. Large exports may take a few seconds.
            Timestamps are in UTC. Reports are subject to current data availability — run a reconciliation first
            to populate exceptions.
          </p>
        </div>
      </div>
    </div>
  )
}
