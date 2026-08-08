
export type Role = 'supplier_viewer' | 'supplier_admin' | 'retail_analyst' | 'system_admin'

export type User = {
  user_id: number
  email: string
  display_name: string
  role: Role
  supplier_id: number | null
  supplier_name: string | null
}

export type LoginResponse = {
  access_token: string
  token_type: 'bearer'
  user: User
}

export type ColumnUnit = 'st' | '%' | 'p.e.' | (string & {})

export type Column = {
  key: string
  type: 'date' | 'text' | 'number'
  label: string
  unit?: ColumnUnit | null
}

export type ChartType = 'line' | 'bar' | 'stacked_bar' | 'area' | 'pie' | 'kpi' | 'table'

export type ChartSpec = {
  type: ChartType
  x: string | null
  y: string[]
  series: string | null
  sort: 'asc' | 'desc' | null
  limit: number | null
  title: string
  subtitle: string | null
  markers: string[]
  marker_label: string | null
}

export type DateRange = { from: string; to: string }

export type Provenance = {
  tool: string
  source: string
  scope: string
  currency: string
  vat: 'excl' | 'incl'
  time_range: DateRange
  compare_range: DateRange | null
  coverage: DateRange
  filters_applied: Record<string, unknown>
  row_count: number
  truncated: boolean
  executed_at: string
  tool_args: Record<string, unknown>
}

export type CardStatus = 'ok' | 'cannot_answer' | 'clarify' | 'validation_failed' | 'explain'

export type ToolCallRecord = {
  query_id: string
  tool: string
  provenance: Provenance
  row_count: number
}

export type Claim = {
  literal: string
  query_id: string
}

export type AnswerCard = {
  card_id: string | null
  status: CardStatus
  narrative: string
  insights: string[]
  caveats: string[]
  chart: ChartSpec | null
  query_id: string | null
  columns: Column[]
  provenance: Provenance | null
  sources?: ToolCallRecord[]
  claims?: Claim[]
  suggestions: string[]
}

export type KpiKey = 'net_sales_sek' | 'category_share_pct' | 'units' | 'avg_price_sek'

export type Kpi = {
  key: KpiKey
  label: string
  value: number
  unit: ColumnUnit
  delta_pct: number | null
  delta_label: string | null
  rank_label: string | null
  spark: number[]
}

export type DashboardResponse = {
  kpis: Kpi[]
  cards: AnswerCard[]
}

export type MoversResponse = {
  cards: AnswerCard[]
}

export type ResultRow = Record<string, string | number | null>

export type ResultResponse = {
  query_id: string
  columns: Column[]
  rows: ResultRow[]
  row_count: number
  truncated: boolean
}

export type SharedView = {
  card: AnswerCard
  result: ResultResponse
  shared_by: string
  expires_at: string
  mode: 'snapshot' | 'live'
}

export type ChatEvent =
  | { type: 'status'; message: string }
  | { type: 'tool_call'; tool: string; args: Record<string, unknown> }
  | { type: 'tool_result'; tool: string; row_count: number | null }
  | { type: 'token'; text: string }
  | { type: 'preview'; card: AnswerCard }
  | { type: 'card'; card: AnswerCard }
  | { type: 'error'; message: string }

export type ChatHistoryEntry = { role: 'user' | 'assistant'; content: string }

export type SaveCardRequest = {
  title: string
  chart: ChartSpec
  tool_name: string
  tool_args: Record<string, unknown>
}

export type ShareResponse = { url: string; expires_at: string }

export type ApiError = { detail: string }
