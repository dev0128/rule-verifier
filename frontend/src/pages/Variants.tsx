import { api, type Variant } from '../api'
import { Loading, useAsync } from '../ui'

export default function Variants() {
  const vs = useAsync(() => api.get<Variant[]>('/api/variants'), [])
  if (!vs.data) return <Loading error={vs.error} loading />
  return (
    <>
      <h1>엔진 변형</h1>
      <div className="sub">
        같은 입력을 어떤 엔진으로 돌릴지. <code>backend/variants.json</code> 에서 정한다 — k8s-engine 의 git ref(태그·브랜치·커밋) 또는 <code>WORKTREE:경로</code>(그 worktree 를 미커밋 수정까지 그대로) + 선택적으로 이 레포의 오버레이(빠른 시험용).
        엔진 수정은 브랜치 <code>fix/aws-master-rules</code> — worktree <code>~/dclo/k8s-engine-fix</code> 에서 한다.
      </div>
      {vs.data.map((v) => (
        <div key={v.id} className="card" style={{ marginBottom: 12 }}>
          <div className="row">
            <h2 style={{ margin: 0 }}>{v.label}</h2>
            <span className="badge mono">{v.id}</span>
          </div>
          <p className="muted">{v.description}</p>
          <div className="kv small">
            <div>엔진 ref</div>
            <div className="mono">
              {v.engine_ref} {v.engine?.sha && `→ ${v.engine.sha}`} {v.engine?.dirty && <span className="badge warn">미커밋 변경 포함</span>}
            </div>
            {v.engine?.branch && <><div>브랜치</div><div className="mono">{v.engine.branch} <span className="muted">({v.engine.path})</span></div></>}
            <div>커밋</div>
            <div>{v.engine?.subject ?? v.engine?.error ?? '—'}</div>
            {!!v.engine?.changed_files?.length && (
              <><div>미커밋 파일</div><div className="mono">{v.engine.changed_files.map((f) => <div key={f}>{f}</div>)}</div></>
            )}
            <div>오버레이</div>
            <div className="mono">{v.overlay ? `backend/overlays/${v.overlay}/` : '없음'}</div>
          </div>
          {!!v.overlay_rules?.length && (
            <div className="table-wrap" style={{ marginTop: 10 }}>
              <table>
                <thead>
                  <tr><th>파일</th><th>바꾸는 것</th><th>설명</th></tr>
                </thead>
                <tbody>
                  {v.overlay_rules.map((r) => (
                    <tr key={`${r.file}:${r.function}`}>
                      <td className="mono small nowrap">{r.file}:{r.line}</td>
                      <td className="mono small nowrap">{r.rule ?? '수집 보정 (preprocess_raw)'}</td>
                      <td className="small">{r.note}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      ))}
    </>
  )
}
