// ─── Overview stats ───────────────────────────────────────────
export interface OverviewStats {
  total_payments: number
  total_transactions: number
  total_refunds: number
  total_exceptions: number
  open_exceptions: number
  reconciliation_runs: number
  matched_records: number
  unmatched_records: number
}

// ─── Upload / Dataset ─────────────────────────────────────────
export interface ImportJobSummary {
  id: string
  status: string
  imported_rows: number
}

export interface UploadedDataset {
  id: string
  filename: string
  dataset_type: string
  gateway: string
  file_size_bytes: number
  file_hash: string
  created_at: string
  import_jobs: ImportJobSummary[]
}

export interface ImportJob {
  id: string
  status: string
  total_rows: number | null
  imported_rows: number
  skipped_rows: number
  duplicate_count: number
  warning_count: number
  error_count: number
  started_at: string | null
  completed_at: string | null
}

// ─── Reconciliation ───────────────────────────────────────────
export interface ReconciliationRun {
  id: string
  status: string
  rule_version: string
  total_records: number | null
  matched_records: number | null
  unmatched_records: number | null
  exception_count: number | null
  summary: Record<string, unknown> | null
  error_message: string | null
  started_at: string | null
  completed_at: string | null
  created_at: string
}

export interface ReconciliationMatch {
  id: string
  match_method: string
  confidence: number
  payment_id: string | null
  gateway_txn_id: string | null
  amount_difference: string | null
  currency: string | null
}

// ─── Exceptions ───────────────────────────────────────────────
export interface ReconciliationException {
  id: string
  run_id: string | null
  category: string
  severity: string
  gateway: string | null
  currency: string | null
  amount_at_stake: string | null
  amount_difference: string | null
  expected_value: string | null
  observed_value: string | null
  description: string
  review_status: string
  source_payment_id: string | null
  source_txn_id: string | null
  created_at: string
}

export interface AIInvestigation {
  id: string
  provider: string
  model: string
  is_ai_generated: boolean
  summary: string | null
  verified_facts: string[] | null
  possible_explanations: string[] | null
  missing_information: string[] | null
  recommended_steps: string[] | null
  confidence_assessment: string | null
  status: string
  created_at: string
}

export interface ReviewHistory {
  id: string
  reviewer: string
  action: string
  previous_status: string
  new_status: string
  notes: string
  created_at: string
}

export interface ExceptionDetail extends ReconciliationException {
  evidence: Record<string, unknown> | null
  investigations: AIInvestigation[]
  review_history: ReviewHistory[]
}

// ─── Pricing ──────────────────────────────────────────────────
export interface PricingRule {
  id: string
  gateway: string
  rule_name: string
  payment_method: string | null
  currency: string | null
  fixed_fee_currency?: string | null
  country?: string | null
  is_international?: boolean | null
  fee_rate_pct: string | null
  fixed_fee: string | null
  tax_on_fee_pct: string | null
  min_fee?: string | null
  max_fee?: string | null
  effective_from?: string | null
  effective_to?: string | null
  is_illustrative: boolean
  notes: string | null
  created_at: string
}

export interface SavingsScenario {
  id?: string
  scenario_id: string
  name: string
  eligible_volume: string
  currency: string
  current_gateway?: string
  alternative_gateway?: string
  payment_method?: string | null
  country?: string | null
  current_estimated_fee: string | null
  alternative_estimated_fee: string | null
  estimated_difference: string | null
  estimated_difference_pct?: string | null
  estimated_lower_cost_gateway?: string | null
  fixed_fee_basis?: string
  created_at?: string
  is_estimate: boolean
  limitations: string[]
  assumptions_note: string
}

// ─── Gateway cost analysis ────────────────────────────────────
export interface GatewayFeeBreakdown {
  gateway: string
  currency: string
  payment_count: number
  gross_volume: number
  total_fees: number
  total_tax: number
  effective_rate_pct: number
  payment_method: string | null
}
