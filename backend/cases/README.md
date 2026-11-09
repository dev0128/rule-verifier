# 재현 케이스 (`backend/cases/<결함ID>.json`)

결함 카탈로그(`catalog/findings.json`)의 한 건(F001~F150, X001~)을 **"이 입력(컨디션)이면 이 결과가 맞다"** 로 적은 것.
같은 케이스를 엔진 변형(현재 운영 엔진 · 개선안)마다 돌려, 기대와 다르면 결함이 재현된 것이고 기대대로면 그 변형에서는 고쳐진 것이다.

```json
{
  "finding": "F001",                 // findings.json 의 id
  "rule": "REME-0103600001",         // 대표 룰 (시나리오마다 rule/service 로 바꿀 수 있다)
  "service": "guardduty",            // 룰 함수의 4번째 인자 service_name (= service_code_func 의 키)
  "status": "reproducible",          // reproducible | not_reproducible
  "effect": "false_negative",        // (선택) 카탈로그의 effect 가 틀렸으면 바로잡는다
  "note": "근거 코드 위치와 한두 줄 설명 (예: guardduty.py:44 — Status 를 안 본다)",
  "scenarios": [
    {
      "id": "suspended",             // 케이스 안에서 유일
      "role": "bug",                 // bug | control | collection
      "condition": "사람이 읽는 입력 설명 — 화면에 그대로 나온다",
      "args": [],                    // 룰 인자. 기본 룰셋 모양 [값] / [] , 거버넌스 "" , 커스텀룰 마스터 참조 null
      "raw": {"ap-northeast-2": {"guardduty": {"get_detector": [{"DetectorId": "d1", "Status": "DISABLED"}]}}},
      "expect": {"verdict": "Vuln", "flag": 1},
      "why": "왜 이 결과가 맞는가 (항목명 · 판단기준 · AWS 동작 근거)"
    }
  ]
}
```

## 역할(role)

| role | 뜻 | 운영 엔진(baseline)에서 |
|---|---|---|
| `bug` | 결함이 드러나는 입력. **expect 는 올바른 결과** | 기대와 **달라야** 한다(= 결함 재현) |
| `control` | 정상 입력. 케이스와 하네스가 맞는지 확인용 | 기대대로 나와야 한다. 다르면 케이스가 틀린 것 |
| `collection` | 수집기가 **정보를 잃어** 지금 raw 로는 올바른 판정이 불가능한 경우(예: SQS Policy 를 `{}` 로 덮어씀). raw 는 수집기가 실제로 만드는 모양, expect 는 실제 리소스 기준의 올바른 결과 | 기대와 다르다. 룰을 고쳐도 계속 다르다 → "수집 결함" 으로 표시 |

정보가 raw 에 남아 있는 수집 결함(예: RDS `DBClusters = {}` — 값이 비었을 뿐 인스턴스 정보는 있다)은 `collection` 이 아니라 `bug` 다. 룰 쪽에서 고칠 수 있다.

## expect

| 키 | 의미 |
|---|---|
| `verdict` | `Vuln` · `Secure` · `N/A` · `ERROR` — k8s-convert `set_weak_state` 와 같은 규칙 (점검 0건 → N/A, 취약>0 → Vuln) |
| `checked` · `flag` · `good` · `na` | 건수 정확히 일치 |
| `flag_contains` · `good_contains` · `na_contains` | 그 목록의 리소스 id 중 하나에 이 문자열이 들어 있어야 함 |
| `flag_excludes` | 취약 목록에 이 문자열이 있으면 안 됨 |

`verdict` 가 `ERROR` 가 아니면 예외는 항상 기대와 다른 것으로 본다. 예외 결함의 올바른 결과는 보통 "예외 없이 판정" 이다 — 수집 실패 리소스는 `N/A` 로 빼고 나머지는 정상 판정.

## 원칙

- **expect 는 지금 엔진 출력이 아니라 올바른 결과**를 적는다. 근거는 항목명 · 판단기준(`catalog/rule_meta.json`, 결함의 summary/impact) · AWS API 문서.
- **raw 는 AWS 응답 모양 그대로**, 수집기(`AWS/Raw/Service/<서비스>.py`)가 붙이는 키까지 맞춘다. 필드명은 botocore 서비스 모델로 확인할 수 있다
  (`backend/.venv/lib/python3.12/site-packages/botocore/data/<서비스>/<버전>/service-2.json`).
- 최소 입력으로 쓴다. 리전은 `ap-northeast-2`, 글로벌 서비스(IAM · S3 · CloudFront · Route53 · WAF 등)는 `globals`.
- 재현이 안 되면(엔진이 이미 맞게 동작, 또는 결함 설명이 틀림) `status: not_reproducible` + `note` 에 이유. 억지로 맞추지 않는다.

## 기준 시각

케이스는 룰이 보는 '지금'을 **2026-11-09T00:00:00Z** 로 고정해 돌린다(`app/cases.py CASES_AS_OF`). 90일 경과 · 만료일 같은 날짜 룰도
날짜를 이 시각 기준으로 적으면 언제 돌려도 결과가 같다.

## 실행

```bash
cd backend
uv run rv cases --only F001,F002 -v      # 몇 건만, 시나리오별 실제 결과 출력 (-vv 면 리소스 id 까지)
uv run rv cases --variant baseline       # 전체 → data/case-results/baseline.json
uv run rv cases --variant improved
```
