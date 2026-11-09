import { api, type Variant } from '../api'
import { Loading, useAsync } from '../ui'

export default function Variants() {
  const vs = useAsync(() => api.get<Variant[]>('/api/variants'), [])
  if (!vs.data) return <Loading error={vs.error} loading />
  return (
    <>
      <h1>엔진 변형</h1>
      <div className="sub">
        같은 입력을 어떤 엔진으로 돌릴지. <code>backend/variants.json</code> 에서 정한다 — k8s-engine 의 git ref(태그·브랜치·커밋, <code>WORKTREE</code> 면 작업 트리) + 이 레포의 오버레이(고친 룰 함수 · 수집 보정).
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
            <div>커밋</div>
            <div>{v.engine?.subject ?? v.engine?.error ?? '—'}</div>
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
