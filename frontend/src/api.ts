export type Variant = {
  id: string
  label: string
  engine_ref: string
  overlay: string | null
  description: string
  engine?: { ref: string; sha?: string; subject?: string; dirty?: boolean; error?: string }
  overlay_rules?: { file: string; function: string; rule: string | null; note: string; line: number }[]
}

export type FindingRow = {
  id: string
  rule: string
  rules: string[]
  code: string
  codes: string[]
  name: string
  level: string
  type: string
  effect: string
  effect_label: string
  category: string
  summary: string
  impact: string
  confidence: string
  source: string
  has_case: boolean
  case_status: string | null
  scenario_count: number
  results: Record<string, string | null>
}

export type RuleResult = {
  rule: string
  service: string
  verdict: string
  checked: number
  flag: number
  good: number
  na: number
  flag_ids?: string[]
  good_ids?: string[]
  na_ids?: string[]
  flag_reason?: Record<string, string>
  error: { type: string; message: string; where?: string } | null
  overlay?: boolean
  args?: unknown
  missing?: boolean
}

export type Scenario = {
  id: string
  role: 'bug' | 'control' | 'collection'
  condition: string
  args?: unknown
  raw?: Record<string, unknown>
  expect: Record<string, unknown>
  why?: string
  rule?: string
  service?: string
}

export type Case = {
  finding: string
  rule: string
  service: string
  status: string
  effect?: string
  note?: string
  scenarios: Scenario[]
}

export type ScenarioResult = { role: string; ok: boolean; diffs: string[]; actual: Partial<RuleResult> & { preprocess?: string[] } }
export type CaseResult = { status: string; scenarios: Record<string, ScenarioResult> }

export type Job = {
  id: string
  kind: string
  label: string
  status: 'running' | 'done' | 'error'
  progress: number
  message: string
  result: ({ run_id?: string } & Record<string, unknown>) | null
  error: string | null
}

async function req<T>(method: string, url: string, body?: unknown): Promise<T> {
  const r = await fetch(url, {
    method,
    headers: body !== undefined ? { 'Content-Type': 'application/json' } : undefined,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  })
  if (!r.ok) {
    let msg = `${r.status} ${r.statusText}`
    try {
      const j = await r.json()
      msg = typeof j.detail === 'string' ? j.detail : JSON.stringify(j.detail ?? j)
    } catch {
      /* 본문 없음 */
    }
    throw new Error(msg)
  }
  return r.json()
}

export const api = {
  get: <T,>(url: string) => req<T>('GET', url),
  post: <T,>(url: string, body: unknown = {}) => req<T>('POST', url, body),
  del: <T,>(url: string) => req<T>('DELETE', url),
}

export const qs = (o: Record<string, string | undefined | null>) =>
  new URLSearchParams(Object.entries(o).filter(([, v]) => v != null && v !== '') as [string, string][]).toString()

export async function waitJob(id: string, onTick?: (j: Job) => void): Promise<Job> {
  for (;;) {
    const j = await api.get<Job>(`/api/jobs/${id}`)
    onTick?.(j)
    if (j.status !== 'running') return j
    await new Promise((r) => setTimeout(r, 800))
  }
}
