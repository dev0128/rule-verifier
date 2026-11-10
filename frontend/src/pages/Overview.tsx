import { useMemo, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { api, waitJob, type FindingRow, type Job, type Variant } from '../api'
import { EFFECT_CLASS, EFFECT_LABEL, EFFECT_ORDER, EffectBadge, EffectBar, HelpLink, JobLine, Loading, STATUS, StatusBadge, TransitionChip, statusKey, useAsync } from '../ui'

type Overview = {
  total_findings: number
  total_rules: number
  with_case: number
  by_effect: Record<string, number>
  by_level: Record<string, number>
  by_category: Record<string, Record<string, number>>
  status: Record<string, Record<string, number>>
  case_runs: Record<string, { ran_at: string; engine: { ref: string; sha: string } } | null>
  variants: Variant[]
}

const LEVELS = ['High', 'Medium', 'Low']

export default function OverviewPage() {
  const ov = useAsync(() => api.get<Overview>('/api/overview'), [])
  const cat = useAsync(() => api.get<{ findings: FindingRow[]; variants: Variant[] }>('/api/catalog'), [])
  const [job, setJob] = useState<Job | null>(null)
  const [sp, setSp] = useSearchParams()
  const nav = useNavigate()

  const q = sp.get('q') ?? ''
  const effect = sp.get('effect') ?? ''
  const category = sp.get('cat') ?? ''
  const level = sp.get('lv') ?? ''
  const st = sp.get('st') ?? ''
  const tr = sp.get('tr') ?? ''
  const set = (k: string, v: string) => {
    const n = new URLSearchParams(sp)
    if (v) n.set(k, v)
    else n.delete(k)
    setSp(n, { replace: true })
  }

  const variants = cat.data?.variants ?? []
  const base = variants[0]?.id
  const rows = useMemo(() => {
    const all = cat.data?.findings ?? []
    const ql = q.toLowerCase()
    return all.filter((f) => {
      if (effect && f.effect !== effect) return false
      if (category && f.category !== category) return false
      if (level && f.level !== level) return false
      if (st) {
        const [vid, key] = st.split(':')
        const k = statusKey(f.results[vid], f.has_case, f.results[base], vid === base, f.has_fix?.[vid])
        if (k !== key) return false
      }
      if (tr === '항상' && !/항상|절대|모든|전부/.test(f.outcome)) return false
      if (tr && tr !== '항상' && !(f.transitions[base] ?? []).includes(tr)) return false
      if (!ql) return true
      return [f.id, f.code, f.codes.join(' '), f.name, f.outcome, f.summary, f.rule].join(' ').toLowerCase().includes(ql)
    })
  }, [cat.data, q, effect, category, level, st, tr, base])
  // 결과 전이 select — 운영 엔진 케이스 결과에 나온 전이를 많은 순으로
  const trOptions = useMemo(() => {
    const n: Record<string, number> = {}
    for (const f of cat.data?.findings ?? []) for (const t of f.transitions[base] ?? []) n[t] = (n[t] ?? 0) + 1
    return Object.entries(n).sort((a, b) => b[1] - a[1])
  }, [cat.data, base])

  const runAll = async () => {
    const j = await api.post<Job>('/api/cases/run', {})
    setJob(j)
    await waitJob(j.id, setJob)
    ov.reload()
    cat.reload()
  }

  if (!ov.data || !cat.data) return <Loading error={ov.error || cat.error} loading />
  const o = ov.data
  const baseStatus = o.status[base] ?? {}
  const reproduced = (baseStatus.defect ?? 0) + (baseStatus.collection_only ?? 0)
  const imp = variants[1]
  const improvedCount = imp ? cat.data.findings.filter((f) => statusKey(f.results[imp.id], f.has_case, f.results[base], false) === 'improved').length : 0

  return (
    <>
      <div className="row">
        <div>
          <h1>AWS 기본 룰 결함 검증 현황</h1>
          <div className="sub">
            위키 0107 · 0106 에서 파악한 결함 {o.total_findings}건을 재현 케이스(입력 → 올바른 결과)로 만들어 엔진 변형마다 돌린 결과.
          </div>
        </div>
        <div className="spacer" />
        <button className="primary" onClick={runAll} disabled={job?.status === 'running'}>
          전체 케이스 다시 실행
        </button>
      </div>
      <JobLine job={job} />

      <div className="grid kpis" style={{ marginTop: 12 }}>
        <div className="card kpi">
          <div className="label">파악된 결함</div>
          <div className="value">{o.total_findings}</div>
          <div className="hint">룰 {o.total_rules}개 · 재현 케이스 {o.with_case}건</div>
        </div>
        <div className="card kpi">
          <div className="label" title="결함이 드러나는 입력을 현재 운영 엔진으로 돌렸을 때 틀리게 나온 결함">현재 운영 엔진에 결함 있음<HelpLink to="status" /></div>
          <div className="value" style={{ color: 'var(--bad)' }}>{reproduced}</div>
          <div className="hint">
            {STATUS.defect.label} {baseStatus.defect ?? 0} · {STATUS.collection_only.label} {baseStatus.collection_only ?? 0} · {STATUS.not_reproducible.label} {baseStatus.not_reproducible ?? 0}
          </div>
        </div>
        {imp && (
          <div className="card kpi">
            <div className="label">{imp.label}에서 개선됨</div>
            <div className="value" style={{ color: 'var(--good)' }}>{improvedCount}</div>
            <div className="hint">개선 로직이 있는 결함 {cat.data.findings.filter((f) => f.has_fix?.[imp.id]).length}건 · 나머지는 {STATUS.no_fix.label}<HelpLink to="status" /></div>
          </div>
        )}
        {EFFECT_ORDER.slice(0, 2).map((e) => (
          <div key={e} className="card kpi">
            <div className="label">{EFFECT_LABEL[e]}</div>
            <div className="value">{o.by_effect[e] ?? 0}</div>
            <div className="hint">{e === 'false_positive' ? '정상인데 취약으로' : '취약인데 양호로'}</div>
          </div>
        ))}
      </div>

      <h2>유형별 · 서비스별</h2>
      <div className="grid" style={{ gridTemplateColumns: 'minmax(260px, 1fr) minmax(320px, 2fr)' }}>
        <div className="card">
          {EFFECT_ORDER.map((e) => (
            <div key={e} className="row" style={{ marginBottom: 6, cursor: 'pointer' }} onClick={() => set('effect', effect === e ? '' : e)}>
              <span style={{ width: 70 }}>
                <i className={EFFECT_CLASS[e]} style={{ display: 'inline-block', width: 10, height: 10, borderRadius: 2, marginRight: 6 }} />
                {EFFECT_LABEL[e]}
              </span>
              <div className="bar" style={{ flex: 1 }}>
                <span className={EFFECT_CLASS[e]} style={{ width: `${((o.by_effect[e] ?? 0) / o.total_findings) * 100}%` }} />
              </div>
              <span className="mono" style={{ width: 34, textAlign: 'right', fontWeight: effect === e ? 700 : 400 }}>
                {o.by_effect[e] ?? 0}
              </span>
            </div>
          ))}
          <div className="muted small" style={{ marginTop: 8 }}>
            등급: {LEVELS.map((l) => `${l} ${o.by_level[l] ?? 0}`).join(' · ')}
          </div>
        </div>
        <div className="card" style={{ maxHeight: 260, overflow: 'auto' }}>
          <div className="legend" style={{ marginBottom: 8 }}>
            {EFFECT_ORDER.map((e) => (
              <span key={e}>
                <i className={EFFECT_CLASS[e]} />
                {EFFECT_LABEL[e]}
              </span>
            ))}
          </div>
          {Object.entries(o.by_category).map(([c, counts]) => {
            const n = Object.values(counts).reduce((a, b) => a + b, 0)
            return (
              <div key={c} className="row small" style={{ marginBottom: 4, cursor: 'pointer' }} onClick={() => set('cat', category === c ? '' : c)}>
                <span className="mono" style={{ width: 44, fontWeight: category === c ? 700 : 400 }}>{c}</span>
                <div style={{ flex: 1 }}>
                  <div style={{ width: `${(n / Math.max(...Object.values(o.by_category).map((x) => Object.values(x).reduce((a, b) => a + b, 0)))) * 100}%` }}>
                    <EffectBar counts={counts} />
                  </div>
                </div>
                <span className="mono muted" style={{ width: 26, textAlign: 'right' }}>{n}</span>
              </div>
            )
          })}
        </div>
      </div>

      <h2>결함 목록</h2>
      <div className="row" style={{ marginBottom: 10 }}>
        <input type="search" placeholder="룰 코드 · 항목명 · 요약 검색" value={q} onChange={(e) => set('q', e.target.value)} />
        <select value={effect} onChange={(e) => set('effect', e.target.value)}>
          <option value="">유형 전체</option>
          {EFFECT_ORDER.map((e) => (
            <option key={e} value={e}>{EFFECT_LABEL[e]}</option>
          ))}
        </select>
        <select value={category} onChange={(e) => set('cat', e.target.value)}>
          <option value="">서비스 전체</option>
          {Object.keys(o.by_category).sort().map((c) => (
            <option key={c} value={c}>{c}</option>
          ))}
        </select>
        <select value={level} onChange={(e) => set('lv', e.target.value)}>
          <option value="">등급 전체</option>
          {LEVELS.map((l) => (
            <option key={l} value={l}>{l}</option>
          ))}
        </select>
        <select value={tr} onChange={(e) => set('tr', e.target.value)}>
          <option value="">결과 전체</option>
          <option value="항상">항상 · 절대 · 전부 (입력과 무관)</option>
          <optgroup label="올바른 결과 → 운영 엔진 결과">
            {trOptions.map(([t, n]) => <option key={t} value={t}>{t} ({n})</option>)}
          </optgroup>
        </select>
        <select value={st} onChange={(e) => set('st', e.target.value)}>
          <option value="">상태 전체</option>
          {variants.map((v) => (
            <optgroup key={v.id} label={v.label}>
              {['defect', 'no_fix', 'collection_only', 'ok', 'improved', 'not_reproducible', 'case_broken', 'no_case', 'not_run']
                .filter((k) => (v.id === base ? k !== 'improved' && k !== 'no_fix' : true))
                .map((k) => (
                  <option key={k} value={`${v.id}:${k}`}>{v.label} · {STATUS[k].label}</option>
                ))}
            </optgroup>
          ))}
        </select>
        <span className="muted small">{rows.length}건</span>
      </div>
      <div className="table-wrap" style={{ maxHeight: '70vh' }}>
        <table>
          <thead>
            <tr>
              <th>ID</th>
              <th>룰</th>
              <th>항목명</th>
              <th>등급</th>
              <th>유형<HelpLink to="effect" title="오탐 · 미탐 · 점검 누락 … 뜻" /></th>
              <th title="어떤 상황에서 어떤 결과가 나오는지 한 줄. 칩은 재현 케이스에서 운영 엔진이 낸 판정(올바른 결과 → 엔진 결과). 마우스를 올리면 결함 요약">결과<HelpLink to="chip" title="취약→양호 같은 칩의 뜻" /></th>
              {variants.map((v) => (
                <th key={v.id}>{v.label}<HelpLink to="status" title="결함 있음 · 개선됨 · 개선 로직 없음 … 뜻" /></th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((f) => (
              <tr key={f.id} className="click" onClick={() => nav(`/findings/${f.id}`)}>
                <td className="mono nowrap">{f.id}</td>
                <td className="mono nowrap">
                  {f.code}
                  {f.codes.length > 1 && <span className="muted"> +{f.codes.length - 1}</span>}
                </td>
                <td style={{ minWidth: 180 }}>{f.name}</td>
                <td>{f.level}</td>
                <td><EffectBadge effect={f.effect} /></td>
                <td className="small" style={{ minWidth: 280 }} title={f.summary}>
                  <div style={{ fontWeight: 600 }}>{f.outcome || f.summary}</div>
                  {(f.transitions[base] ?? []).length > 0 && (
                    <div style={{ marginTop: 3 }}>{f.transitions[base].map((t) => <TransitionChip key={t} t={t} />)}</div>
                  )}
                </td>
                {variants.map((v, i) => (
                  <td key={v.id} className="nowrap">
                    <StatusBadge k={statusKey(f.results[v.id], f.has_case, f.results[base], i === 0, f.has_fix?.[v.id])} />
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="muted small">
        케이스 실행 시각 —{' '}
        {variants.map((v) => `${v.label}: ${o.case_runs[v.id]?.ran_at ?? '미실행'}`).join(' · ')}
      </p>
    </>
  )
}
