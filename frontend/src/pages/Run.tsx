import { Fragment, useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api, type RuleResult } from '../api'
import { Counts, EffectBadge, Loading, VerdictBadge, useAsync } from '../ui'

type Change = { changed: boolean; verdict: [string, string] | null; to_flag_n?: number; to_good_n?: number; left_flag_n?: number; left_good_n?: number; error_fixed: boolean; error_new: boolean; to_flag?: string[]; to_good?: string[]; left_flag?: string[]; left_good?: string[] }
type Row = {
  rule: string
  code: string
  name: string
  category: string
  level: string
  args: unknown
  findings: { id: string; effect: string; summary: string }[]
  variants: Record<string, RuleResult | null>
  changes: Record<string, Change>
  production?: RuleResult | null
  matches_production?: boolean
}
type RunDoc = {
  id: string
  created: string
  diag: string
  ruleset: string
  ruleset_name?: string
  args_override: string
  as_of?: string | null
  base: string
  variant_ids: string[]
  variants: Record<string, { describe: { label: string; engine?: { ref: string; sha?: string } }; skipped: { rule: string; reason: string }[]; enabled_rules: number }>
  summary: {
    variants: Record<string, { label: string; verdicts: Record<string, number>; rules: number; errors: number; sec: number; changed_rules?: number; preprocess: string[]; overlay_rules: number }>
    production: { available: boolean; rules?: number; same?: number; different?: string[] }
  }
  rules: Row[]
}

function Ids({ title, ids }: { title: string; ids?: string[] }) {
  if (!ids?.length) return null
  return (
    <div style={{ marginBottom: 6 }}>
      <div className="small muted">{title} ({ids.length})</div>
      <div className="mono small" style={{ maxHeight: 160, overflow: 'auto' }}>{ids.map((i) => <div key={i}>{i}</div>)}</div>
    </div>
  )
}

function RuleDetail({ runId, row, doc }: { runId: string; row: Row; doc: RunDoc }) {
  const d = useAsync(() => api.get<Row>(`/api/runs/${runId}/rules/${row.rule}`), [runId, row.rule])
  if (!d.data) return <Loading error={d.error} loading />
  const full = d.data
  return (
    <div style={{ padding: '6px 4px' }}>
      {full.findings.length > 0 && (
        <div style={{ marginBottom: 10 }}>
          <div className="small muted">이 룰의 알려진 결함</div>
          {full.findings.map((f) => (
            <div key={f.id} className="small">
              <Link to={`/findings/${f.id}`} className="mono">{f.id}</Link> <EffectBadge effect={f.effect} /> {f.summary}
            </div>
          ))}
        </div>
      )}
      <div className="grid" style={{ gridTemplateColumns: `repeat(${doc.variant_ids.length + (full.production ? 1 : 0)}, minmax(220px, 1fr))` }}>
        {full.production && (
          <div>
            <h3 style={{ marginTop: 0 }}>운영 실제 결과</h3>
            <Ids title="취약" ids={full.production.flag_ids} />
            <Ids title="양호" ids={full.production.good_ids} />
          </div>
        )}
        {doc.variant_ids.map((vid) => {
          const r = full.variants[vid]
          const ch = full.changes[vid]
          return (
            <div key={vid}>
              <h3 style={{ marginTop: 0 }}>{doc.variants[vid].describe.label}</h3>
              {r?.error && <div className="err small">{r.error.type}: {r.error.message}<br /><span className="mono">{r.error.where}</span></div>}
              {ch ? (
                <>
                  <Ids title="새로 취약" ids={ch.to_flag} />
                  <Ids title="취약에서 빠짐" ids={ch.left_flag} />
                  <Ids title="새로 양호" ids={ch.to_good} />
                  <Ids title="양호에서 빠짐" ids={ch.left_good} />
                  {!ch.changed && <p className="muted small">기준 엔진과 같다</p>}
                </>
              ) : (
                <>
                  <Ids title="취약" ids={r?.flag_ids} />
                  <Ids title="양호" ids={r?.good_ids} />
                  <Ids title="N/A" ids={r?.na_ids} />
                </>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}

export default function Run() {
  const { id = '' } = useParams()
  const d = useAsync(() => api.get<RunDoc>(`/api/runs/${id}`), [id])
  const [filter, setFilter] = useState('')
  const [q, setQ] = useState('')
  const [open, setOpen] = useState<string | null>(null)

  const rows = useMemo(() => {
    if (!d.data) return []
    const other = d.data.variant_ids.slice(1)
    const ql = q.toLowerCase()
    return d.data.rules.filter((r) => {
      if (filter === 'changed' && !other.some((v) => r.changes[v]?.changed)) return false
      if (filter === 'findings' && !r.findings.length) return false
      if (filter === 'prod' && (r.production === undefined || r.matches_production)) return false
      if (filter === 'error' && !Object.values(r.variants).some((x) => x?.error)) return false
      if (filter === 'na' && r.variants[d.data!.base]?.verdict !== 'N/A') return false
      if (ql && !`${r.code} ${r.name} ${r.rule}`.toLowerCase().includes(ql)) return false
      return true
    })
  }, [d.data, filter, q])

  if (!d.data) return <Loading error={d.error} loading />
  const doc = d.data
  const prod = doc.summary.production
  const other = doc.variant_ids.slice(1)

  return (
    <>
      <p className="small"><Link to="/diagnoses">← 실데이터 실행</Link></p>
      <h1>실행 결과 <span className="mono muted" style={{ fontSize: 14 }}>{doc.id}</span></h1>
      <div className="sub">
        진단 <span className="mono">{doc.diag}</span> · 컨디션 파일 <span className="mono">{doc.ruleset}</span> {doc.ruleset_name && `(${doc.ruleset_name})`} · 인자{' '}
        {doc.args_override || '그대로'} · 기준 시각 {doc.as_of ?? '실행 시각'}
      </div>

      <div className="grid kpis">
        {prod.available && (
          <div className="card kpi">
            <div className="label">운영 실제 결과와 일치 (기준 엔진)</div>
            <div className="value" style={{ color: prod.same === prod.rules ? 'var(--good)' : 'var(--warn)' }}>{prod.same}/{prod.rules}</div>
            <div className="hint">{prod.different?.length ? `다름: ${prod.different.slice(0, 6).join(', ')}${prod.different.length > 6 ? '…' : ''}` : '건수 · 취약 리소스 목록까지 같다'}</div>
          </div>
        )}
        {doc.variant_ids.map((vid) => {
          const s = doc.summary.variants[vid]
          return (
            <div key={vid} className="card kpi">
              <div className="label">{s.label} <span className="mono">{doc.variants[vid].describe.engine?.sha}</span></div>
              <div className="value">{s.changed_rules != null ? <>변경 {s.changed_rules}</> : <>룰 {s.rules}</>}</div>
              <div className="hint">
                취약 {s.verdicts.Vuln ?? 0} · 양호 {s.verdicts.Secure ?? 0} · N/A {s.verdicts['N/A'] ?? 0} · 예외 {s.errors} · {s.sec}s
                {s.overlay_rules > 0 && ` · 수정 룰 ${s.overlay_rules}`}
                {s.preprocess.length > 0 && ` · 수집 보정 ${s.preprocess.length}`}
              </div>
            </div>
          )
        })}
      </div>
      {doc.variants[doc.base].skipped.length > 0 && (
        <p className="muted small">실행하지 않은 룰 {doc.variants[doc.base].skipped.length}개 — {doc.variants[doc.base].skipped[0].reason}</p>
      )}

      <div className="row" style={{ margin: '16px 0 10px' }}>
        <input type="search" placeholder="룰 코드 · 항목명" value={q} onChange={(e) => setQ(e.target.value)} />
        <select value={filter} onChange={(e) => setFilter(e.target.value)}>
          <option value="">전체 룰</option>
          {other.length > 0 && <option value="changed">엔진끼리 결과가 다른 룰</option>}
          <option value="findings">알려진 결함이 있는 룰</option>
          {prod.available && <option value="prod">운영 결과와 다른 룰</option>}
          <option value="error">예외가 난 룰</option>
          <option value="na">기준 엔진에서 N/A</option>
        </select>
        <span className="muted small">{rows.length}개</span>
      </div>
      <div className="table-wrap" style={{ maxHeight: '72vh' }}>
        <table>
          <thead>
            <tr>
              <th>룰</th>
              <th>항목명</th>
              <th>인자</th>
              <th>결함</th>
              {prod.available && <th>운영 결과</th>}
              {doc.variant_ids.map((v) => <th key={v}>{doc.variants[v].describe.label}</th>)}
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => {
              const changed = other.some((v) => r.changes[v]?.changed)
              return (
                <Fragment key={r.rule}>
                  <tr className="click" onClick={() => setOpen(open === r.rule ? null : r.rule)} style={changed ? { boxShadow: 'inset 3px 0 0 var(--accent)' } : undefined}>
                    <td className="mono nowrap">{r.code}<div className="muted small">{r.level}</div></td>
                    <td style={{ minWidth: 200 }}>{r.name}</td>
                    <td className="mono small">{JSON.stringify(r.args ?? null)}</td>
                    <td className="nowrap">{r.findings.length > 0 && <span className="badge warn" title={r.findings.map((f) => `${f.id} ${f.summary}`).join('\n')}>{r.findings.length}건</span>}</td>
                    {prod.available && (
                      <td className="nowrap">
                        <VerdictBadge v={r.production?.verdict} />
                        {r.production && !r.matches_production && <span className="badge info" style={{ marginLeft: 4 }}>다름</span>}
                      </td>
                    )}
                    {doc.variant_ids.map((v) => {
                      const x = r.variants[v]
                      const ch = r.changes[v]
                      return (
                        <td key={v} className="nowrap">
                          <VerdictBadge v={x?.verdict} /> {x?.overlay && <span className="badge accent">수정 룰</span>}
                          <div><Counts r={x} /></div>
                          {ch?.changed && (
                            <div className="small" style={{ color: 'var(--accent)' }}>
                              {ch.verdict ? `${ch.verdict[0]} → ${ch.verdict[1]} ` : ''}
                              {ch.to_flag_n ? `+취약 ${ch.to_flag_n} ` : ''}
                              {ch.left_flag_n ? `−취약 ${ch.left_flag_n} ` : ''}
                              {ch.to_good_n ? `+양호 ${ch.to_good_n} ` : ''}
                              {ch.error_fixed ? '예외 해소' : ''}
                              {ch.error_new ? '새 예외' : ''}
                            </div>
                          )}
                          {x?.error && <div className="diff small">{x.error.type}</div>}
                        </td>
                      )
                    })}
                  </tr>
                  {open === r.rule && (
                    <tr>
                      <td colSpan={5 + doc.variant_ids.length} style={{ background: 'var(--surface-2)' }}>
                        <RuleDetail runId={doc.id} row={r} doc={doc} />
                      </td>
                    </tr>
                  )}
                </Fragment>
              )
            })}
          </tbody>
        </table>
      </div>
    </>
  )
}
