import axios from 'axios'

export const api = axios.create({
  baseURL: '/api/v1',
  headers: { 'Content-Type': 'application/json' },
})

// ─── Analytics ────────────────────────────────────────────────
export const fetchOverview = () => api.get('/analytics/overview').then(r => r.data)
export const fetchGatewayCosts = (gateway?: string) =>
  api.get('/analytics/gateway-costs', { params: gateway ? { gateway } : {} }).then(r => r.data)
export const fetchSettlements = () => api.get('/analytics/settlements').then(r => r.data)

// ─── Uploads ──────────────────────────────────────────────────
export const fetchUploads = () => api.get('/uploads').then(r => r.data)
export const fetchUpload = (id: string) => api.get(`/uploads/${id}`).then(r => r.data)
export const uploadDataset = (formData: FormData) =>
  api.post('/uploads', formData, { headers: { 'Content-Type': 'multipart/form-data' } }).then(r => r.data)

// ─── Import Jobs ──────────────────────────────────────────────
export const fetchJobs = () => api.get('/jobs').then(r => r.data)
export const fetchJob = (id: string) => api.get(`/jobs/${id}`).then(r => r.data)

// ─── Reconciliation ────────────────────────────────────────────
export const fetchReconciliationRuns = () => api.get('/reconciliation/runs').then(r => r.data)
export const fetchReconciliationRun = (id: string) => api.get(`/reconciliation/runs/${id}`).then(r => r.data)
export const triggerReconciliation = () => api.post('/reconciliation/runs').then(r => r.data)
export const fetchRunMatches = (runId: string, page = 1, pageSize = 50) =>
  api.get(`/reconciliation/runs/${runId}/matches`, { params: { page, page_size: pageSize } }).then(r => r.data)
export const fetchRunExceptions = (runId: string, page = 1, pageSize = 50) =>
  api.get(`/reconciliation/runs/${runId}/exceptions`, { params: { page, page_size: pageSize } }).then(r => r.data)

// ─── Exceptions ───────────────────────────────────────────────
export type ExceptionFilters = {
  category?: string
  gateway?: string
  review_status?: string
  currency?: string
  severity?: string
  page?: number
  page_size?: number
}
export const fetchExceptions = (filters: ExceptionFilters = {}) =>
  api.get('/exceptions', { params: filters }).then(r => r.data)
export const fetchException = (id: string) => api.get(`/exceptions/${id}`).then(r => r.data)
export const investigateException = (id: string) => api.post(`/exceptions/${id}/investigate`).then(r => r.data)
export const reviewException = (id: string, body: { action: string; reviewer?: string; notes?: string }) =>
  api.patch(`/exceptions/${id}/review`, body).then(r => r.data)
export const fetchAuditTrail = (id: string) => api.get(`/exceptions/${id}/audit`).then(r => r.data)

// ─── Pricing ──────────────────────────────────────────────────
export const fetchPricingRules = () => api.get('/pricing-rules').then(r => r.data)
export const createPricingRule = (body: unknown) => api.post('/pricing-rules', body).then(r => r.data)
export const updatePricingRule = (id: string, body: unknown) => api.patch(`/pricing-rules/${id}`, body).then(r => r.data)
export const deletePricingRule = (id: string) => api.delete(`/pricing-rules/${id}`).then(r => r.data)
export const createSavingsScenario = (body: unknown) => api.post('/savings-scenarios', body).then(r => r.data)
export const fetchSavingsScenarios = () => api.get('/savings-scenarios').then(r => r.data)

// ─── Vendor compliance ────────────────────────────────────────
export const fetchVendors = (source?: string) => api.get('/vendor-compliance/vendors', { params: source ? { source } : {} }).then(r => r.data)
export const fetchVendorScorecards = (source?: string) => api.get('/vendor-compliance/scorecards', { params: source ? { source } : {} }).then(r => r.data)
export const fetchVendorExceptions = (source?: string) => api.get('/vendor-compliance/exceptions', { params: source ? { source } : {} }).then(r => r.data)
export const fetchVendorCleanup = (source?: string) => api.get('/vendor-compliance/master-cleanup', { params: source ? { source } : {} }).then(r => r.data)
export const fetchVendorDocuments = () => api.get('/vendor-compliance/documents').then(r => r.data)
export const fetchVendorDocumentBatches = () => api.get('/vendor-compliance/documents/batches').then(r => r.data)
export const importVendorDocuments = (files: File[]) => {
  const data = new FormData()
  files.forEach(file => data.append('files', file))
  return api.post('/vendor-compliance/documents/import', data, { headers: { 'Content-Type': 'multipart/form-data' } }).then(r => r.data)
}
export const fetchVendorRules = () => api.get('/vendor-compliance/tax-rules').then(r => r.data)
export const seedVendorData = () => api.post('/vendor-compliance/seed').then(r => r.data)
export const runVendorChecks = (source?: string) => api.post('/vendor-compliance/checks/run', null, { params: source ? { source } : {} }).then(r => r.data)
export const scanVendorMaster = (source?: string) => api.post('/vendor-compliance/master-cleanup/scan', null, { params: source ? { source } : {} }).then(r => r.data)
export const createVendorRule = (body: unknown) => api.post('/vendor-compliance/tax-rules', body).then(r => r.data)
export const approveVendorRule = (id: string, approved_by: string) => api.post(`/vendor-compliance/tax-rules/${id}/approve`, { approved_by }).then(r => r.data)

// ─── Health ───────────────────────────────────────────────────
export const fetchHealth = () => api.get('/health').then(r => r.data).catch(() => api.get('/../health').then(r => r.data))
