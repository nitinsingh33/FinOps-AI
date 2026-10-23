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
export const createSavingsScenario = (body: unknown) => api.post('/savings-scenarios', body).then(r => r.data)

// ─── Health ───────────────────────────────────────────────────
export const fetchHealth = () => api.get('/health').then(r => r.data).catch(() => api.get('/../health').then(r => r.data))
