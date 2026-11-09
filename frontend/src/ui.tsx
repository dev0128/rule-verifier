import { useEffect, useState } from 'react'
import type { Job } from './api'

export const EFFECT_CLASS: Record<string, string> = {
  false_positive: 'c-fp',
  false_negative: 'c-fn',
  not_checked: 'c-nc',
  crash: 'c-crash',
  wrong_logic: 'c-wl',
}
export const EFFECT_ORDER = ['false_positive', 'false_negative', 'not_checked', 'crash', 'wrong_logic']
export const EFFECT_LABEL: Record<string, string> = {
  false_positive: '오탐',
  false_negative: '미탐',
  not_checked: '점검 누락',
  crash: '예외',
  wrong_logic: '판정 오류',
}
const EFFECT_BADGE: Record<string, string> = {
  false_positive: 'bad',
  false_negative: 'warn',
  not_checked: 'info',
  crash: 'accent',
  wrong_logic: '',
}

export function EffectBadge({ effect }: { effect: string }) {
  return <span className={`badge ${EFFECT_BADGE[effect] ?? ''}`}>{EFFECT_LABEL[effect] ?? effect}</span>
}

// 케이스 상태 — 변형(엔진) 하나에서 그 결함이 어떻게 나왔나
export const STATUS: Record<string, { label: string; cls: string; hint: string }> = {
  defect: { label: '결함 재현', cls: 'bad', hint: '이 엔진에서 결함 시나리오가 기대(올바른 결과)와 다르게 나온다' },
  collection_only: { label: '수집 결함', cls: 'warn', hint: '룰 판정은 맞지만 수집 데이터에서 정보가 사라져 실제로는 틀린다 — 수집 수정 + 재수집 필요' },
  ok: { label: '정상', cls: 'good', hint: '모든 시나리오가 기대대로 — 이 엔진에서는 결함이 없다' },
  improved: { label: '개선됨', cls: 'good', hint: '운영 엔진에서는 결함이 재현되고, 이 엔진에서는 기대대로 나온다' },
  case_broken: { label: '케이스 점검', cls: 'info', hint: '정상 입력(control) 시나리오가 기대와 다르다 — 케이스를 고쳐야 한다' },
  not_reproducible: { label: '재현 안 됨', cls: '', hint: '케이스 작성 중 결함이 재현되지 않았다 — 메모 참고' },
  no_case: { label: '케이스 없음', cls: '', hint: '아직 재현 케이스가 없다' },
  not_run: { label: '미실행', cls: '', hint: '이 엔진으로 케이스를 아직 돌리지 않았다' },
}

export function statusKey(status: string | null | undefined, hasCase: boolean, baseStatus?: string | null, isBase = true) {
  if (!hasCase) return 'no_case'
  if (!status) return 'not_run'
  if (!isBase && status === 'ok' && (baseStatus === 'defect' || baseStatus === 'collection_only')) return 'improved'
  return status
}

export function StatusBadge({ k }: { k: string }) {
  const s = STATUS[k] ?? { label: k, cls: '', hint: '' }
  return (
    <span className={`badge ${s.cls}`} title={s.hint}>
      {s.label}
    </span>
  )
}

const VERDICT: Record<string, [string, string]> = {
  Vuln: ['취약', 'bad'],
  Secure: ['양호', 'good'],
  'N/A': ['N/A', ''],
  ERROR: ['예외', 'accent'],
  MISSING: ['함수 없음', 'info'],
}
export function VerdictBadge({ v }: { v?: string | null }) {
  if (!v) return <span className="muted">—</span>
  const [label, cls] = VERDICT[v] ?? [v, '']
  return <span className={`badge ${cls}`}>{label}</span>
}

export function Counts({ r }: { r?: { checked?: number; flag?: number; good?: number; na?: number } | null }) {
  if (!r) return <span className="muted">—</span>
  return (
    <span className="mono small muted">
      점검 {r.checked ?? 0} · 취약 {r.flag ?? 0} · 양호 {r.good ?? 0}
      {r.na ? ` · N/A ${r.na}` : ''}
    </span>
  )
}

export function Json({ value, open = false, label = 'JSON' }: { value: unknown; open?: boolean; label?: string }) {
  return (
    <details open={open}>
      <summary>{label}</summary>
      <pre className="json">{JSON.stringify(value, null, 2)}</pre>
    </details>
  )
}

export function EffectBar({ counts, total }: { counts: Record<string, number>; total?: number }) {
  const t = total ?? Object.values(counts).reduce((a, b) => a + b, 0)
  return (
    <div className="bar" title={EFFECT_ORDER.map((e) => `${EFFECT_LABEL[e]} ${counts[e] ?? 0}`).join(' · ')}>
      {EFFECT_ORDER.map((e) =>
        counts[e] ? <span key={e} className={EFFECT_CLASS[e]} style={{ width: `${(counts[e] / t) * 100}%` }} /> : null,
      )}
    </div>
  )
}

export function JobLine({ job }: { job: Job | null }) {
  if (!job) return null
  return (
    <div className="row small">
      <span className={`badge ${job.status === 'error' ? 'bad' : job.status === 'done' ? 'good' : 'accent'}`}>
        {job.status === 'running' ? '진행 중' : job.status === 'done' ? '완료' : '실패'}
      </span>
      <span>{job.label}</span>
      {job.status === 'running' && (
        <div className="progress">
          <span style={{ width: `${Math.round(job.progress * 100)}%` }} />
        </div>
      )}
      <span className="muted">{job.message}</span>
      {job.error && <span className="diff">{job.error}</span>}
    </div>
  )
}

export function useAsync<T>(fn: () => Promise<T>, deps: unknown[]) {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [tick, setTick] = useState(0)
  useEffect(() => {
    let alive = true
    setLoading(true)
    fn()
      .then((d) => alive && (setData(d), setError(null)))
      .catch((e) => alive && setError(String(e.message ?? e)))
      .finally(() => alive && setLoading(false))
    return () => {
      alive = false
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick])
  return { data, error, loading, reload: () => setTick((t) => t + 1) }
}

export function Loading({ error, loading }: { error: string | null; loading: boolean }) {
  if (error) return <div className="err">{error}</div>
  if (loading) return <p className="muted">불러오는 중…</p>
  return null
}
