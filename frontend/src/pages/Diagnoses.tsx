import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api, qs, waitJob, type Job, type Variant } from '../api'
import { JobLine, Loading, useAsync } from '../ui'

type LocalDiag = {
  id: string
  profile?: string
  env?: string
  bucket?: string
  group_id?: string
  key_id?: string
  his_id?: string
  rulesets: string[]
  raw_size: number
  raw_modified?: string
  account_id?: string | null
  downloaded_at?: string
}
type RunRow = {
  id: string
  created: string
  diag: string
  ruleset: string
  ruleset_name?: string
  args_override?: string
  summary: { variants: Record<string, { label: string; verdicts: Record<string, number>; errors: number; changed_rules?: number }>; production?: { available: boolean; same?: number; rules?: number } }
}
type Files = { prefix: string; rulesets: { name: string; size: number }[]; raw: { size: number; modified: string } | null }

const mb = (n: number) => `${(n / 1024 / 1024).toFixed(1)} MB`

function S3Browser({ onDownloaded }: { onDownloaded: () => void }) {
  const profiles = useAsync(() => api.get<string[]>('/api/s3/profiles'), [])
  const [profile, setProfile] = useState('')
  const [tenant, setTenant] = useState('')
  const [buckets, setBuckets] = useState<{ bucket: string; env: string }[] | null>(null)
  const [bucket, setBucket] = useState('')
  const [groups, setGroups] = useState<string[] | null>(null)
  const [group, setGroup] = useState('')
  const [keys, setKeys] = useState<string[] | null>(null)
  const [key, setKey] = useState('')
  const [hists, setHists] = useState<{ his_id: string; date: string | null }[] | null>(null)
  const [his, setHis] = useState('')
  const [files, setFiles] = useState<Files | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [job, setJob] = useState<Job | null>(null)

  useEffect(() => {
    if (profiles.data && !profile) setProfile(profiles.data[0])
  }, [profiles.data, profile])

  const call = async <T,>(fn: () => Promise<T>, set: (v: T) => void) => {
    setErr(null)
    setBusy(true)
    try {
      set(await fn())
    } catch (e) {
      setErr(String((e as Error).message))
    } finally {
      setBusy(false)
    }
  }
  const loadBuckets = () => {
    setBucket(''); setGroups(null); setKeys(null); setHists(null); setFiles(null)
    call(() => api.get<{ bucket: string; env: string }[]>(`/api/s3/buckets?${qs({ profile, tenant })}`), setBuckets)
  }
  const pickBucket = (b: string) => {
    setBucket(b); setGroup(''); setKeys(null); setHists(null); setFiles(null)
    if (b) call(() => api.get<string[]>(`/api/s3/groups?${qs({ profile, bucket: b })}`), setGroups)
  }
  const pickGroup = (g: string) => {
    setGroup(g); setKey(''); setHists(null); setFiles(null)
    if (g) call(() => api.get<string[]>(`/api/s3/keys?${qs({ profile, bucket, group: g })}`), setKeys)
  }
  const pickKey = (k: string) => {
    setKey(k); setHis(''); setFiles(null)
    if (k) call(() => api.get<{ his_id: string; date: string | null }[]>(`/api/s3/histories?${qs({ profile, bucket, group, key: k })}`), setHists)
  }
  const pickHis = (h: string) => {
    setHis(h); setFiles(null)
    if (h) call(() => api.get<Files>(`/api/s3/files?${qs({ profile, bucket, group, key, his: h })}`), setFiles)
  }
  const download = async () => {
    const j = await api.post<Job>('/api/s3/download', { profile, bucket, group, key, his })
    setJob(j)
    const done = await waitJob(j.id, setJob)
    if (done.status === 'done') onDownloaded()
  }

  if (!profiles.data) return <Loading error={profiles.error} loading />
  return (
    <div className="card">
      <div className="row">
        <select value={profile} onChange={(e) => setProfile(e.target.value)}>
          {profiles.data.map((p) => <option key={p}>{p}</option>)}
        </select>
        <input placeholder="테넌트 root_id (선택, 예: msp_samsungcard)" value={tenant} onChange={(e) => setTenant(e.target.value)} style={{ width: 280 }} />
        <button onClick={loadBuckets} disabled={busy}>버킷 찾기</button>
        {profile.startsWith('ops') && <span className="badge warn">운영 — 고객 데이터, 받은 파일은 data/ 밖으로 옮기지 않는다</span>}
      </div>
      <div className="row" style={{ marginTop: 10 }}>
        {buckets && (
          <select value={bucket} onChange={(e) => pickBucket(e.target.value)}>
            <option value="">버킷 ({buckets.length})</option>
            {buckets.map((b) => <option key={b.bucket} value={b.bucket}>{b.bucket}</option>)}
          </select>
        )}
        {groups && (
          <select value={group} onChange={(e) => pickGroup(e.target.value)}>
            <option value="">그룹/거버넌스 ({groups.length})</option>
            {groups.map((g) => <option key={g}>{g}</option>)}
          </select>
        )}
        {keys && (
          <select value={key} onChange={(e) => pickKey(e.target.value)}>
            <option value="">키 ({keys.length})</option>
            {keys.map((k) => <option key={k}>{k}</option>)}
          </select>
        )}
        {hists && (
          <select value={his} onChange={(e) => pickHis(e.target.value)}>
            <option value="">진단 ({hists.length})</option>
            {hists.map((h) => <option key={h.his_id} value={h.his_id}>{h.his_id}{h.date ? ` (${h.date})` : ''}</option>)}
          </select>
        )}
        {busy && <span className="muted small">조회 중…</span>}
      </div>
      {err && <div className="err" style={{ marginTop: 8 }}>{err}</div>}
      {files && (
        <div style={{ marginTop: 10 }}>
          <div className="small mono muted">{files.prefix}</div>
          <div className="small" style={{ margin: '6px 0' }}>
            컨디션 파일 {files.rulesets.length}개: {files.rulesets.map((r) => r.name).join(', ') || '없음'}
            <br />
            수집 데이터: {files.raw ? `Raw/raw_data.json ${mb(files.raw.size)} (${files.raw.modified.slice(0, 19)})` : <span className="diff">없음</span>}
          </div>
          <button className="primary" disabled={!files.raw || job?.status === 'running'} onClick={download}>
            받기
          </button>
        </div>
      )}
      <div style={{ marginTop: 8 }}><JobLine job={job} /></div>
    </div>
  )
}

function RunForm({ diag, variants, onDone }: { diag: LocalDiag; variants: Variant[]; onDone: (runId: string) => void }) {
  const modes = useAsync(() => api.get<Record<string, string>>('/api/runs/args-modes'), [])
  const [ruleset, setRuleset] = useState(diag.rulesets[0] ?? '')
  const [picked, setPicked] = useState(variants.map((v) => v.id))
  const [mode, setMode] = useState('')
  const [job, setJob] = useState<Job | null>(null)
  const rs = useAsync(
    () => (ruleset ? api.get<{ ruleset_name: string; rules: { enabled: boolean; rule: string }[] }>(`/api/diagnoses/${diag.id}/rulesets/${ruleset}`) : Promise.resolve(null)),
    [diag.id, ruleset],
  )
  const go = async () => {
    const j = await api.post<Job>('/api/runs', { diag: diag.id, ruleset, variants: picked, args_override: mode })
    setJob(j)
    const done = await waitJob(j.id, setJob)
    if (done.status === 'done' && done.result?.run_id) onDone(done.result.run_id)
  }
  const enabled = rs.data?.rules.filter((r) => r.enabled) ?? []
  return (
    <div className="card" style={{ marginTop: 8 }}>
      <div className="row">
        <label className="inline">컨디션 파일
          <select value={ruleset} onChange={(e) => setRuleset(e.target.value)}>
            {diag.rulesets.map((r) => <option key={r}>{r}</option>)}
          </select>
        </label>
        {rs.data && (
          <span className="muted small">
            {rs.data.ruleset_name} · 활성 룰 {enabled.length}개 (커스텀 {enabled.filter((r) => r.rule.startsWith('CUSTOM-RULE-')).length}개는 실행 안 함)
          </span>
        )}
      </div>
      <div className="row" style={{ marginTop: 8 }}>
        엔진:
        {variants.map((v) => (
          <label key={v.id} className="inline">
            <input
              type="checkbox"
              checked={picked.includes(v.id)}
              disabled={v.id === variants[0].id}
              onChange={(e) => setPicked(e.target.checked ? variants.filter((x) => picked.includes(x.id) || x.id === v.id).map((x) => x.id) : picked.filter((x) => x !== v.id))}
            />
            {v.label}
          </label>
        ))}
        <label className="inline">인자
          <select value={mode} onChange={(e) => setMode(e.target.value)}>
            {Object.entries(modes.data ?? { '': '컨디션 파일 그대로' }).map(([k, l]) => <option key={k} value={k}>{l}</option>)}
          </select>
        </label>
        <div className="spacer" />
        <button className="primary" onClick={go} disabled={job?.status === 'running' || !ruleset}>실행</button>
      </div>
      <div style={{ marginTop: 6 }}><JobLine job={job} /></div>
    </div>
  )
}

export default function Diagnoses() {
  const local = useAsync(() => api.get<LocalDiag[]>('/api/diagnoses'), [])
  const runs = useAsync(() => api.get<RunRow[]>('/api/runs'), [])
  const vs = useAsync(() => api.get<Variant[]>('/api/variants'), [])
  const [open, setOpen] = useState<string | null>(null)
  const nav = useNavigate()

  const del = async (id: string) => {
    if (!confirm(`${id} 의 받은 파일을 지울까요?`)) return
    await api.del(`/api/diagnoses/${id}`)
    local.reload()
  }

  return (
    <>
      <h1>실데이터 실행</h1>
      <div className="sub">
        S3 진단 폴더에서 <b>컨디션 파일</b>(룰셋 <code>SET-….json</code> — 룰별 인자·활성·등급)과 <b>수집 데이터</b>(<code>Raw/raw_data.json</code>)를 받아,
        엔진과 같은 순서·인자로 룰셋 전체를 엔진 변형마다 돌린다. 기준 시각은 진단 시점으로 고정하고, 운영 엔진이 그 진단에서 남긴 결과(<code>Analyze/</code>)와도 대조한다.
      </div>

      <h2>S3 에서 받기</h2>
      <S3Browser onDownloaded={local.reload} />

      <h2>받아 둔 진단</h2>
      <Loading error={local.error} loading={local.loading && !local.data} />
      {local.data && local.data.length === 0 && <p className="muted">아직 없다. 위에서 진단을 받거나 <code>data/diagnoses/&lt;id&gt;/</code> 에 Raw/raw_data.json 과 SET-*.json 을 넣는다.</p>}
      {local.data?.map((d) => (
        <div key={d.id} className="card" style={{ marginBottom: 8 }}>
          <div className="row">
            <strong className="mono">{d.key_id ?? d.id}</strong>
            <span className="mono small">{d.his_id}</span>
            {d.env && <span className="badge">{d.env}</span>}
            <span className="muted small">
              {d.group_id} · 계정 {d.account_id ?? '?'} · raw {mb(d.raw_size)} · 컨디션 파일 {d.rulesets.length}개 · 수집 {d.raw_modified?.slice(0, 10) ?? '?'}
            </span>
            <div className="spacer" />
            <button onClick={() => setOpen(open === d.id ? null : d.id)}>{open === d.id ? '닫기' : '실행…'}</button>
            <button onClick={() => del(d.id)}>지우기</button>
          </div>
          {open === d.id && vs.data && <RunForm diag={d} variants={vs.data} onDone={(id) => nav(`/runs/${id}`)} />}
        </div>
      ))}

      <h2>실행 기록</h2>
      {runs.data && runs.data.length === 0 && <p className="muted">없음</p>}
      {runs.data && runs.data.length > 0 && (
        <div className="table-wrap">
          <table>
            <thead>
              <tr><th>시각</th><th>진단</th><th>컨디션 파일</th><th>인자</th><th>운영 결과 일치</th>{vs.data?.map((v) => <th key={v.id}>{v.label}</th>)}</tr>
            </thead>
            <tbody>
              {runs.data.map((r) => (
                <tr key={r.id} className="click" onClick={() => nav(`/runs/${r.id}`)}>
                  <td className="nowrap small">{r.created}</td>
                  <td className="mono small">{r.diag}</td>
                  <td className="small">{r.ruleset} {r.ruleset_name && <span className="muted">({r.ruleset_name})</span>}</td>
                  <td className="small">{r.args_override || '그대로'}</td>
                  <td className="small">{r.summary.production?.available ? `${r.summary.production.same}/${r.summary.production.rules}` : '—'}</td>
                  {vs.data?.map((v) => {
                    const s = r.summary.variants[v.id]
                    return (
                      <td key={v.id} className="small nowrap">
                        {s ? <>취약 {s.verdicts.Vuln ?? 0} · 양호 {s.verdicts.Secure ?? 0} · N/A {s.verdicts['N/A'] ?? 0}{s.errors ? ` · 예외 ${s.errors}` : ''}{s.changed_rules != null && <> · <b>변경 {s.changed_rules}</b></>}</> : '—'}
                      </td>
                    )
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <p className="small muted"><Link to="/variants">엔진 변형 설정 보기</Link></p>
    </>
  )
}
