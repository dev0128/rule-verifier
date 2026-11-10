import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api, qs, waitJob, type Job, type Variant } from '../api'
import { JobLine, Loading, useAsync } from '../ui'

type Labels = {
  tenant?: string
  company?: string | null
  key_alias?: string | null
  db_account_id?: string | null
  group_name?: string | null
  ruleset_names?: Record<string, string>
}
type LocalDiag = {
  labels?: Labels
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

type DbStatus = {
  available: Record<string, boolean>
  snapshots: Record<string, { synced_at: string; tenants: number; tenants_with_aws: number; histories: number; rules: number; errors: number } | null>
  profiles: Record<string, string | null>
}
type DbTenant = { id: string; company: string | null; alias: string | null; deleted: boolean; bucket: string | null; keys: number; histories: number; end: number; last_diag: string | null }
type DbKey = { key_id: string; alias: string | null; account_id: string | null; account_name: string | null; status: string | null; deleted: boolean; histories: number; last_diag: string | null }
type DbHist = {
  his_id: string; group_id: string; key_id: string; ruleset_id: string | null; governance: boolean; status: string
  high: number | null; medium: number | null; low: number | null; good: number | null; na: number | null; ins_dt: string | null
  group_name: string | null; group_kind: string; ruleset_name: string | null
}
type DbTenantDetail = { id: string; company: string | null; alias: string | null; bucket: string | null; keys: DbKey[]; histories: DbHist[]; ruleset_names: Record<string, string> }

const day = (s: string | null | undefined) => (s ? s.slice(0, 10) : '—')
const STATUS_KO: Record<string, string> = { end: '정상 종료', error: '오류', running: '진행 중' }

/** 고객사 → AWS 계정 → 진단을 DB 스냅샷에서 고른다. 버킷 · S3 경로는 DB 값으로 계산된다(위키 0060 매핑 사슬). */
export function DbPicker({ onDownloaded }: { onDownloaded: () => void }) {
  const status = useAsync(() => api.get<DbStatus>('/api/db/status'), [])
  const [env, setEnv] = useState('')
  const [tenants, setTenants] = useState<DbTenant[] | null>(null)
  const [tid, setTid] = useState('')
  const [detail, setDetail] = useState<DbTenantDetail | null>(null)
  const [kid, setKid] = useState('')
  const [his, setHis] = useState('')
  const [onlyEnd, setOnlyEnd] = useState(true)
  const [files, setFiles] = useState<Files | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [syncJob, setSyncJob] = useState<Job | null>(null)
  const [job, setJob] = useState<Job | null>(null)

  // 기본 환경: 스냅샷이 있는 운영 → dev 순
  useEffect(() => {
    if (status.data && !env) setEnv(status.data.snapshots.ops ? 'ops' : status.data.snapshots.dev ? 'dev' : 'ops')
  }, [status.data, env])
  useEffect(() => {
    setTenants(null); setTid(''); setDetail(null); setKid(''); setHis(''); setFiles(null)
    if (env) api.get<DbTenant[]>(`/api/db/${env}/tenants`).then(setTenants, (e) => setErr(String(e.message)))
  }, [env, status.data])

  const profile = status.data?.profiles[env] ?? ''
  const snap = status.data?.snapshots[env]

  const sync = async () => {
    setErr(null)
    try {
      const j = await api.post<Job>('/api/db/sync', { env })
      setSyncJob(j)
      const done = await waitJob(j.id, setSyncJob)
      if (done.status === 'done') status.reload()
    } catch (e) {
      setErr(String((e as Error).message))
    }
  }
  const pickTenant = async (t: string) => {
    setTid(t); setDetail(null); setKid(''); setHis(''); setFiles(null); setErr(null)
    if (!t) return
    try {
      const d = await api.get<DbTenantDetail>(`/api/db/${env}/tenants/${encodeURIComponent(t)}`)
      setDetail(d)
      if (d.keys.length === 1) setKid(d.keys[0].key_id)
    } catch (e) {
      setErr(String((e as Error).message))
    }
  }
  const pickHis = async (h: string) => {
    setHis(h); setFiles(null); setErr(null)
    const hh = detail?.histories.find((x) => x.his_id === h)
    if (!hh || !detail?.bucket) return
    setBusy(true)
    try {
      setFiles(await api.get<Files>(`/api/s3/files?${qs({ profile, bucket: detail.bucket, group: hh.group_id, key: hh.key_id, his: h })}`))
    } catch (e) {
      setErr(String((e as Error).message))
    } finally {
      setBusy(false)
    }
  }
  const download = async () => {
    const hh = detail!.histories.find((x) => x.his_id === his)!
    const k = detail!.keys.find((x) => x.key_id === hh.key_id)
    const labels: Labels = {
      tenant: detail!.id, company: detail!.company, key_alias: k?.alias, db_account_id: k?.account_id, group_name: hh.group_name,
      ruleset_names: Object.fromEntries((files?.rulesets ?? []).map((r) => [r.name, detail!.ruleset_names[r.name.replace(/\.json$/, '')]]).filter(([, v]) => v)),
    }
    const j = await api.post<Job>('/api/s3/download', { profile, bucket: detail!.bucket, group: hh.group_id, key: hh.key_id, his, labels })
    setJob(j)
    const done = await waitJob(j.id, setJob)
    if (done.status === 'done') onDownloaded()
  }

  if (!status.data) return <Loading error={status.error} loading />
  const withDiag = tenants?.filter((t) => t.histories > 0) ?? []
  const noDiag = tenants?.filter((t) => t.histories === 0) ?? []
  const tLabel = (t: DbTenant) =>
    `${t.company || '(회사명 없음)'} · ${t.id}${t.deleted ? ' (삭제)' : ''} — AWS 계정 ${t.keys} · 진단 ${t.histories}${t.last_diag ? ` · 최근 ${day(t.last_diag)}` : ''}`
  const hists = (detail?.histories ?? []).filter((h) => h.key_id === kid && (!onlyEnd || h.status === 'end'))
  const n = (v: number | null) => v ?? 0

  return (
    <div className="card">
      <div className="row">
        <label className="inline">환경
          <select value={env} onChange={(e) => setEnv(e.target.value)}>
            {['ops', 'dev'].map((e) => (
              <option key={e} value={e}>{e === 'ops' ? '운영 (ops)' : '개발 (dev)'}{status.data!.snapshots[e] ? '' : ' — 목록 없음'}</option>
            ))}
          </select>
        </label>
        <button onClick={sync} disabled={!status.data.available[env] || syncJob?.status === 'running'} title={status.data.available[env] ? 'bastion 터널을 열어 읽기 전용으로 읽고 닫는다' : 'python-tenant-helper/.env 에 접속 정보가 없다'}>
          {syncJob?.status === 'running' ? 'DB 읽는 중…' : 'DB 목록 갱신'}
        </button>
        <span className="muted small">
          {snap ? `${snap.synced_at} 기준 · 테넌트 ${snap.tenants}(AWS 진단 있음 ${snap.tenants_with_aws}) · 진단 ${snap.histories.toLocaleString()} · 룰 ${snap.rules}${snap.errors ? ` · 못 읽은 테넌트 ${snap.errors}` : ''}` : '아직 받은 목록이 없다 — DB 목록 갱신'}
        </span>
        {env === 'ops' && <span className="badge warn">운영 — 고객 데이터, 받은 파일은 data/ 밖으로 옮기지 않는다</span>}
      </div>
      <JobLine job={syncJob?.status === 'done' ? null : syncJob} />
      {tenants && tenants.length > 0 && (
        <div className="row" style={{ marginTop: 10 }}>
          <label className="inline">고객사
            <select value={tid} onChange={(e) => pickTenant(e.target.value)} style={{ maxWidth: 560 }}>
              <option value="">고객사 · 테넌트 ({withDiag.length} / 전체 {tenants.length})</option>
              <optgroup label="AWS 진단 있음 (최근 진단 순)">
                {withDiag.map((t) => <option key={t.id} value={t.id} disabled={!t.bucket}>{tLabel(t)}</option>)}
              </optgroup>
              <optgroup label="AWS 진단 없음">
                {noDiag.map((t) => <option key={t.id} value={t.id}>{tLabel(t)}</option>)}
              </optgroup>
            </select>
          </label>
        </div>
      )}
      {detail && (
        <>
          <div className="small mono muted" style={{ marginTop: 6 }}>버킷 {detail.bucket ?? '계산 불가(center_user 없음)'}</div>
          <div className="row" style={{ marginTop: 8 }}>
            <label className="inline">AWS 계정
              <select value={kid} onChange={(e) => { setKid(e.target.value); setHis(''); setFiles(null) }} style={{ maxWidth: 520 }}>
                <option value="">계정 ({detail.keys.length})</option>
                {detail.keys.map((k) => (
                  <option key={k.key_id} value={k.key_id} disabled={k.histories === 0}>
                    {k.alias || '(별칭 없음)'} · {k.account_id ?? '계정 ID 없음'} · {k.key_id}{k.deleted ? ' (삭제된 키)' : ''} — 진단 {k.histories}{k.last_diag ? ` · 최근 ${day(k.last_diag)}` : ''}
                  </option>
                ))}
              </select>
            </label>
          </div>
        </>
      )}
      {detail && kid && (
        <div className="row" style={{ marginTop: 8 }}>
          <label className="inline">진단
            <select value={his} onChange={(e) => pickHis(e.target.value)} style={{ maxWidth: 640 }}>
              <option value="">진단 ({hists.length})</option>
              {hists.map((h) => (
                <option key={h.his_id} value={h.his_id}>
                  {h.ins_dt ?? '?'} · {STATUS_KO[h.status] ?? h.status} · {h.group_kind === 'governance' ? '거버넌스' : '그룹'} {h.group_name ?? h.group_id}
                  {h.ruleset_name ? ` · ${h.ruleset_name}` : ''} · 취약 H{n(h.high)}/M{n(h.medium)}/L{n(h.low)} 양호 {n(h.good)} — {h.his_id}
                </option>
              ))}
            </select>
          </label>
          <label className="inline small"><input type="checkbox" checked={onlyEnd} onChange={(e) => setOnlyEnd(e.target.checked)} />정상 종료만</label>
          {busy && <span className="muted small">S3 확인 중…</span>}
        </div>
      )}
      {err && <div className="err" style={{ marginTop: 8 }}>{err}</div>}
      {files && (
        <div style={{ marginTop: 10 }}>
          <div className="small mono muted">{files.prefix}</div>
          <div className="small" style={{ margin: '6px 0' }}>
            컨디션 파일 {files.rulesets.length}개: {files.rulesets.map((r) => { const nm = detail?.ruleset_names[r.name.replace(/\.json$/, '')]; return nm ? `${r.name} (${nm})` : r.name }).join(', ') || '없음'}
            <br />
            수집 데이터: {files.raw ? `Raw/raw_data.json ${mb(files.raw.size)} (${files.raw.modified.slice(0, 19)})` : <span className="diff">없음</span>}
          </div>
          <button className="primary" disabled={!files.raw || job?.status === 'running'} onClick={download}>받기</button>
        </div>
      )}
      <div style={{ marginTop: 8 }}><JobLine job={job} /></div>
    </div>
  )
}

// 테넌트 root_id 는 S3 에서 목록을 얻을 수 없다(버킷 이름엔 sha1 만 있음) — 버킷을 찾았던 값을 이 브라우저에 기억해 고르게 한다
const RECENT_KEY = 'rv-recent-tenants'
function recentTenants(): string[] {
  try {
    return JSON.parse(localStorage.getItem(RECENT_KEY) ?? '[]')
  } catch {
    return []
  }
}
function rememberTenant(t: string) {
  try {
    localStorage.setItem(RECENT_KEY, JSON.stringify([t, ...recentTenants().filter((x) => x !== t)].slice(0, 20)))
  } catch {
    /* 저장 못 해도 동작에는 지장 없음 */
  }
}

function S3Browser({ onDownloaded }: { onDownloaded: () => void }) {
  const profiles = useAsync(() => api.get<string[]>('/api/s3/profiles'), [])
  const [profile, setProfile] = useState('')
  const [tenant, setTenant] = useState('')
  const [recent, setRecent] = useState(recentTenants)
  const [buckets, setBuckets] = useState<{ bucket: string; env: string; tenant?: string; company?: string | null }[] | null>(null)
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
    const t = tenant.trim()
    call(() => api.get<{ bucket: string; env: string; tenant?: string; company?: string | null }[]>(`/api/s3/buckets?${qs({ profile, tenant: t })}`), (bs) => {
      setBuckets(bs)
      if (t && bs.length) {
        rememberTenant(t)
        setRecent(recentTenants())
      }
    })
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
        <input list="rv-tenants" placeholder="테넌트 root_id (선택, 예: msp_samsungcard)" value={tenant} onChange={(e) => setTenant(e.target.value)} style={{ width: 280 }} />
        <datalist id="rv-tenants">{recent.map((t) => <option key={t} value={t} />)}</datalist>
        <button onClick={loadBuckets} disabled={busy}>버킷 찾기</button>
        {profile.startsWith('ops') && <span className="badge warn">운영 — 고객 데이터, 받은 파일은 data/ 밖으로 옮기지 않는다</span>}
      </div>
      <div className="row" style={{ marginTop: 10 }}>
        {buckets && (
          <select value={bucket} onChange={(e) => pickBucket(e.target.value)}>
            <option value="">버킷 ({buckets.length})</option>
            {buckets.map((b) => <option key={b.bucket} value={b.bucket}>{b.tenant ? `${b.company || '(회사명 없음)'} · ${b.tenant} — ` : ''}{b.bucket}</option>)}
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
            {diag.rulesets.map((r) => <option key={r} value={r}>{r}{diag.labels?.ruleset_names?.[r] ? ` — ${diag.labels.ruleset_names[r]}` : ''}</option>)}
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

      <h2>진단 고르기</h2>
      <p className="small muted" style={{ marginTop: 0 }}>
        고객사 · AWS 계정 · 진단 목록은 dev / 운영 DB 에서 받아 둔 스냅샷(<code>data/db/</code>)이다. 갱신할 때만 bastion 터널을 열어 읽기 전용으로 읽는다.
      </p>
      <DbPicker onDownloaded={local.reload} />
      <details style={{ marginTop: 8 }}>
        <summary className="small muted">S3 에서 직접 찾기 (DB 목록 없이 — 버킷 · 경로 이름만 보인다)</summary>
        <S3Browser onDownloaded={local.reload} />
      </details>

      <h2>받아 둔 진단</h2>
      <Loading error={local.error} loading={local.loading && !local.data} />
      {local.data && local.data.length === 0 && <p className="muted">아직 없다. 위에서 진단을 받거나 <code>data/diagnoses/&lt;id&gt;/</code> 에 Raw/raw_data.json 과 SET-*.json 을 넣는다.</p>}
      {local.data?.map((d) => (
        <div key={d.id} className="card" style={{ marginBottom: 8 }}>
          <div className="row">
            {d.env && <span className="badge">{d.env}</span>}
            <strong>{d.labels?.company ?? d.labels?.tenant ?? '(DB 목록에 없음)'}</strong>
            {d.labels?.tenant && <span className="mono small muted">{d.labels.tenant}</span>}
            <span>{d.labels?.key_alias ?? d.key_id ?? d.id}</span>
            <span className="mono small">{d.key_id} · {d.his_id}</span>
            <span className="muted small">
              {d.labels?.group_name ?? d.group_id} · 계정 {d.account_id ?? d.labels?.db_account_id ?? '?'} · raw {mb(d.raw_size)} · 컨디션 파일 {d.rulesets.length}개 · 수집 {d.raw_modified?.slice(0, 10) ?? '?'}
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
                  <td className="small">
                    {(() => { const l = local.data?.find((d) => d.id === r.diag)?.labels; return l?.company || l?.key_alias ? <>{l.company} · {l.key_alias}<br /></> : null })()}
                    <span className="mono muted">{r.diag}</span>
                  </td>
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
