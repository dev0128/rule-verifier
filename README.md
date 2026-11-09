# rule-verifier — D-CLO AWS 기본 룰 검증 도구

진단 엔진(`k8s-engine`)의 AWS 기본(마스터) 룰을 **엔진 코드 그대로** 돌려,

1. **알려진 결함 214건**(위키 0107 · 0106)이 지금 엔진에서 실제로 재현되는지 — 결함마다 "이 입력이면 이 결과가 맞다" 는 재현 케이스로
2. **실데이터**(S3 진단 폴더의 컨디션 파일 `SET-….json` + 수집 데이터 `Raw/raw_data.json`)로 룰셋 전체를 돌리면 어떤 결과가 나오는지
3. **개선안**(고친 룰 · 수집 보정)으로 바꾸면 위 두 결과가 어떻게 달라지는지

를 한 화면에서 본다. 배경과 결정 기록은 위키 [`0123-rule-verifier-tool`](../dclo-wiki/00-common/0123-rule-verifier-tool.md).

```
./dev.sh setup     # 최초 1회 — uv sync + npm install
./dev.sh serve     # → http://127.0.0.1:8600   (FE 빌드 후 백엔드가 같이 서빙)
./dev.sh dev       # 개발 — 백엔드 8600(--reload) + Vite 5180
./dev.sh cases     # 재현 케이스 전체 × 엔진 변형 전부
./dev.sh test
```

필요한 것: Python 3.12 + [uv](https://docs.astral.sh/uv/), Node 18+, 옆 폴더의 `k8s-engine` git 레포(`RV_ENGINE_REPO` 로 바꿀 수 있다),
S3 를 쓰려면 `~/.aws/credentials` 의 `dev-dclo` / `ops-dclo` 프로파일(`RV_AWS_PROFILES`).

## 구성

```
backend/                  FastAPI + 엔진 워커 (uv, Python 3.12 — 엔진과 같은 버전)
  app/engine/worker.py    엔진 룰을 실제로 돌리는 서브프로세스. 표준 라이브러리 + 엔진 소스만 쓴다
  app/engine/source.py    엔진 변형 — k8s-engine git ref 를 git archive 로 풀어 쓴다 (엔진 레포에는 아무것도 쓰지 않음)
  app/cases.py            재현 케이스 실행 · 기대값 대조
  app/diagnosis.py        실데이터 실행 · 변형 간 비교 · 운영 실제 결과(Analyze/)와 대조
  app/s3source.py         S3 진단 폴더 탐색 · 받기
  variants.json           엔진 변형 정의 (baseline = 운영 태그, improved = 운영 + 오버레이)
  overlays/improved/      개선안 — 고친 룰 함수(REME_…) · 수집 보정(preprocess_raw)
  cases/                  재현 케이스 214개 (형식: cases/README.md)
catalog/
  findings.json           결함 카탈로그 214건 (F001~F150: 0107 전수 점검, X001~: 0107 후속 · 0106 · 고객 데이터 대조)
  rule_meta.json          룰 코드 · 항목명 · 등급
frontend/                 Vite + React + TypeScript
data/                     (.gitignore) 받은 진단 · 실행 결과 · 엔진 소스 캐시 — 고객 환경 데이터라 커밋하지 않는다
```

## 엔진과 같게 돌린다 — 그리고 그걸 확인했다

- 룰 모듈을 그대로 import 하고 DB · 설정 모듈만 가짜로 바꾼다. 룰은 `@error_handler` 를 벗긴 원 함수로 부르고, 예외가 나면
  엔진 `run_master_rule` 처럼 N/A + 사유로 남긴다.
- 실데이터 실행은 `Get_Analyze.aws_analyze_run` 과 같은 순서(service_code_func) · 같은 인자(컨디션 파일을 엔진 `setRuleData` 로 읽음) · 같은 raw 공유.
- 판정(취약/양호/N/A)은 k8s-convert `set_weak_state` 와 같은 규칙.
- 룰이 보는 '지금'을 진단 시점으로 고정한다(90일 경과 같은 날짜 룰). 재현 케이스는 2026-11-09 로 고정.
- **검증**: dev 진단 하나(AWS-00203000, Best Practice 룰셋)에서 기준 엔진 결과가 운영 엔진이 그 진단에서 남긴 `Analyze/SET-00011014.json` 과
  **149개 룰 전부 건수 · 취약 리소스 목록까지 일치**했다. 실행 결과 화면에 진단마다 이 일치율이 나온다.

다른 점: 외부 네트워크를 막는다(ECS-011 GitHub API, EKS-008 AWS 문서 → "외부망 차단" 경로). 커스텀 룰(RQL)은 Couchbase 가 필요해 돌리지 않는다(rql-helper 담당).

## 개선안 만들기

`backend/overlays/improved/*.py` 에

- 같은 이름의 `REME_…` 함수를 두면 원 함수를 덮어쓴다(원 모듈 이름공간을 `from AWS.Analyze.Service.<svc> import *` 로 가져다 쓴다).
- `preprocess_raw(raw)` 를 두면 룰 실행 전에 raw 를 고친다 — **정보가 raw 에 남아 있는 수집 결함**만 이걸로 흉내 낼 수 있다(예: RDS `DBClusters={}`).
  정보 자체가 사라진 수집 결함(예: SQS Policy 를 `{}` 로 덮어씀)은 케이스에서 `collection` 시나리오로 따로 표시되고, 재수집 전에는 개선이 안 보인다.
- `FIXES = {"REME_…": "설명"}` 은 화면 표시용.

엔진에 반영되면 `variants.json` 의 `engine_ref` 를 그 커밋(또는 브랜치)으로 바꾸고 오버레이에서 그 함수를 뺀다.
엔진 작업 브랜치를 바로 비교하려면 변형을 하나 더 추가한다: `{"id": "fix-branch", "label": "수정 브랜치", "engine_ref": "fix/rule-xxx"}`.

## 재현 케이스 상태

| 상태 | 뜻 |
|---|---|
| 결함 재현 | 결함 입력(bug) 시나리오가 올바른 결과와 다르게 나온다 |
| 수집 결함 | 룰은 맞게 판정하지만 수집 단계에서 정보가 사라져 실제 결과는 틀린다 — 수집 수정 + 재수집 필요 |
| 정상 / 개선됨 | 모든 시나리오가 기대대로 (운영에서 재현되던 것이 이 변형에서 기대대로면 "개선됨") |
| 케이스 점검 | 정상 입력(control)이 기대와 다르다 — 케이스가 틀렸다 |
| 재현 안 됨 | 케이스 작성 중 결함이 재현되지 않았다(메모에 근거) |
