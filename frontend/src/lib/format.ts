import { format, formatDistanceToNow } from 'date-fns'

export function formatDate(iso: string | null | undefined): string {
  if (!iso) return '—'
  try {
    return format(new Date(iso), 'MMM d, yyyy HH:mm')
  } catch {
    return iso
  }
}

export function formatRelative(iso: string | null | undefined): string {
  if (!iso) return '—'
  try {
    return formatDistanceToNow(new Date(iso), { addSuffix: true })
  } catch {
    return iso
  }
}

export function formatCurrency(value: string | number | null | undefined, currency = 'INR'): string {
  if (value == null || value === '') return '—'
  const num = typeof value === 'string' ? parseFloat(value) : value
  if (isNaN(num)) return String(value)
  return new Intl.NumberFormat('en-IN', {
    style: 'currency',
    currency,
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(num)
}

export function formatNumber(value: number | null | undefined): string {
  if (value == null) return '—'
  return new Intl.NumberFormat('en-IN').format(value)
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`
}

export function formatPct(value: number | null | undefined): string {
  if (value == null) return '—'
  return `${value.toFixed(2)}%`
}

export function severityClass(severity: string): string {
  switch (severity?.toLowerCase()) {
    case 'critical': return 'badge-danger'
    case 'high': return 'badge-warning'
    case 'medium': return 'badge-info'
    case 'low': return 'badge-success'
    default: return 'badge-muted'
  }
}

export function reviewStatusClass(status: string): string {
  switch (status) {
    case 'open': return 'badge-danger'
    case 'in_review': return 'badge-warning'
    case 'resolved': return 'badge-success'
    case 'dismissed': return 'badge-muted'
    default: return 'badge-muted'
  }
}

export function jobStatusClass(status: string): string {
  switch (status) {
    case 'completed': return 'badge-success'
    case 'running': return 'badge-info'
    case 'pending': return 'badge-warning'
    case 'failed': return 'badge-danger'
    default: return 'badge-muted'
  }
}

export function reconciliationStatusClass(status: string): string {
  switch (status) {
    case 'completed': return 'badge-success'
    case 'running': return 'badge-info'
    case 'pending': return 'badge-warning'
    case 'failed': return 'badge-danger'
    default: return 'badge-muted'
  }
}

export function truncateId(id: string, len = 8): string {
  if (!id) return '—'
  return id.length > len ? `${id.slice(0, len)}…` : id
}

export function gatewayLabel(gw: string | null | undefined): string {
  if (!gw) return '—'
  return gw === 'gateway_a' ? 'Gateway A' : gw === 'gateway_b' ? 'Gateway B' : gw
}
