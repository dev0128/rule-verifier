import { useEffect } from 'react'
import { useLocation } from 'react-router-dom'
import { api, type Variant } from '../api'
import { CHIP_HELP, COMPARE_HELP, DEFECT_TYPE, EFFECT_HINT, EFFECT_LABEL, EFFECT_ORDER, EffectBadge, ROLE, STATUS, StatusBadge, TransitionChip, VERDICT_HELP, VerdictBadge, useAsync } from '../ui'

/** 용어 도움말 — 화면 라벨의 뜻. 라벨 정의(ui.tsx)를 그대로 읽어 그린다(여기에 따로 적지 않는다) */
export default function Help() {
  const { hash } = useLocation()
  const vs = useAsync(() => api.get<Variant[]>('/api/variants'), [])
  useEffect(() => {
    if (hash) document.getElementById(hash.slice(1))?.scrollIntoView({ block: 'start' })
  }, [hash, vs.data])
  const sel = (id: string) => (hash === `#${id}` ? { outline: '2px solid var(--accent)', outlineOffset: 2 } : undefined)

  return (
    <>
      <h1>용어 도움말</h1>
      <div className="sub">화면에 나오는 라벨의 뜻. 라벨 옆 <span className="help-link">?</span> 를 누르면 여기의 그 항목으로 온다.</div>

      <Section id="status" title="결함 상태 — 엔진마다 그 결함이 어떻게 나왔나" sel={sel}>
        <p className="small muted">결함마다 “결함이 드러나는 입력” 을 엔진(현재 운영 엔진 · 수정 브랜치)으로 돌려 올바른 결과와 비교한 결과.</p>
        <Rows rows={['defect', 'no_fix', 'improved', 'ok', 'collection_only', 'case_broken', 'not_reproducible', 'no_case', 'not_run'].map((k) => [<StatusBadge key={k} k={k} />, STATUS[k].short, STATUS[k].hint])} />
      </Section>

      <Section id="engine" title="엔진" sel={sel}>
        <Rows rows={(vs.data ?? []).map((v, i) => [<b key={v.id}>{v.label}</b>, i === 0 ? '비교 기준 — 개선 전' : '개선 후', `${v.description} (${v.engine_ref})`])} />
        <p className="small muted">
          <b>개선 로직 있음 / 없음</b> — 수정 브랜치의 그 룰 코드(룰 함수 + 그 함수가 부르는 헬퍼)가 현재 운영 엔진과 다른지로 정한다.
          없으면 결과가 운영과 똑같으므로 “결함 있음” 대신 <StatusBadge k="no_fix" /> 로 보인다. 수집기(AWS/Raw)만 고친 것은 이미 수집된 raw 결과를 바꾸지 않아 “없음” 으로 본다.
        </p>
      </Section>

      <Section id="type" title="결함 유형 — 어디가 잘못됐나" sel={sel}>
        <Rows rows={Object.entries(DEFECT_TYPE).map(([k, t]) => [<span key={k} className={`badge ${t.cls}`}>{t.label}</span>, '', t.hint])} />
      </Section>

      <Section id="effect" title="판정 영향 — 결과가 어느 쪽으로 틀리나" sel={sel}>
        <Rows rows={EFFECT_ORDER.map((k) => [<EffectBadge key={k} effect={k} />, EFFECT_LABEL[k], EFFECT_HINT[k]])} />
        <p className="small muted"><b>확신도</b> — 확실 · 중간 · 추정. 결함 카탈로그를 쓸 때 매긴 “이 결함이 맞다” 는 확신 정도(`confidence`). 근거는 결함 상세의 코드 근거 · 스파이크 재현.</p>
      </Section>

      <Section id="verdict" title="판정 — 룰 하나의 결과" sel={sel}>
        <Rows rows={VERDICT_HELP.map(([v, h]) => [<VerdictBadge key={v} v={v} />, '', h])} />
        <p className="small muted">
          <b>건수</b> — 점검 = 룰이 본 리소스 수, 취약 · 양호 · N/A = 그중 각 판정 수. <b>리소스별 판정</b> 은 리소스마다 어느 목록(취약 · 양호 · N/A)에 들어갔는지,
          엔진마다 다르면 노란 줄. 취약 밑의 글은 룰이 남긴 취약 사유.
        </p>
      </Section>

      <Section id="role" title="재현 케이스 — 결함 확인용 입력" sel={sel}>
        <p className="small muted">결함마다 손으로 쓴 최소 입력(raw)과 그 입력의 <b>올바른 결과</b>(지금 엔진 출력이 아니다). 입력 종류:</p>
        <Rows rows={Object.entries(ROLE).map(([k, r]) => [<span key={k} className={`badge ${r.cls}`}>{r.label}</span>, k, r.hint])} />
      </Section>

      <Section id="chip" title="결과 칩" sel={sel}>
        <Rows rows={CHIP_HELP.map(([t, h]) => [<TransitionChip key={t} t={t} />, '', h])} />
      </Section>

      <Section id="compare" title="입력 실험 — 결과 표" sel={sel}>
        <Rows rows={COMPARE_HELP.map(([t, w, h]) => [<b key={t}>{t}</b>, w, h])} />
      </Section>

      <Section id="terms" title="그 밖의 용어" sel={sel}>
        <Rows rows={[
          [<b key="1">raw</b>, '', '수집기가 AWS API 로 모은 응답(진단의 Raw/raw_data.json). 룰은 이것만 보고 판정한다'],
          [<b key="2">컨디션 파일</b>, '', '룰셋 — 어떤 룰을 켜고 어떤 인자(기간 등)로 돌릴지'],
          [<b key="3">운영과 같은 순서로 실행</b>, '', '운영 엔진은 같은 서비스 룰을 정해진 순서로 한 번에 돌린다. 앞 룰이 남긴 상태에 기대는 룰이 있어 켜야 운영 결과와 같아진다'],
          [<b key="4">오버레이</b>, '', '엔진을 고치기 전 빠른 시험용으로 룰 함수를 덮어쓰는 기능(지금은 엔진 브랜치에서 직접 고친다)'],
        ]} />
      </Section>
    </>
  )
}

function Section({ id, title, sel, children }: { id: string; title: string; sel: (id: string) => object | undefined; children: React.ReactNode }) {
  return (
    <div id={id} className="card" style={{ marginTop: 12, scrollMarginTop: 12, ...sel(id) }}>
      <h2 style={{ marginTop: 0 }}>{title}</h2>
      {children}
    </div>
  )
}

function Rows({ rows }: { rows: [React.ReactNode, string, string][] }) {
  return (
    <table className="small" style={{ tableLayout: 'fixed' }}>
      <colgroup><col style={{ width: 200 }} /><col style={{ width: 260 }} /><col /></colgroup>
      <tbody>
        {rows.map(([a, b, c], i) => (
          <tr key={i}><td>{a}</td><td>{b}</td><td className="muted">{c}</td></tr>
        ))}
      </tbody>
    </table>
  )
}
