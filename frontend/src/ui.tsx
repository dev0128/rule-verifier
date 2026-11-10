import { useEffect, useRef, useState, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
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
// short = 범례에 쓰는 한 줄 뜻(화면에 그대로 보인다 — 툴팁에만 숨기지 않는다)
export const STATUS: Record<string, { label: string; cls: string; hint: string; short: string }> = {
  defect: { label: '결함 있음', cls: 'bad', short: '이 엔진이 결함 상황에서 틀리게 판정', hint: '결함이 드러나는 입력을 이 엔진으로 돌리면 올바른 결과와 다르게 나온다 — 아직 안 고쳐졌다' },
  no_fix: { label: '개선 로직 없음', cls: 'muted-badge', short: '이 엔진에 이 룰을 고친 코드가 없음 — 결과는 운영 엔진과 같음', hint: '이 엔진의 이 룰 코드(룰 함수 + 부르는 헬퍼)가 현재 운영 엔진과 같다 — 아직 아무도 안 고쳤다. 수집기(AWS/Raw) 수정은 보지 않는다' },
  improved: { label: '개선됨', cls: 'good', short: '운영 엔진은 틀리고 이 엔진은 맞게 판정', hint: '현재 운영 엔진에서는 틀리던 입력을 이 엔진은 올바르게 판정한다' },
  ok: { label: '결함 없음', cls: 'good', short: '이 엔진은 모든 입력을 맞게 판정', hint: '케이스의 모든 입력이 올바른 결과대로 나온다' },
  collection_only: { label: '수집 문제', cls: 'warn', short: '룰은 맞지만 수집기가 정보를 안 가져와 실제 결과는 틀림', hint: '룰 판정은 맞지만 수집 단계에서 정보가 빠져 실제 고객 결과는 틀린다 — 수집기 수정 + 재수집 필요' },
  case_broken: { label: '케이스 오류', cls: 'info', short: '정상 입력부터 틀림 — 케이스를 고쳐야 함', hint: '결함과 상관없는 정상 입력(control)이 올바른 결과와 다르다 — 결함이 아니라 케이스가 틀렸다' },
  not_reproducible: { label: '결함 확인 안 됨', cls: '', short: '케이스를 만들 때 결함이 실제로 나타나지 않음', hint: '케이스 작성 중 결함이 실제로 나타나지 않았다 — 메모 참고' },
  no_case: { label: '케이스 없음', cls: '', short: '아직 확인용 입력(케이스)이 없음', hint: '아직 재현 케이스가 없다' },
  not_run: { label: '아직 안 돌림', cls: '', short: '이 엔진으로 케이스를 아직 안 돌림', hint: '이 엔진으로 케이스를 아직 돌리지 않았다' },
}

/** 화면에 나온 상태들의 뜻 — 배지 옆에 한 줄로 */
export function StatusLegend({ keys }: { keys: string[] }) {
  const ks = [...new Set(keys)].filter((k) => STATUS[k])
  if (!ks.length) return null
  return (
    <div className="small muted" style={{ display: 'flex', flexWrap: 'wrap', gap: '4px 14px' }}>
      {ks.map((k) => <span key={k}><StatusBadge k={k} /> {STATUS[k].short}</span>)}
    </div>
  )
}

/** hasFix — 이 엔진에 그 결함의 룰을 고친 코드가 있나(서버 has_fix). false 면 운영과 같은 결과라 '결함 있음' 대신 '개선 로직 없음' */
export function statusKey(status: string | null | undefined, hasCase: boolean, baseStatus?: string | null, isBase = true, hasFix?: boolean | null) {
  if (!hasCase) return 'no_case'
  if (!status) return 'not_run'
  if (!isBase && status === 'ok' && (baseStatus === 'defect' || baseStatus === 'collection_only')) return 'improved'
  if (!isBase && hasFix === false && status === 'defect' && baseStatus === 'defect') return 'no_fix'
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

/** 판정 전이 칩 — '취약→양호'(올바른 결과 → 엔진 결과). 올바른 결과 쪽 색으로 무엇을 놓쳤는지 보이게 */
export function TransitionChip({ t }: { t: string }) {
  const [from, to] = t.split('→')
  const cls = to === undefined ? 'neutral' : to === '예외' ? 'bad' : from === '취약' ? 'warn' : to === '취약' ? 'bad' : 'info'
  return <span className={`badge ${cls === 'neutral' ? '' : cls}`} style={{ marginRight: 4 }}>{t}</span>
}

// ---------------------------------------------------------------- 용어 — 화면 라벨의 뜻(도움말 페이지 /help 와 배지 툴팁이 같이 쓴다)
/** 결함 유형 — 어디가 잘못됐나 · 룰만 고쳐서 바로잡히나 */
export const DEFECT_TYPE: Record<string, { label: string; cls: string; hint: string }> = {
  logic: { label: '룰 로직 오류', cls: 'accent', hint: '룰 함수의 판정 조건이 틀렸다 — 엔진 룰 수정으로 고친다' },
  collection: { label: '수집 누락', cls: 'warn', hint: '수집기가 판정에 필요한 정보를 안 가져온다 — raw 에 이미 정보가 없어서 룰만 고쳐서는 바로잡히지 않는다(수집기 수정 + 재수집)' },
  crash: { label: '룰 중단(예외)', cls: 'bad', hint: '특정 입력에서 룰이 예외로 멈춰 결과가 안 나온다' },
  args: { label: '인자 해석 오류', cls: 'info', hint: '컨디션 파일의 인자(기간 · 값)를 잘못 해석한다' },
}
/** 판정 영향 — 결과가 어느 쪽으로 틀리나 */
export const EFFECT_HINT: Record<string, string> = {
  false_positive: '안전한 리소스를 취약으로 판정',
  false_negative: '취약한 리소스를 양호로 놓침',
  not_checked: '점검해야 할 리소스가 점검 대상에서 빠짐',
  crash: '룰이 예외로 멈춰 결과가 없음',
  wrong_logic: '판정 · 건수 계산이 틀림',
}
/** 룰 결과 판정 — 엔진 결과(점검 · 취약 · 양호 · N/A 건수)에서 정한다(worker verdict_of) */
export const VERDICT_HELP: [string, string][] = [
  ['Vuln', '취약 리소스가 1개 이상'],
  ['Secure', '취약 없이 양호 리소스가 있음'],
  ['N/A', '점검한 리소스가 없음(대상 없음 · 해당 없음)'],
  ['ERROR', '룰이 실행 중 예외로 멈춤 — 결과 없음'],
  ['MISSING', '이 엔진에 그 룰 함수가 없음'],
]
/** 재현 케이스의 입력 종류 */
export const ROLE: Record<string, { label: string; cls: string; hint: string }> = {
  bug: { label: '결함 입력', cls: 'bad', hint: '결함이 드러나는 입력 — 결함이 있는 엔진이면 올바른 결과와 다르게 나온다' },
  control: { label: '정상 입력', cls: 'good', hint: '결함과 상관없는 평범한 입력 — 어느 엔진이든 맞아야 한다. 틀리면 케이스가 잘못된 것' },
  collection: { label: '수집 누락 입력', cls: 'warn', hint: '수집기가 정보를 빠뜨린 뒤의 raw — 룰은 맞게 판정하지만 실제 고객 결과는 틀린다' },
}
export const CONFIDENCE: Record<string, string> = { high: '확실', medium: '중간', low: '추정' }

/** 결과 칩(메인 그리드 '결과' 칼럼) */
export const CHIP_HELP: [string, string][] = [
  ['취약→양호', '올바른 결과는 취약인데 운영 엔진은 양호 — 화살표 왼쪽이 올바른 결과, 오른쪽이 엔진 결과'],
  ['양호→취약', '올바른 결과는 양호인데 엔진은 취약(오탐 쪽)'],
  ['취약(건수)', '판정은 맞지만 건수 · 리소스 목록이 틀림'],
]
/** 입력 실험 결과 표 */
export const COMPARE_HELP: [string, string, string][] = [
  ['비교 기준 (지금 운영 코드)', '현재 운영 엔진 행', '개선 전 결과. 수정 브랜치 결과를 이것과 비교한다'],
  ['개선으로 결과가 바뀜', '수정 브랜치 행', '개선 전과 다른 판정 · 건수 · 리소스. 알려진 결함 때문이면 의도한 변화, 아니면 개선이 다른 걸 망가뜨린 것(회귀)'],
  ['개선 전과 같음', '수정 브랜치 행', '개선 로직은 있지만 이 데이터에는 고친 결함이 걸리는 조건이 없다'],
  ['아직 개선 로직 없음', '수정 브랜치 행', '이 룰 코드가 운영 엔진과 같아 결과도 같다'],
  ['운영에 저장된 결과', '실데이터일 때', '그 진단에서 운영 엔진이 실제로 낸 결과(S3 Analyze)'],
  ['운영과 다름', '현재 운영 엔진 행', '같은 코드 · 같은 데이터인데 저장된 결과와 다르다 — 결함이 아니라 화면 실행 조건 문제(운영과 같은 순서로 실행 · 컨디션 파일 · 리전)'],
  ['틀리는 조건', '알려진 결함', '이 조건이 입력에 있으면 결함 있는 엔진은 틀리게 판정한다'],
]

/** 도움말 항목별 짧은 내용 — '?' 호버 카드. 전체 설명은 /help */
const HELP_TOPIC: Record<string, { title: string; rows: () => [ReactNode, string][] }> = {
  status: { title: '결함 상태 — 엔진마다 그 결함이 어떻게 나왔나', rows: () => ['defect', 'no_fix', 'improved', 'ok', 'collection_only', 'case_broken', 'not_reproducible', 'no_case', 'not_run'].map((k) => [<StatusBadge key={k} k={k} />, STATUS[k].short]) },
  type: {
    title: '어떤 결함 — 유형 · 판정 영향',
    rows: () => [
      ...Object.entries(DEFECT_TYPE).map(([k, t]) => [<span key={k} className={`badge ${t.cls}`}>{t.label}</span>, t.hint] as [ReactNode, string]),
      ...EFFECT_ORDER.map((k) => [<EffectBadge key={k} effect={k} />, EFFECT_HINT[k]] as [ReactNode, string]),
    ],
  },
  effect: { title: '판정 영향 — 결과가 어느 쪽으로 틀리나', rows: () => EFFECT_ORDER.map((k) => [<EffectBadge key={k} effect={k} />, EFFECT_HINT[k]]) },
  verdict: { title: '판정 — 룰 하나의 결과', rows: () => VERDICT_HELP.map(([v, h]) => [<VerdictBadge key={v} v={v} />, h]) },
  role: { title: '재현 케이스의 입력 종류', rows: () => Object.entries(ROLE).map(([k, r]) => [<span key={k} className={`badge ${r.cls}`}>{r.label}</span>, r.hint]) },
  chip: { title: '결과 칩 — 올바른 결과 → 엔진 결과', rows: () => CHIP_HELP.map(([t, h]) => [<TransitionChip key={t} t={t} />, h]) },
  compare: { title: '입력 실험 결과 표', rows: () => COMPARE_HELP.map(([t, w, h]) => [<b key={t}>{t}</b>, `${w} — ${h}`]) },
}

/** 라벨 옆 '?' — 마우스를 올리면 그 자리에서 뜻을 보이고, 누르면 도움말 페이지의 그 항목으로 */
export function HelpLink({ to }: { to: string; title?: string }) {
  const [pos, setPos] = useState<{ left: number; top?: number; bottom?: number } | null>(null)
  const ref = useRef<HTMLAnchorElement>(null)
  const timer = useRef<number | undefined>(undefined)
  const topic = HELP_TOPIC[to]
  const W = 460
  const show = () => {
    window.clearTimeout(timer.current)
    const r = ref.current?.getBoundingClientRect()
    if (!r) return
    const left = Math.max(8, Math.min(r.left - 12, document.documentElement.clientWidth - W - 8))
    // 아래 공간이 모자라면 '?' 위로 띄운다
    const up = r.bottom + 330 > window.innerHeight && r.top > 340
    setPos(up ? { left, bottom: window.innerHeight - r.top + 6 } : { left, top: r.bottom + 6 })
  }
  const hide = () => {
    window.clearTimeout(timer.current)
    timer.current = window.setTimeout(() => setPos(null), 150)
  }
  useEffect(() => () => window.clearTimeout(timer.current), [])
  return (
    <span style={{ display: 'inline-block' }} onMouseEnter={show} onMouseLeave={hide}>
      <Link ref={ref} to={`/help#${to}`} className="help-link" onClick={(e) => e.stopPropagation()} onFocus={show} onBlur={hide} aria-label="용어 뜻">?</Link>
      {pos && topic && (
        <div className="help-pop" role="tooltip"
          style={{ left: pos.left, width: W, top: pos.top, bottom: pos.bottom }}>
          <div className="help-pop-title">{topic.title}</div>
          <table>
            <tbody>
              {topic.rows().map(([l, h], i) => (
                <tr key={i}><td>{l}</td><td>{h}</td></tr>
              ))}
            </tbody>
          </table>
          <div className="help-pop-foot">누르면 용어 도움말 페이지로</div>
        </div>
      )}
    </span>
  )
}
