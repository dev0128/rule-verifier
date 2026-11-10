import { Fragment, useEffect, useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { api } from '../api'
import { Loading, useAsync } from '../ui'

type OpSummary = {
  service: string; operation: string; method: string; urls: { aws?: string; boto3: string }; paginated: boolean
  raw_keys: string[]; rules: string[]; added_in_latest: number; doc: string
}
type RuleRef = {
  file: string; line: number; service: string | null; raw_service: string; code: string | null; name: string | null
  raw_keys: { service: string; key: string }[]; fields_read: string[]; operations: string[]; unknown_fields: string[]; documented_extra: string[]
}
type RawRef = { ops: string[]; functions: { file: string; function: string; line: number }[]; attach_keys: string[] }
type Index = {
  meta: { generated_at: string; engine_ref: string; engine_sha: string | null; botocore: string; latest_source: string; latest_errors: Record<string, string>; counts: Record<string, number> }
  raw: Record<string, Record<string, RawRef>>
  rules: Record<string, RuleRef>
  operations: Record<string, OpSummary>
  collector_unknown: { file: string; function: string; line: number; raw_service: string; raw_keys: string[]; unknown_fields: string[] }[]
  documented_extra: Record<string, { doc: string; columns: string[] }>
  other_source_keys: Record<string, string>
}
type Node = {
  type: string; doc?: string; enum?: string[]; required?: boolean; ref?: string
  members?: Record<string, Node>; item?: Node; key?: Node; value?: Node
}
type OpDetail = OpSummary & { doc: string; input_required: string[]; output: Node | null; added_in_latest: string[] }

/** 응답 트리 — 룰이 읽는 필드는 강조, 최신 botocore 에만 있는 필드는 따로 표시 */
function Tree({ name, node, path, hl, depth = 0 }: { name: string; node: Node; path: string; hl: Set<string>; depth?: number }) {
  const children: [string, Node, string][] = node.members
    ? Object.entries(node.members).map(([k, v]) => [k, v, path ? `${path}.${k}` : k])
    : node.item ? [['[]', node.item, `${path}[]`]]
    : node.value ? [['{키}', node.value, `${path}{}`]]
    : []
  const [open, setOpen] = useState(depth < 2)
  const hit = hl.has(name)
  return (
    <div style={{ marginLeft: depth ? 14 : 0 }}>
      <div className="small" style={{ padding: '1px 0' }}>
        {children.length > 0 ? (
          <button className="linklike" onClick={() => setOpen(!open)} style={{ border: 0, background: 'none', padding: 0, cursor: 'pointer', width: 14 }}>{open ? '▾' : '▸'}</button>
        ) : <span style={{ display: 'inline-block', width: 14 }} />}
        <span className="mono" style={hit ? { background: 'var(--warn-soft)', color: 'var(--warn)', fontWeight: 700, padding: '0 3px', borderRadius: 4 } : undefined}>{name}</span>
        <span className="muted"> {node.type}{node.ref ? ` (${node.ref} 반복)` : ''}{node.required ? ' · 필수' : ''}</span>
        {node.enum && <span className="muted"> · {node.enum.map((e) => <code key={e} style={{ marginRight: 4 }}>{e}</code>)}</span>}
        {node.doc && <div className="muted" style={{ marginLeft: 14, fontSize: 12 }}>{node.doc}</div>}
      </div>
      {open && children.map(([k, v, p]) => <Tree key={p} name={k} node={v} path={p} hl={hl} depth={depth + 1} />)}
    </div>
  )
}

function OpPanel({ opKey, hl, idx }: { opKey: string; hl: Set<string>; idx: Index }) {
  const svc = idx.operations[opKey].service
  const d = useAsync(() => api.get<Record<string, OpDetail>>(`/api/apiref/services/${svc}`), [svc])
  const op = d.data?.[opKey]
  if (!op) return <Loading error={d.error} loading={d.loading} />
  return (
    <div className="card" style={{ marginTop: 8 }}>
      <div className="row">
        <strong className="mono">{op.service}.{op.operation}</strong>
        <span className="mono small muted">client.{op.method}()</span>
        {op.paginated && <span className="badge">페이지네이션</span>}
        <div className="spacer" />
        {op.urls.aws && <a href={op.urls.aws} target="_blank" rel="noreferrer">AWS API Reference ↗</a>}
        <a href={op.urls.boto3} target="_blank" rel="noreferrer">boto3 ↗</a>
      </div>
      <p className="small">{op.doc}</p>
      {op.input_required.length > 0 && <p className="small muted">필수 요청 인자: <span className="mono">{op.input_required.join(', ')}</span></p>}
      <p className="small muted">
        raw 키: <span className="mono">{op.raw_keys.join(', ') || '—'}</span> · 이 API 를 보는 룰 {op.rules.length}개
        {op.rules.length > 0 && <>: {op.rules.map((r) => <Link key={r} to={`/apiref?rule=${r}`} style={{ marginRight: 6 }}>{idx.rules[r]?.code ?? r}</Link>)}</>}
      </p>
      {op.added_in_latest.length > 0 && (
        <details>
          <summary className="small"><span className="badge warn">최신 botocore 에만 있는 필드 {op.added_in_latest.length}</span> — 엔진의 botocore {idx.meta.botocore} 는 이 필드를 응답에서 버린다</summary>
          <div className="mono small" style={{ columns: 2, marginTop: 6 }}>{op.added_in_latest.map((p) => <div key={p}>{p}</div>)}</div>
        </details>
      )}
      <h3 className="small" style={{ marginBottom: 4 }}>응답 (botocore {idx.meta.botocore} 모델){hl.size > 0 && <span className="muted"> — 노란 필드는 고른 룰이 읽는 키</span>}</h3>
      {op.output ? <Tree name="(응답)" node={op.output} path="" hl={hl} /> : <p className="muted small">응답 본문 없음</p>}
    </div>
  )
}

export default function ApiRef() {
  const idx = useAsync(() => api.get<Index>('/api/apiref'), [])
  const [sp, setSp] = useSearchParams()
  const rule = sp.get('rule') ?? ''
  const svc = sp.get('svc') ?? ''
  const [q, setQ] = useState('')
  const [onlyLatest, setOnlyLatest] = useState(false)
  const [open, setOpen] = useState<string | null>(sp.get('op'))
  const set = (k: string, v: string) => {
    const n = new URLSearchParams(sp)
    if (v) n.set(k, v)
    else n.delete(k)
    if (k === 'rule') n.delete('svc')
    setSp(n, { replace: true })
  }
  useEffect(() => setOpen(sp.get('op')), [sp])

  const data = idx.data
  const r = data && rule ? data.rules[rule] : null
  const hl = useMemo(() => new Set(r?.fields_read ?? []), [r])
  const services = useMemo(() => (data ? [...new Set(Object.values(data.operations).map((o) => o.service))].sort() : []), [data])
  const ruleOptions = useMemo(
    () => (data ? Object.entries(data.rules).filter(([, v]) => v.operations.length).sort((a, b) => (a[1].code ?? a[0]).localeCompare(b[1].code ?? b[0])) : []),
    [data],
  )
  if (!data) return <Loading error={idx.error} loading />

  const ql = q.trim().toLowerCase()
  const ops = Object.entries(data.operations).filter(([k, o]) =>
    (!r || r.operations.includes(k)) && (!svc || o.service === svc) && (!onlyLatest || o.added_in_latest > 0) &&
    (!ql || k.toLowerCase().includes(ql) || o.method.includes(ql) || o.raw_keys.some((x) => x.toLowerCase().includes(ql))),
  )
  const m = data.meta
  const flagged = Object.entries(data.rules).filter(([, v]) => v.unknown_fields.length)

  return (
    <>
      <h1>AWS API 참고</h1>
      <div className="sub">
        엔진 수집기(<code>AWS/Raw/Service</code>) · 룰(<code>AWS/Analyze/Service</code>)이 쓰는 AWS API 와, 그 응답 구조 · 필드 설명 · enum 을 공식 API 모델(botocore {m.botocore},
        AWS API Reference 와 같은 원본)에서 뽑았다. 엔진 <span className="mono">{m.engine_ref}</span>({m.engine_sha}) · {m.generated_at} 생성 —
        API {m.counts.operations} · raw 키 {m.counts.raw_keys} · 룰 {m.counts.rules}. 다시 만들기: <code>uv run rv apiref</code>
      </div>

      {(flagged.length > 0 || data.collector_unknown.length > 0) && (
        <div className="card" style={{ marginBottom: 12 }}>
          <strong>모델에 없는 키를 읽는 곳</strong> <span className="muted small">— 응답에 그 키가 없어 항상 빈 값 · 예외가 될 수 있다(확인 후보)</span>
          <ul className="small" style={{ margin: '6px 0 0' }}>
            {flagged.map(([rid, v]) => (
              <li key={rid}>룰 <Link to={`/apiref?rule=${rid}`}>{v.code ?? rid}</Link> <span className="mono">{v.unknown_fields.join(', ')}</span> <span className="muted mono">{v.file}:{v.line}</span></li>
            ))}
            {data.collector_unknown.map((c) => (
              <li key={`${c.file}:${c.line}`}>수집기 <span className="mono">{c.raw_service}.{c.function}</span> <span className="mono">{c.unknown_fields.join(', ')}</span> <span className="muted mono">{c.file}:{c.line}</span></li>
            ))}
          </ul>
        </div>
      )}

      <div className="row" style={{ marginBottom: 10 }}>
        <label className="inline">룰
          <select value={rule} onChange={(e) => set('rule', e.target.value)} style={{ maxWidth: 380 }}>
            <option value="">전체</option>
            {ruleOptions.map(([rid, v]) => <option key={rid} value={rid}>{v.code ?? rid} · {v.name ?? ''}</option>)}
          </select>
        </label>
        <label className="inline">서비스
          <select value={svc} onChange={(e) => set('svc', e.target.value)}>
            <option value="">전체 ({services.length})</option>
            {services.map((s) => <option key={s}>{s}</option>)}
          </select>
        </label>
        <input type="search" placeholder="API · raw 키 검색" value={q} onChange={(e) => setQ(e.target.value)} />
        <label className="inline small"><input type="checkbox" checked={onlyLatest} onChange={(e) => setOnlyLatest(e.target.checked)} />최신 botocore 에만 있는 필드가 있는 API</label>
      </div>

      {r && (
        <div className="card" style={{ marginBottom: 10 }}>
          <div className="row">
            <strong>{r.code} · {r.name}</strong>
            <span className="mono small muted">{rule} · {r.file}:{r.line}</span>
            <div className="spacer" />
            <Link to="/playground">입력 실험</Link>
          </div>
          <p className="small" style={{ marginBottom: 0 }}>
            읽는 raw: <span className="mono">{r.raw_keys.map((k) => `${k.service}.${k.key}`).join(', ')}</span><br />
            읽는 키(<code>x["…"]</code> · <code>.get("…")</code>): <span className="mono">{r.fields_read.join(', ') || '—'}</span>
            {r.unknown_fields.length > 0 && <><br /><span className="diff">모델에 없는 키: {r.unknown_fields.join(', ')}</span></>}
            {r.documented_extra.length > 0 && <><br />IAM 자격 증명 보고서 CSV 컬럼(API 모델 밖, <a href={data.documented_extra['iam.get_credential_report']?.doc} target="_blank" rel="noreferrer">문서 ↗</a>): <span className="mono">{r.documented_extra.join(', ')}</span></>}
          </p>
        </div>
      )}

      <div className="table-wrap">
        <table>
          <thead><tr><th>API</th><th>raw 키</th><th>룰</th><th>최신 추가</th><th>설명</th></tr></thead>
          <tbody>
            {ops.map(([k, o]) => (
              <Fragment key={k}>
                <tr className="click" onClick={() => setOpen(open === k ? null : k)}>
                  <td className="mono small nowrap">{open === k ? '▾ ' : '▸ '}{k}{o.paginated ? ' ⋯' : ''}</td>
                  <td className="mono small">{o.raw_keys.join(', ') || '—'}</td>
                  <td className="small">{o.rules.length || '—'}</td>
                  <td className="small">{o.added_in_latest ? <span className="badge warn">{o.added_in_latest}</span> : '—'}</td>
                  <td className="small muted">{o.doc}</td>
                </tr>
                {open === k && (
                  <tr><td colSpan={5} style={{ background: 'var(--bg)' }}><OpPanel opKey={k} hl={hl} idx={data} /></td></tr>
                )}
              </Fragment>
            ))}
          </tbody>
        </table>
      </div>
      {ops.length === 0 && <p className="muted">조건에 맞는 API 가 없다.</p>}
    </>
  )
}
