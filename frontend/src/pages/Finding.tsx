import { useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { api, type Case, type CaseResult, type FindingRow, type Scenario, type Variant } from '../api'
import { Counts, EffectBadge, HelpLink, Json, Loading, ROLE, StatusBadge, TransitionChip, VerdictBadge, statusKey, useAsync } from '../ui'

type FindingDetail = FindingRow & { trigger?: string; evidence?: string; reproduced_in_spike?: string }
type Detail = {
  finding: FindingDetail
  rules_meta: Record<string, { code: string; name: string; category: string; report_lv: string } | null>
  case: Case | null
  results: Record<string, CaseResult>
}


function expectText(e: Record<string, unknown>) {
  const parts: string[] = []
  if (e.verdict) parts.push(`판정 ${({ Vuln: '취약', Secure: '양호', 'N/A': 'N/A', ERROR: '예외' } as Record<string, string>)[e.verdict as string] ?? e.verdict}`)
  for (const [k, l] of [['checked', '점검'], ['flag', '취약'], ['good', '양호'], ['na', 'N/A']] as const) if (k in e) parts.push(`${l} ${e[k]}`)
  for (const k of ['flag_contains', 'good_contains', 'na_contains', 'flag_excludes'])
    if (Array.isArray(e[k]) && (e[k] as string[]).length) parts.push(`${k}: ${(e[k] as string[]).join(', ')}`)
  return parts.join(' · ')
}

const VKO: Record<string, string> = { Vuln: '취약', Secure: '양호', 'N/A': 'N/A', ERROR: '예외' }

/** 기대와 다르게 나온 결함 시나리오의 판정 전이 — 메인 그리드 '결과' 칩과 같은 규칙 */
function transitions(c: Case | null, r: CaseResult | undefined): string[] {
  const out = new Set<string>()
  for (const s of c?.scenarios ?? []) {
    const sr = r?.scenarios?.[s.id]
    if (!sr || s.role === 'control' || sr.ok) continue
    const e = s.expect.verdict as string | undefined
    const a = sr.actual?.verdict as string | undefined
    out.add(e && e !== a ? `${VKO[e] ?? e}→${VKO[a ?? ''] ?? a}` : `${VKO[a ?? ''] ?? a}(건수)`)
  }
  return [...out].sort()
}

/** 올바른 결과 행과 다른 칸만 강조 */
const hit = (on: boolean) => (on ? { background: 'var(--bad-soft)' } : undefined)

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div style={{ marginBottom: 14 }}>
      <div className="small muted" style={{ fontWeight: 600, marginBottom: 4 }}>{title}</div>
      <div>{children}</div>
    </div>
  )
}

export default function FindingPage() {
  const { id = '' } = useParams()
  const nav = useNavigate()
  const d = useAsync(() => api.get<Detail>(`/api/findings/${id}`), [id])
  const vs = useAsync(() => api.get<Variant[]>('/api/variants'), [])
  const [live, setLive] = useState<Record<string, CaseResult> | null>(null)
  const [running, setRunning] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  if (!d.data || !vs.data) return <Loading error={d.error || vs.error} loading />
  const { finding: f, case: c } = d.data
  const results = live ?? d.data.results
  const variants = vs.data
  const base = variants[0]?.id

  const rerun = async () => {
    setRunning(true)
    setErr(null)
    try {
      setLive(await api.post<Record<string, CaseResult>>(`/api/findings/${id}/run`))
    } catch (e) {
      setErr(String((e as Error).message))
    } finally {
      setRunning(false)
    }
  }

  const openPlayground = (s: Scenario) => {
    sessionStorage.setItem(
      'rv-playground',
      JSON.stringify({ rule: s.rule ?? c?.rule, service: s.service ?? c?.service, args: s.args ?? null, raw: s.raw ?? {}, from: `${id} · ${s.id}` }),
    )
    nav('/playground')
  }

  return (
    <>
      <p className="small"><Link to="/">← 결함 검증 현황</Link></p>
      <div className="row" style={{ alignItems: 'flex-start' }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div className="row" style={{ gap: 8 }}>
            <span className="mono muted">{f.id}</span>
            <span className="mono" style={{ fontWeight: 700 }}>{f.codes.join(', ')}</span>
            <span className="muted">{f.name}</span>
            <EffectBadge effect={f.effect} />
            <span className="badge">{f.level}</span>
          </div>
          <h1 style={{ fontSize: 22, margin: '8px 0 6px' }}>{f.outcome || f.summary}</h1>
          <div className="row" style={{ gap: 6 }}>
            {variants.map((v, i) => {
              const t = transitions(c, results[v.id])
              return (
                <span key={v.id} className="row small" style={{ gap: 4 }}>
                  <span className="muted">{v.label}</span>
                  <StatusBadge k={statusKey(results[v.id]?.status, !!c, results[base]?.status, i === 0, f.has_fix?.[v.id])} />
                  {t.map((x) => <TransitionChip key={x} t={x} />)}
                  {i < variants.length - 1 && <span className="muted" style={{ margin: '0 6px' }}>|</span>}
                </span>
              )
            })}
            <HelpLink to="status" title="결함 있음 · 개선됨 · 개선 로직 없음 … 뜻" />
            {live && <span className="muted small">방금 실행</span>}
          </div>
        </div>
        {c && (
          <button className="primary" onClick={rerun} disabled={running}>
            {running ? '실행 중…' : '지금 다시 실행'}
          </button>
        )}
      </div>
      {err && <div className="err" style={{ marginTop: 8 }}>{err}</div>}

      <div className="grid finding-grid" style={{ marginTop: 14, alignItems: 'start' }}>
        <div className="card">
          <Section title="결함">{f.summary}</Section>
          {f.trigger && <Section title="발생 조건">{f.trigger}</Section>}
          <Section title="영향">{f.impact}</Section>
          {f.evidence && (
            <Section title="근거 코드">
              <pre className="json" style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word', margin: 0 }}>{f.evidence}</pre>
            </Section>
          )}
          {c?.note && <Section title="케이스 메모"><span className="small">{c.note}</span></Section>}
        </div>
        <div className="card">
          <Section title="룰">
            {Object.entries(d.data.rules_meta).map(([r, m]) => (
              <div key={r} className="small" style={{ marginBottom: 6 }}>
                <div><span className="mono">{m?.code ?? r}</span> {m?.name}</div>
                <div className="mono muted">{r}</div>
                <Link to={`/apiref?rule=${r}`}>AWS API · 응답 구조 →</Link>
              </div>
            ))}
          </Section>
          <Section title="출처">
            <span className="small">{f.source} · 신뢰도 {f.confidence || '—'} · {f.type}</span>
          </Section>
          {f.reproduced_in_spike && (
            <Section title="스파이크 재현">
              <span className="small" style={{ wordBreak: 'break-word' }}>{f.reproduced_in_spike}</span>
            </Section>
          )}
        </div>
      </div>

      <h2>시나리오 — 이 입력이면 이 결과가 맞다 ({c?.scenarios.length ?? 0})</h2>
      {!c && <p className="muted">재현 케이스가 없다.</p>}
      {c?.scenarios.length === 0 && <p className="muted">시나리오 없음 — 메모 참고.</p>}
      {c?.scenarios.map((s) => {
        const e = s.expect as Record<string, unknown>
        return (
          <div key={s.id} className="card" style={{ marginBottom: 12 }}>
            <div className="row" style={{ alignItems: 'flex-start' }}>
              <span className={`badge ${ROLE[s.role]?.cls ?? ''}`} title={ROLE[s.role]?.hint}>{ROLE[s.role]?.label ?? s.role}</span><HelpLink to="role" title="결함 입력 · 정상 입력 · 수집 누락 입력 뜻" />
              <strong style={{ flex: 1, minWidth: 0 }}>{s.condition}</strong>
              <button onClick={() => openPlayground(s)}>입력 실험으로 열기</button>
            </div>
            {s.why && <p className="small muted" style={{ margin: '6px 0 0' }}>{s.why}</p>}
            <div className="table-wrap" style={{ marginTop: 10 }}>
              <table style={{ tableLayout: 'fixed', minWidth: 560 }}>
                <colgroup><col style={{ width: 150 }} /><col style={{ width: 80 }} /><col style={{ width: '34%' }} /><col /></colgroup>
                <thead>
                  <tr>
                    <th></th>
                    <th>판정</th>
                    <th>건수</th>
                    <th>올바른 결과와 다른 점</th>
                  </tr>
                </thead>
                <tbody>
                  <tr style={{ background: 'var(--good-soft)' }}>
                    <td className="nowrap"><b>올바른 결과</b></td>
                    <td>{e.verdict ? <VerdictBadge v={e.verdict as string} /> : '—'}</td>
                    <td className="mono small">{expectText(e).replace(/^판정 [^·]+ · ?/, '') || '—'}</td>
                    <td className="small muted">args={JSON.stringify(s.args ?? null)}{s.rule && s.rule !== c.rule ? ` · ${s.rule}` : ''}</td>
                  </tr>
                  {variants.map((v) => {
                    const r = results[v.id]?.scenarios?.[s.id]
                    const a = r?.actual
                    const vbad = !!r && !!e.verdict && a?.verdict !== e.verdict
                    const cbad = !!r && (['checked', 'flag', 'good', 'na'] as const).some((k) => k in e && (a as Record<string, unknown> | undefined)?.[k] !== e[k])
                    return (
                      <tr key={v.id}>
                        <td className="nowrap">
                          {v.label}
                          {a?.overlay && <span className="badge accent" style={{ marginLeft: 6 }}>수정 룰</span>}
                        </td>
                        <td style={hit(vbad)}><VerdictBadge v={a?.verdict} /></td>
                        <td style={hit(cbad)}><Counts r={a} /></td>
                        <td>
                          {!r ? (
                            <span className="muted">미실행</span>
                          ) : r.ok ? (
                            <span className="ok">맞음</span>
                          ) : (
                            r.diffs.map((x, i) => <div key={i} className="diff">{x}</div>)
                          )}
                          {a?.error?.where && <div className="mono small muted">{a.error.where}</div>}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
            <div style={{ marginTop: 8 }}>
              <Json value={s.raw} label="입력 raw (json_given.raw)" />
            </div>
          </div>
        )
      })}
    </>
  )
}
