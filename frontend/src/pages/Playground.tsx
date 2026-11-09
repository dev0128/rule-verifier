import { useState } from 'react'
import { api, type RuleResult, type Variant } from '../api'
import { Counts, Json, Loading, VerdictBadge, useAsync } from '../ui'

type Saved = { rule: string; service?: string; args: unknown; raw: unknown; from?: string; expect?: unknown }

function load(): Saved {
  try {
    const s = sessionStorage.getItem('rv-playground')
    if (s) return JSON.parse(s)
  } catch {
    /* 없음 */
  }
  return {
    rule: 'REME-0103600001',
    service: 'guardduty',
    args: [],
    raw: { 'ap-northeast-2': { guardduty: { get_detector: [{ DetectorId: 'd1', Status: 'DISABLED' }] } } },
  }
}

export default function Playground() {
  const init = load()
  const vs = useAsync(() => api.get<Variant[]>('/api/variants'), [])
  const [rule, setRule] = useState(init.rule)
  const [service, setService] = useState(init.service ?? '')
  const [args, setArgs] = useState(JSON.stringify(init.args ?? null))
  const [raw, setRaw] = useState(JSON.stringify(init.raw, null, 2))
  const [out, setOut] = useState<Record<string, RuleResult> | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const run = async () => {
    setErr(null)
    let a: unknown, r: Record<string, unknown>
    try {
      a = JSON.parse(args)
      r = JSON.parse(raw)
    } catch (e) {
      setErr(`JSON 형식 오류: ${(e as Error).message}`)
      return
    }
    setBusy(true)
    try {
      setOut(await api.post<Record<string, RuleResult>>('/api/playground', { rule, service: service || null, args: a, raw: r }))
    } catch (e) {
      setErr(String((e as Error).message))
    } finally {
      setBusy(false)
    }
  }

  if (!vs.data) return <Loading error={vs.error} loading />
  return (
    <>
      <h1>입력 실험</h1>
      <div className="sub">
        룰 하나에 컨디션(인자)과 raw 를 직접 넣어 엔진 변형마다 돌린다. 케이스 화면의 “입력 실험으로 열기”로 시나리오를 가져와 고쳐 볼 수 있다.
        {init.from && <> 가져온 시나리오: <span className="mono">{init.from}</span></>}
      </div>
      <div className="card">
        <div className="row">
          <label className="inline">룰 <input value={rule} onChange={(e) => setRule(e.target.value)} className="mono" style={{ width: 170 }} /></label>
          <label className="inline">service_name <input value={service} onChange={(e) => setService(e.target.value)} placeholder="비우면 룰에서 찾음" className="mono" style={{ width: 150 }} /></label>
          <label className="inline">args <input value={args} onChange={(e) => setArgs(e.target.value)} className="mono" style={{ width: 160 }} title='기본 룰셋 ["90"] · 거버넌스 "" · 커스텀룰 참조 null' /></label>
          <div className="spacer" />
          <button className="primary" onClick={run} disabled={busy}>{busy ? '실행 중…' : '실행'}</button>
        </div>
        <p className="muted small">args 모양 — 기본 룰셋 <code>["90"]</code> 또는 <code>[]</code> · 거버넌스 기본 룰 <code>""</code> · 커스텀룰 마스터 참조 <code>null</code></p>
        <textarea rows={18} value={raw} onChange={(e) => setRaw(e.target.value)} spellCheck={false} />
        {init.expect != null && <Json value={init.expect} label="원래 시나리오의 올바른 결과(expect)" />}
      </div>
      {err && <div className="err" style={{ marginTop: 10 }}>{err}</div>}
      {out && (
        <div className="table-wrap" style={{ marginTop: 12 }}>
          <table>
            <thead>
              <tr><th>엔진</th><th>판정</th><th>건수</th><th>취약 리소스</th><th>예외</th></tr>
            </thead>
            <tbody>
              {vs.data.map((v) => {
                const r = out[v.id]
                return (
                  <tr key={v.id}>
                    <td className="nowrap">{v.label}{r?.overlay && <span className="badge accent" style={{ marginLeft: 6 }}>수정 룰</span>}</td>
                    <td><VerdictBadge v={r?.verdict} /></td>
                    <td><Counts r={r} /></td>
                    <td className="mono small">{(r?.flag_ids ?? []).join(', ') || '—'}</td>
                    <td className="small">{r?.error ? <span className="diff">{r.error.type}: {r.error.message}<br /><span className="mono muted">{r.error.where}</span></span> : '—'}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </>
  )
}
