import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, type FindingRow, type RuleOption, type RuleResult, type Variant } from '../api'
import { CONFIDENCE, Counts, DEFECT_TYPE, EFFECT_HINT, EffectBadge, HelpLink, Loading, StatusBadge, StatusLegend, VerdictBadge, statusKey, useAsync } from '../ui'
import { DbPicker } from './Diagnoses'

type LocalDiag = {
  id: string; env?: string; key_id?: string; his_id?: string; rulesets: string[]; raw_size: number; raw_modified?: string
  labels?: { company?: string | null; tenant?: string; key_alias?: string | null; group_name?: string | null; ruleset_names?: Record<string, string> }
}
type PreRule = { rule: string; args: unknown; service: string }
type RealSlice = {
  raw: Record<string, unknown>; keys: string[]; how: string; regions: Record<string, number>; all_regions: string[]; records: number; bytes: number
  args: unknown; enabled: boolean | null; ruleset_name: string | null; as_of: string | null; production: RuleResult | null; pre_rules: PreRule[]
}
const COUNT_KEYS: [keyof RuleResult, string][] = [['checked', '점검'], ['flag', '취약'], ['good', '양호'], ['na', 'N/A']]
const VERDICT_KO: Record<string, string> = { Vuln: '취약', Secure: '양호', 'N/A': 'N/A', ERROR: '예외', MISSING: '함수 없음' }
const ko = (v?: string | null) => (v ? VERDICT_KO[v] ?? v : '—')
type Mark = '취약' | '양호' | 'N/A'
const MARK_CLS: Record<Mark, string> = { 취약: 'bad', 양호: 'good', 'N/A': '' }

/** 리소스 id → 그 엔진의 판정(취약 · 양호 · N/A 목록) */
function marks(r?: RuleResult | null): Map<string, Mark> {
  const m = new Map<string, Mark>()
  for (const i of r?.na_ids ?? []) m.set(i, 'N/A')
  for (const i of r?.good_ids ?? []) m.set(i, '양호')
  for (const i of r?.flag_ids ?? []) m.set(i, '취약')
  return m
}

/** a(개선 전 · 기준) → b 에서 바뀐 것 — 판정 · 건수 · 예외 · 리소스별 판정 */
function changes(a: RuleResult, b: RuleResult): string[] {
  const d: string[] = []
  if (a.verdict !== b.verdict) d.push(`판정 ${ko(a.verdict)} → ${ko(b.verdict)}`)
  const cnt = COUNT_KEYS.filter(([k]) => (a[k] ?? 0) !== (b[k] ?? 0)).map(([k, l]) => `${l} ${a[k] ?? 0}→${b[k] ?? 0}`)
  if (cnt.length) d.push(`건수 ${cnt.join(' · ')}`)
  if (b.error && !a.error) d.push(`예외 생김 ${b.error.type}`)
  if (a.error && !b.error) d.push(`예외 없어짐 (${a.error.type})`)
  const ma = marks(a), mb = marks(b)
  const moved = [...new Set([...ma.keys(), ...mb.keys()])].filter((i) => ma.get(i) !== mb.get(i))
  for (const i of moved.slice(0, 6)) d.push(`${i}: ${ma.get(i) ?? '없음'} → ${mb.get(i) ?? '없음'}`)
  if (moved.length > 6) d.push(`리소스 ${moved.length - 6}개 더 바뀜 — 아래 리소스별 판정`)
  return d
}

const ruleFindings = (rows: FindingRow[] | undefined, rule: string) => (rows ?? []).filter((f) => (f.rules?.length ? f.rules : [f.rule]).includes(rule))
const countBy = (xs: string[]) => Object.entries(xs.reduce<Record<string, number>>((m, x) => ({ ...m, [x]: (m[x] ?? 0) + 1 }), {}))

/** 고른 룰 한눈에 — 결함이 있는지 · 어떤 결함인지 · 고쳐졌는지를 배지로 */
function RuleBadges({ rule, opt, rows, variants, improvedIn }: {
  rule: string; opt: RuleOption | undefined; rows: FindingRow[] | undefined; variants: Variant[]; improvedIn: string[] | null
}) {
  const fs = ruleFindings(rows, rule)
  const base = variants[0]?.id
  const fixV = variants.slice(1)
  const st = fixV.flatMap((v) => fs.map((f) => statusKey(f.results[v.id], f.has_case, f.results[base], false, f.has_fix?.[v.id])))
  const lg = { fontSize: 13, padding: '3px 10px' }
  return (
    <div className="row" style={{ gap: 6, margin: '10px 0 6px', alignItems: 'center' }}>
      <span className="mono" style={{ fontWeight: 700 }}>{opt?.code ?? rule}</span>
      <span>{opt?.name}</span>
      {opt?.level && <span className="badge">{opt.level}</span>}
      <span style={{ width: 8 }} />
      {!rows ? null : fs.length ? (
        <span className="badge bad" style={lg} title="결함 카탈로그(0107)에 이 룰의 결함으로 올라 있는 것">알려진 결함 {fs.length}건</span>
      ) : (
        <span className="badge good" style={lg} title="결함 카탈로그에 없음 — 결과가 이상하면 새 결함 후보">알려진 결함 없음</span>
      )}
      {countBy(fs.map((f) => f.effect)).map(([e, n]) => (
        <span key={e} title={EFFECT_HINT[e]}><EffectBadge effect={e} />{n > 1 && <span className="small muted"> ×{n}</span>}</span>
      ))}
      {countBy(fs.map((f) => f.type)).map(([t, n]) => {
        const d = DEFECT_TYPE[t] ?? { label: t, cls: '', hint: '' }
        return <span key={t} className={`badge ${d.cls}`} title={d.hint}>{d.label}{n > 1 ? ` ×${n}` : ''}</span>
      })}
      {improvedIn && (
        <>
          <span className="muted" style={{ margin: '0 2px 0 8px' }}>|</span>
          <span className="small muted">{fixV.map((v) => v.label).join(', ')}</span>
          {improvedIn.length
            ? <span className="badge accent" style={lg} title={`이 룰 코드가 ${variants.filter((v) => improvedIn.includes(v.id)).map((v) => v.label).join(', ')} 에서 바뀌었다`}>개선 로직 있음</span>
            : <span className="badge muted-badge" style={lg} title={`이 룰 코드는 ${fixV.map((v) => v.label).join(', ')} 에서도 ${variants[0]?.label} 와 같다 — 결과도 운영과 같다`}>개선 로직 없음</span>}
          {improvedIn.length > 0 && fs.length > 0 && (
            <span className="small" title="알려진 결함마다 수정 브랜치에서 어떻게 나왔나">
              → {countBy(st).map(([k, n], i) => <span key={k}>{i > 0 && ' · '}<StatusBadge k={k} /> {n}건</span>)}
            </span>
          )}
        </>
      )}
      {fs.length > 0 && <span className="muted" style={{ margin: '0 2px 0 8px' }}>|</span>}
      {fs.length > 0 && (
        <span className="small" style={{ marginLeft: 4 }}>
          {fs.map((f) => <a key={f.id} href={`#defect-${f.id}`} className="mono" style={{ marginRight: 6 }} title={f.outcome}>{f.id}</a>)}
        </span>
      )}
      <HelpLink to="status" />
    </div>
  )
}

/** 이 룰의 알려진 결함(0107 카탈로그) — 이 입력의 판정에서 무엇이 부족할 수 있는지 */
function KnownDefects({ rule, rows, variants }: { rule: string; rows: FindingRow[] | undefined; variants: Variant[] }) {
  if (!rows) return null
  const fs = ruleFindings(rows, rule)
  const base = variants[0]?.id
  return (
    <div className="card" style={{ marginTop: 10 }}>
      <div className="row small" style={{ marginBottom: 6 }}>
        <b>이 룰의 알려진 결함 {fs.length ? `${fs.length}건` : ''}</b><HelpLink to="status" title="결함 있음 · 개선됨 · 개선 로직 없음 … 뜻" />
        <span className="muted">아래 결과를 볼 때 “틀리는 조건” 이 이 raw 에 있는지, 있으면 판정이 맞게 나왔는지 본다</span>
      </div>
      {fs.length > 0 && (
        <div style={{ marginBottom: 6 }}>
          <StatusLegend keys={fs.flatMap((f) => variants.map((v) => statusKey(f.results[v.id], f.has_case, f.results[base], v.id === base, f.has_fix?.[v.id])))} />
        </div>
      )}
      {fs.length === 0 ? (
        <p className="small muted" style={{ margin: 0 }}>
          카탈로그에 알려진 결함 없음 — 아래 리소스별 판정이 이상하면 새 결함 후보다(<span className="mono">catalog/findings.json</span> + 케이스).
        </p>
      ) : fs.map((f, i) => {
        const { label: tl, cls: tc, hint: th } = DEFECT_TYPE[f.type] ?? { label: f.type, cls: '', hint: '' }
        return (
          <div key={f.id} id={`defect-${f.id}`} className="small" style={{ padding: '8px 0', borderTop: i ? '1px solid var(--border)' : undefined, scrollMarginTop: 12 }}>
            <div className="row" style={{ gap: 8, alignItems: 'flex-start' }}>
              <Link to={`/findings/${f.id}`} className="mono">{f.id}</Link>
              <b style={{ flex: 1, minWidth: 200 }}>{f.outcome || f.summary}</b>
              <span>
                {variants.map((v) => (
                  <span key={v.id} style={{ marginLeft: 10, whiteSpace: 'nowrap' }}>{v.label} <StatusBadge k={statusKey(f.results[v.id], f.has_case, f.results[base], v.id === base, f.has_fix?.[v.id])} /></span>
                ))}
              </span>
            </div>
            <div className="kv" style={{ marginTop: 6, gridTemplateColumns: '90px 1fr' }}>
              <div>어떤 결함<HelpLink to="type" title="룰 로직 오류 · 수집 누락 · 오탐 · 미탐 … 뜻" /></div>
              <div>
                <span className={`badge ${tc}`} title={th}>{tl}</span>{' '}
                <EffectBadge effect={f.effect} /> <span className="muted">{EFFECT_HINT[f.effect] ?? ''}</span>
                {f.confidence && <span className="muted"> · 확신도 {CONFIDENCE[f.confidence] ?? f.confidence}</span>}
                {th && <div className="muted">{th}</div>}
              </div>
              <div>원인</div>
              <div>{f.summary}</div>
              {f.impact && <><div>영향</div><div>{f.impact}</div></>}
              {f.trigger && <><div>틀리는 조건</div><div>{f.trigger}</div></>}
              {f.evidence && (
                <>
                  <div>코드 위치</div>
                  <details>
                    <summary className="muted mono" style={{ cursor: 'pointer' }}>{f.evidence.split(/\s/)[0]}</summary>
                    <pre className="json" style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word', margin: '4px 0 0' }}>{f.evidence}</pre>
                  </details>
                </>
              )}
            </div>
          </div>
        )
      })}
    </div>
  )
}

/** 리소스별 판정 — 엔진(· 운영 실제 결과)마다 같은 리소스를 어떻게 판정했는지, 다른 곳을 위로 */
function ResourceMatrix({ cols }: { cols: { key: string; label: string; r: RuleResult | null | undefined }[] }) {
  const [onlyDiff, setOnlyDiff] = useState(false)
  const ms = cols.map((c) => marks(c.r))
  const ids = [...new Set(ms.flatMap((m) => [...m.keys()]))]
  if (!ids.length) return <p className="small muted">판정된 리소스 없음(점검 0건이거나 리소스 목록을 남기지 않는 룰).</p>
  const differs = (i: string) => new Set(ms.map((m) => m.get(i) ?? '')).size > 1
  const order: Record<string, number> = { 취약: 0, 양호: 1, 'N/A': 2, '': 3 }
  const rows = ids
    .filter((i) => !onlyDiff || differs(i))
    .sort((a, b) => Number(differs(b)) - Number(differs(a)) || order[ms[0].get(a) ?? ''] - order[ms[0].get(b) ?? ''] || a.localeCompare(b))
  const nDiff = ids.filter(differs).length
  const LIMIT = 300
  return (
    <div style={{ marginTop: 12 }}>
      <div className="row small">
        <b>리소스별 판정</b><HelpLink to="verdict" title="취약 · 양호 · N/A 뜻" />
        <span className="muted">{ids.length}개 리소스{cols.length > 1 && <> · 엔진마다 다른 것 <b className={nDiff ? 'diff' : undefined}>{nDiff}</b>개</>}</span>
        {cols.length > 1 && <label className="inline"><input type="checkbox" checked={onlyDiff} onChange={(e) => setOnlyDiff(e.target.checked)} />다른 것만</label>}
      </div>
      <div className="table-wrap" style={{ maxHeight: 480, overflow: 'auto' }}>
        <table className="small" style={{ tableLayout: 'fixed', minWidth: 480 }}>
          <colgroup><col />{cols.map((c) => <col key={c.key} style={{ width: `${Math.round(55 / cols.length)}%` }} />)}</colgroup>
          <thead><tr><th>리소스</th>{cols.map((c) => <th key={c.key}>{c.label}</th>)}</tr></thead>
          <tbody>
            {rows.slice(0, LIMIT).map((i) => (
              <tr key={i} style={differs(i) ? { background: 'var(--warn-soft)' } : undefined}>
                <td className="mono" style={{ wordBreak: 'break-all' }}>{i}</td>
                {cols.map((c, k) => {
                  const m = ms[k].get(i)
                  const why = m === '취약' ? c.r?.flag_reason?.[i] : undefined
                  return (
                    <td key={c.key}>
                      {m ? <span className={`badge ${MARK_CLS[m]}`}>{m}</span> : <span className="muted">없음</span>}
                      {why !== undefined && <div className="muted" style={{ wordBreak: 'break-all' }}>{String(why).slice(0, 200)}</div>}
                    </td>
                  )
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {rows.length > LIMIT && <p className="small muted">{rows.length - LIMIT}개 더 있음 — 리전을 좁히거나 “다른 것만”</p>}
    </div>
  )
}

const TEXTAREA_LIMIT = 1_500_000 // 이보다 큰 raw 는 편집 창에 바로 펼치지 않는다(브라우저가 느려짐)
const mb = (n: number) => (n > 1e6 ? `${(n / 1e6).toFixed(1)} MB` : `${Math.ceil(n / 1e3)} KB`)
const diagLabel = (d: LocalDiag) =>
  `${d.labels?.company ?? d.labels?.tenant ?? '(DB 목록에 없음)'} · ${d.labels?.key_alias ?? d.key_id ?? d.id} · ${d.raw_modified?.slice(0, 10) ?? d.his_id ?? ''}${d.env ? ` (${d.env})` : ''}`

type Saved = { rule: string; service?: string; args: unknown; raw: unknown; from?: string }

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

// args 모양 — 기본 룰셋 ["90"] / [] · 거버넌스 기본 룰 "" · 커스텀룰 마스터 참조 null
const ARG_PRESETS: [string, string][] = [
  ['["90"]', '["90"] — 기본 룰셋 (기간 인자)'],
  ['[]', '[] — 기본 룰셋 (인자 없음)'],
  ['""', '"" — 거버넌스 기본 룰'],
  ['null', 'null — 커스텀룰 마스터 참조'],
]
const CUSTOM = '__custom__'

export default function Playground() {
  const init = load()
  const vs = useAsync(() => api.get<Variant[]>('/api/variants'), [])
  const rl = useAsync(() => api.get<{ rules: RuleOption[]; services: string[]; error: string | null; db_env: string | null }>('/api/rules'), [])
  const [rule, setRule] = useState(init.rule)
  const [service, setService] = useState(init.service ?? '')
  const [args, setArgs] = useState(JSON.stringify(init.args ?? null))
  const [argsCustom, setArgsCustom] = useState(!ARG_PRESETS.some(([v]) => v === JSON.stringify(init.args ?? null)))
  const [raw, setRaw] = useState(JSON.stringify(init.raw, null, 2))
  const [out, setOut] = useState<Record<string, RuleResult> | null>(null)
  const cat = useAsync(() => api.get<{ findings: FindingRow[] }>('/api/catalog'), [])
  const [ranRule, setRanRule] = useState('') // 결과 표가 어느 룰 것인지(룰을 바꾸면 이전 결과는 안 맞는다)
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  // 실제 고객 데이터 — 받아 둔 진단에서 이 룰이 읽는 raw 만 잘라 온다
  const diags = useAsync(() => api.get<LocalDiag[]>('/api/diagnoses'), [])
  const [diag, setDiag] = useState('')
  const [ruleset, setRuleset] = useState('')
  const [region, setRegion] = useState('')
  const [engineOrder, setEngineOrder] = useState(true)
  const [onlyEnabled, setOnlyEnabled] = useState(true)
  const [real, setReal] = useState<RealSlice | null>(null)
  const [rawObj, setRawObj] = useState<Record<string, unknown> | null>(null) // 편집 창에 펼치지 않은 큰 실데이터
  const [loadingReal, setLoadingReal] = useState(false)
  const d = diags.data?.find((x) => x.id === diag)
  const rs = useAsync(
    () => (diag && ruleset ? api.get<{ rules: { enabled: boolean; rule: string }[] }>(`/api/diagnoses/${diag}/rulesets/${ruleset}`) : Promise.resolve(null)),
    [diag, ruleset],
  )
  const enabledRules = useMemo(() => new Set((rs.data?.rules ?? []).filter((r) => r.enabled).map((r) => r.rule)), [rs.data])

  const pickDiag = (id: string) => {
    setDiag(id)
    setRegion('')
    setOut(null)
    const dd = diags.data?.find((x) => x.id === id)
    setRuleset(dd?.rulesets[0] ?? '')
    if (!id) {
      setReal(null)
      setRawObj(null)
    }
  }
  useEffect(() => {
    if (!diag || !rule) return
    let gone = false
    setLoadingReal(true)
    setErr(null)
    const q = new URLSearchParams({ diag, rule, ...(ruleset ? { ruleset } : {}), ...(region ? { region } : {}), engine_order: String(engineOrder) })
    api.get<RealSlice>(`/api/playground/real?${q}`).then(
      (r) => {
        if (gone) return
        setReal(r)
        setOut(null)
        if (r.bytes <= TEXTAREA_LIMIT) {
          setRaw(JSON.stringify(r.raw, null, 2))
          setRawObj(null)
        } else {
          setRawObj(r.raw)
        }
        if (r.args !== null && r.args !== undefined) {
          setArgs(JSON.stringify(r.args))
          setArgsCustom(!ARG_PRESETS.some(([v]) => v === JSON.stringify(r.args)))
        }
      },
      (e) => !gone && setErr(String(e.message)),
    ).finally(() => !gone && setLoadingReal(false))
    return () => {
      gone = true
    }
  }, [diag, rule, ruleset, region, engineOrder])

  const run = async () => {
    setErr(null)
    let a: unknown, r: Record<string, unknown>
    try {
      a = JSON.parse(args)
      r = rawObj ?? JSON.parse(raw)
    } catch (e) {
      setErr(`JSON 형식 오류: ${(e as Error).message}`)
      return
    }
    setBusy(true)
    try {
      setRanRule(rule)
      setOut(await api.post<Record<string, RuleResult>>('/api/playground', {
        rule, service: service || null, args: a, raw: r,
        // 실데이터면 진단 시점으로 '지금'을 고정하고, 엔진 순서 재현이면 같은 서비스 앞 룰을 먼저 돌린다
        as_of: real?.as_of ?? null,
        pre_rules: real && engineOrder ? real.pre_rules : null,
      }))
    } catch (e) {
      setErr(String((e as Error).message))
    } finally {
      setBusy(false)
    }
  }

  // 룰 select — 엔진에 함수가 있는 룰만, 서비스 영역(category)별 묶음
  const groups = useMemo(() => {
    const g = new Map<string, RuleOption[]>()
    for (const r of rl.data?.rules ?? []) {
      if (r.has_function === false) continue
      const k = r.category ?? r.service ?? '기타'
      g.set(k, [...(g.get(k) ?? []), r])
    }
    return [...g.entries()]
  }, [rl.data])
  const current = rl.data?.rules.find((r) => r.rule === rule)
  const improvedIn = current?.changed_in ?? null // 이 룰 로직을 바꾼 변형 id
  const services = rl.data?.services ?? []

  // 이 룰의 마스터 기본 인자(clo_rule_dtl) — 컨디션 파일 args 모양 그대로
  const defaultArgs = current?.default_args != null ? JSON.stringify(current.default_args) : null
  const argOptions: [string, string][] = [
    ...(defaultArgs != null ? [[defaultArgs, `${defaultArgs} — 이 룰의 기본값${current?.arg_names.length ? ` (${current.arg_names.join(', ')})` : ' (인자 없음)'}`] as [string, string]] : []),
    ...ARG_PRESETS.filter(([v]) => v !== defaultArgs),
  ]

  const pickRule = (r: string) => {
    setRule(r)
    setService('') // 룰이 바뀌면 서비스는 다시 룰에서 찾게
    const d = rl.data?.rules.find((x) => x.rule === r)?.default_args
    if (d != null) {
      setArgs(JSON.stringify(d))
      setArgsCustom(false)
    }
  }

  if (!vs.data) return <Loading error={vs.error} loading />
  return (
    <>
      <h1>입력 실험</h1>
      <div className="sub">
        룰 하나에 컨디션(인자)과 raw 를 넣어 엔진 변형마다 돌린다. 데이터는 케이스 시나리오(“입력 실험으로 열기”) · 직접 입력 · <b>실제 고객 데이터</b>(받아 둔 진단에서 이 룰이 읽는 raw 만 잘라 옴) 중에서 고른다.
        {init.from && <> 가져온 시나리오: <span className="mono">{init.from}</span></>}
      </div>
      <div className="card" style={{ marginBottom: 10 }}>
        <div className="row">
          <label className="inline">데이터
            <select value={diag} onChange={(e) => pickDiag(e.target.value)} style={{ maxWidth: 520 }}>
              <option value="">직접 입력 · 케이스 시나리오</option>
              {(diags.data ?? []).length > 0 && (
                <optgroup label="실제 고객 데이터 (받아 둔 진단)">
                  {diags.data!.map((x) => <option key={x.id} value={x.id}>{diagLabel(x)}</option>)}
                </optgroup>
              )}
            </select>
          </label>
          {d && (
            <>
              <label className="inline">컨디션 파일
                <select value={ruleset} onChange={(e) => setRuleset(e.target.value)} style={{ maxWidth: 300 }}>
                  {d.rulesets.map((r) => <option key={r} value={r}>{r}{d.labels?.ruleset_names?.[r] ? ` — ${d.labels.ruleset_names[r]}` : ''}</option>)}
                </select>
              </label>
              <label className="inline">리전
                <select value={region} onChange={(e) => setRegion(e.target.value)}>
                  <option value="">전체 리전{real ? ` (레코드 ${real.records})` : ''}</option>
                  {(real?.all_regions ?? []).map((g) => <option key={g} value={g}>{g}{real && !region ? ` (${real.regions[g] ?? 0})` : ''}</option>)}
                </select>
              </label>
              <label className="inline small" title="엔진은 같은 서비스 룰을 정해진 순서로 같은 프로세스 · 같은 raw 에서 돌린다. 앞 룰이 남긴 모듈 전역 상태에 기대는 룰(CWH-015 등)은 이걸 켜야 실데이터 실행과 같은 결과가 된다">
                <input type="checkbox" checked={engineOrder} onChange={(e) => setEngineOrder(e.target.checked)} />운영과 같은 순서로 실행
              </label>
              <label className="inline small"><input type="checkbox" checked={onlyEnabled} onChange={(e) => setOnlyEnabled(e.target.checked)} />이 컨디션 파일에서 켜진 룰만</label>
            </>
          )}
        </div>
        {d && env(d) === 'ops' && <p className="small" style={{ margin: '6px 0 0' }}><span className="badge warn">운영 고객 데이터</span> <span className="muted">화면에서만 본다 — 복사해 다른 곳에 붙이거나 케이스 파일에 넣지 않는다</span></p>}
        {real && d && (
          <p className="small muted" style={{ margin: '6px 0 0' }}>
            {loadingReal ? '불러오는 중… · ' : ''}읽는 raw <span className="mono">{real.keys.join(', ')}</span> ({real.how}) · 레코드 {real.records} · {mb(real.bytes)}
            {real.as_of && <> · 현재 시각을 진단 시각 <span className="mono">{real.as_of.slice(0, 19)}</span> 으로 고정</>}
            {real.ruleset_name && <> · 인자는 {real.ruleset_name} 값{real.enabled === false && <span className="diff"> (이 컨디션 파일에서 꺼진 룰 — 운영에서는 돌지 않음)</span>}</>}
            {real.args === null && ruleset && <span className="diff"> · 이 컨디션 파일에 없는 룰 — 인자는 그대로</span>}
            {engineOrder && real.pre_rules.length > 0 && <> · 운영에서 이 룰보다 먼저 도는 룰 {real.pre_rules.length}개를 먼저 실행</>}
            {region && <span className="diff"> · 리전을 좁히면 리전 수를 세는 룰은 실데이터 실행과 결과가 달라진다</span>}
          </p>
        )}
        <details style={{ marginTop: 6 }}>
          <summary className="small muted">다른 고객 진단 받기 (DB 목록에서 고객사 → 계정 → 진단)</summary>
          <DbPicker onDownloaded={diags.reload} />
        </details>
      </div>
      <div className="card">
        <div className="row">
          <label className="inline">룰
            <select value={rule} onChange={(e) => pickRule(e.target.value)} style={{ maxWidth: 420 }}>
              {!current && <option value={rule}>{rule} (목록에 없음)</option>}
              {groups.filter(([, rs]) => !(d && onlyEnabled && enabledRules.size) || rs.some((r) => enabledRules.has(r.rule) || r.rule === rule)).map(([cat, rs]) => (
                <optgroup key={cat} label={cat}>
                  {rs.filter((r) => !(d && onlyEnabled && enabledRules.size) || enabledRules.has(r.rule) || r.rule === rule).map((r) => (
                    <option key={r.rule} value={r.rule}>
                      {r.code ?? r.rule} · {r.name ?? r.rule}{r.level ? ` (${r.level})` : ''}{r.findings.length ? ` [결함 ${r.findings.length}]` : ''}{r.changed_in?.length ? ' [개선됨]' : ''}{r.in_master === false ? ' — 마스터에 없음' : ''}
                    </option>
                  ))}
                </optgroup>
              ))}
            </select>
          </label>
          <label className="inline">service_name
            <select value={service} onChange={(e) => setService(e.target.value)} className="mono">
              <option value="">자동{current?.service ? ` (${current.service})` : ' (룰에서 찾음)'}</option>
              {service && !services.includes(service) && <option value={service}>{service}</option>}
              {services.map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
          </label>
          <label className="inline">args
            <select
              value={argsCustom || !argOptions.some(([v]) => v === args) ? CUSTOM : args}
              onChange={(e) => {
                const v = e.target.value
                setArgsCustom(v === CUSTOM)
                if (v !== CUSTOM) setArgs(v)
              }}
            >
              {argOptions.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
              <option value={CUSTOM}>직접 입력…</option>
            </select>
            {argsCustom && <input value={args} onChange={(e) => setArgs(e.target.value)} className="mono" style={{ width: 160 }} placeholder='JSON — 예: ["30"]' />}
          </label>
          <div className="spacer" />
          <button className="primary" onClick={run} disabled={busy}>{busy ? '실행 중…' : '실행'}</button>
        </div>
        <RuleBadges rule={rule} opt={current} rows={cat.data?.findings} variants={vs.data} improvedIn={improvedIn} />
        <p className="muted small" style={{ marginTop: 0 }}>
          <span className="mono">{rule}</span> · <Link to={`/apiref?rule=${rule}`}>이 룰이 보는 AWS API · 응답 구조</Link>
          {rl.error && <span className="diff"> · 룰 목록을 못 불러옴: {rl.error}</span>}
          {rl.data?.error && <span className="diff"> · 엔진 룰 목록 오류(서비스 자동 표시 불가): {rl.data.error}</span>}
          {rl.data && (rl.data.db_env ? <> · 항목명 · 등급 · 기본 인자는 {rl.data.db_env} DB 스냅샷</> : <> · DB 스냅샷 없음(실데이터 실행 화면의 “DB 목록 갱신”) — 항목명은 rule_meta.json</>)}
        </p>
        {rawObj ? (
          <div className="card" style={{ background: 'var(--bg)' }}>
            <span className="small">raw 가 {mb(real?.bytes ?? 0)} 라 편집 창에 펼치지 않았다 — 그대로 실행된다.</span>{' '}
            <button onClick={() => { setRaw(JSON.stringify(rawObj, null, 2)); setRawObj(null) }}>편집 창에 펼치기 (느릴 수 있음)</button>
            {' '}<span className="muted small">리전을 하나로 좁히면 작아진다</span>
          </div>
        ) : (
          <textarea rows={18} value={raw} onChange={(e) => setRaw(e.target.value)} spellCheck={false} />
        )}
      </div>
      <KnownDefects rule={rule} rows={cat.data?.findings} variants={vs.data} />
      {err && <div className="err" style={{ marginTop: 10 }}>{err}</div>}
      {out && ranRule === rule && (() => {
        const prod = real?.production && !region ? real.production : null
        const base = vs.data![0]
        const baseR = out[base.id]
        type Row = { key: string; label: React.ReactNode; r: RuleResult | undefined; note: React.ReactNode }
        const list = (d: string[], cls?: string) => d.map((x, i) => <div key={i} className={cls}>{x}</div>)
        const rows: Row[] = []
        if (prod) rows.push({ key: 'prod', r: prod, label: <><b>운영에 저장된 결과</b><br /><span className="muted small">이 진단의 Analyze/{ruleset}</span></>, note: <span className="muted">운영에 저장된 결과</span> })
        for (const [i, v] of vs.data!.entries()) {
          const r = out[v.id]
          let note: React.ReactNode = r?.error ? <span className="diff">{r.error.type}: {r.error.message}</span> : null
          if (i === 0) {
            if (prod && r) {
              const d = changes(prod, r)
              note = d.length
                ? <><div className="diff"><b>운영과 다름</b> — 같은 코드 · 같은 데이터인데 운영에 저장된 결과와 다르다. 결함이 아니라 화면 실행 조건 문제다(“운영과 같은 순서로 실행” · 컨디션 파일 · 리전 확인)</div>{list(d, 'diff')}</>
                : <><span className="ok">운영과 같음</span>{note && <div>{note}</div>}</>
            } else note = note ?? <span className="muted">비교 기준 (지금 운영 코드)</span>
          } else if (improvedIn !== null && !improvedIn.includes(v.id)) {
            note = <span className="muted">아직 개선 로직 없음 — 이 룰은 {base.label} 와 같은 코드라 결과도 같다</span>
          } else if (r && baseR) {
            const d = changes(baseR, r)
            note = d.length
              ? <><div style={{ color: 'var(--warn)' }}><b>개선으로 결과가 바뀜</b> — 위 알려진 결함 때문이면 의도한 변화, 아니면 개선이 다른 걸 망가뜨린 것(회귀)</div>{list(d)}</>
              : <span className="muted">개선 전과 같음 — 이 데이터에는 고친 결함이 걸리는 조건이 없다</span>
          }
          rows.push({
            key: v.id, r, note,
            label: <>{v.label}{r?.overlay && <span className="badge accent" style={{ marginLeft: 6 }}>수정 룰</span>}
              {i === 0 && <><br /><span className="muted small">개선 전</span></>}
              {i > 0 && improvedIn?.includes(v.id) && <><br /><span className="small" style={{ color: 'var(--accent)' }}>개선 로직</span></>}</>,
          })
        }
        const cols = [
          ...(prod ? [{ key: 'prod', label: '운영 저장 결과', r: prod }] : []),
          ...vs.data!.filter((v, i) => i === 0 || improvedIn === null || improvedIn.includes(v.id)).map((v) => ({ key: v.id, label: v.label, r: out[v.id] })),
        ]
        return (
          <div className="card" style={{ marginTop: 12 }}>
            <div className="table-wrap">
              <table style={{ tableLayout: 'fixed', minWidth: 640 }}>
                <colgroup><col style={{ width: 170 }} /><col style={{ width: 80 }} /><col style={{ width: 230 }} /><col /></colgroup>
                <thead>
                  <tr><th></th><th>판정</th><th>건수</th><th>{prod ? '운영과 비교 · ' : ''}개선 전후 차이<HelpLink to="compare" /></th></tr>
                </thead>
                <tbody>
                  {rows.map(({ key, label, r, note }) => (
                    <tr key={key}>
                      <td>{label}</td>
                      <td><VerdictBadge v={r?.verdict} /></td>
                      <td><Counts r={r} /></td>
                      <td className="small">{note}{r?.error?.where && <div className="mono muted">{r.error.where}</div>}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <ResourceMatrix cols={cols} />
          </div>
        )
      })()}
    </>
  )
}

function env(d: LocalDiag) {
  return d.env ?? (d.id.startsWith('ops__') ? 'ops' : d.id.startsWith('dev__') ? 'dev' : '')
}
