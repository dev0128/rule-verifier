import { useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { api, type Case, type CaseResult, type FindingRow, type Scenario, type Variant } from '../api'
import { Counts, EffectBadge, Json, Loading, StatusBadge, VerdictBadge, statusKey, useAsync } from '../ui'

type FindingDetail = FindingRow & { trigger?: string; evidence?: string; reproduced_in_spike?: string }
type Detail = {
  finding: FindingDetail
  rules_meta: Record<string, { code: string; name: string; category: string; report_lv: string } | null>
  case: Case | null
  results: Record<string, CaseResult>
}

const ROLE: Record<string, [string, string]> = {
  bug: ['결함 입력', 'bad'],
  control: ['정상 입력', 'good'],
  collection: ['수집 결함', 'warn'],
}

function expectText(e: Record<string, unknown>) {
  const parts: string[] = []
  if (e.verdict) parts.push(`판정 ${({ Vuln: '취약', Secure: '양호', 'N/A': 'N/A', ERROR: '예외' } as Record<string, string>)[e.verdict as string] ?? e.verdict}`)
  for (const [k, l] of [['checked', '점검'], ['flag', '취약'], ['good', '양호'], ['na', 'N/A']] as const) if (k in e) parts.push(`${l} ${e[k]}`)
  for (const k of ['flag_contains', 'good_contains', 'na_contains', 'flag_excludes'])
    if (Array.isArray(e[k]) && (e[k] as string[]).length) parts.push(`${k}: ${(e[k] as string[]).join(', ')}`)
  return parts.join(' · ')
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
      JSON.stringify({ rule: s.rule ?? c?.rule, service: s.service ?? c?.service, args: s.args ?? null, raw: s.raw ?? {}, from: `${id} · ${s.id}`, expect: s.expect }),
    )
    nav('/playground')
  }

  return (
    <>
      <p className="small"><Link to="/">← 결함 검증 현황</Link></p>
      <div className="row">
        <h1>
          <span className="mono">{f.id}</span> · {f.codes.join(', ')}
        </h1>
        <EffectBadge effect={f.effect} />
        <span className="badge">{f.level}</span>
        <span className="badge">{f.type}</span>
        <div className="spacer" />
        {c && (
          <button className="primary" onClick={rerun} disabled={running}>
            {running ? '실행 중…' : '지금 다시 실행'}
          </button>
        )}
      </div>
      <div className="sub">{f.name}</div>
      {err && <div className="err">{err}</div>}

      <div className="grid" style={{ gridTemplateColumns: 'minmax(300px, 3fr) minmax(240px, 2fr)' }}>
        <div className="card">
          <div className="kv">
            <div>결함</div>
            <div>{f.summary}</div>
            {f.trigger && (<><div>발생 조건</div><div>{f.trigger}</div></>)}
            <div>영향</div>
            <div>{f.impact}</div>
            {f.evidence && (<><div>근거 코드</div><div className="mono small">{f.evidence}</div></>)}
            {c?.note && (<><div>케이스 메모</div><div className="small">{c.note}</div></>)}
            <div>출처</div>
            <div className="small">
              {f.source} · 신뢰도 {f.confidence || '—'}
              {f.reproduced_in_spike ? ` · 스파이크 재현: ${f.reproduced_in_spike}` : ''}
            </div>
          </div>
        </div>
        <div className="card">
          <h3 style={{ marginTop: 0 }}>엔진별 결과</h3>
          {variants.map((v, i) => (
            <div key={v.id} className="row" style={{ marginBottom: 6 }}>
              <span style={{ width: 110 }}>{v.label}</span>
              <StatusBadge k={statusKey(results[v.id]?.status, !!c, results[base]?.status, i === 0)} />
              {live && <span className="muted small">방금 실행</span>}
            </div>
          ))}
          <h3>룰</h3>
          {Object.entries(d.data.rules_meta).map(([r, m]) => (
            <div key={r} className="small">
              <span className="mono">{r}</span> {m?.code} — {m?.name}
            </div>
          ))}
        </div>
      </div>

      <h2>시나리오 — 입력(컨디션) 과 결과</h2>
      {!c && <p className="muted">재현 케이스가 없다.</p>}
      {c?.scenarios.length === 0 && <p className="muted">시나리오 없음 — 메모 참고.</p>}
      {c?.scenarios.map((s) => (
        <div key={s.id} className="card" style={{ marginBottom: 12 }}>
          <div className="row">
            <span className={`badge ${ROLE[s.role]?.[1] ?? ''}`}>{ROLE[s.role]?.[0] ?? s.role}</span>
            <strong>{s.condition}</strong>
            <div className="spacer" />
            <button onClick={() => openPlayground(s)}>입력 실험으로 열기</button>
          </div>
          <div className="kv small" style={{ marginTop: 8 }}>
            <div>룰 · 인자</div>
            <div className="mono">
              {s.rule ?? c.rule} · args={JSON.stringify(s.args ?? null)}
            </div>
            <div>올바른 결과</div>
            <div>{expectText(s.expect)}</div>
            {s.why && (<><div>근거</div><div>{s.why}</div></>)}
          </div>
          <div className="table-wrap" style={{ marginTop: 10 }}>
            <table>
              <thead>
                <tr>
                  <th>엔진</th>
                  <th>판정</th>
                  <th>건수</th>
                  <th>기대와 비교</th>
                </tr>
              </thead>
              <tbody>
                {variants.map((v) => {
                  const r = results[v.id]?.scenarios?.[s.id]
                  return (
                    <tr key={v.id}>
                      <td className="nowrap">
                        {v.label}
                        {r?.actual?.overlay && <span className="badge accent" style={{ marginLeft: 6 }}>수정 룰</span>}
                      </td>
                      <td><VerdictBadge v={r?.actual?.verdict} /></td>
                      <td><Counts r={r?.actual} /></td>
                      <td>
                        {!r ? (
                          <span className="muted">미실행</span>
                        ) : r.ok ? (
                          <span className="ok">기대대로</span>
                        ) : (
                          r.diffs.map((x, i) => <div key={i} className="diff">{x}</div>)
                        )}
                        {r?.actual?.error?.where && <div className="mono small muted">{r.actual.error.where}</div>}
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
      ))}
    </>
  )
}
