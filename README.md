# rule-verifier — D-CLO AWS 기본 룰 검증 도구

진단 엔진(`k8s-engine`)의 AWS 기본(마스터) 룰을 **엔진 코드 그대로** 돌려,

1. **알려진 결함 214건**(위키 0107 · 0106)이 지금 엔진에서 실제로 재현되는지 — 결함마다 "이 입력이면 이 결과가 맞다" 는 재현 케이스로
2. **실데이터**(S3 진단 폴더의 컨디션 파일 `SET-….json` + 수집 데이터 `Raw/raw_data.json`)로 룰셋 전체를 돌리면 어떤 결과가 나오는지
3. **개선안**(고친 룰 · 수집 보정)으로 바꾸면 위 두 결과가 어떻게 달라지는지

를 한 화면에서 본다. 배경과 결정 기록은 위키 [`0123-rule-verifier-tool`](../dclo-wiki/00-common/0123-rule-verifier-tool.md).

```
./dev.sh setup     # 최초 1회 — uv sync + npm install
./dev.sh serve     # → http://127.0.0.1:8600   (FE 빌드 후 백엔드가 같이 서빙. 포트를 쥔 이전 서버는 먼저 종료)
./dev.sh dev       # 개발 — 백엔드 8600(--reload) + Vite 5180
./dev.sh cases     # 재현 케이스 전체 × 엔진 변형 전부
./dev.sh test
cd backend && uv run rv apiref   # 엔진이 부르는 AWS API 참고 자료 → catalog/aws_api/ (엔진 ref 를 바꾸면 다시)
```

필요한 것: Python 3.12 + [uv](https://docs.astral.sh/uv/), Node 18+, 옆 폴더의 `k8s-engine` git 레포(`RV_ENGINE_REPO` 로 바꿀 수 있다),
S3 를 쓰려면 `~/.aws/credentials` 의 `dev-dclo` / `ops-dclo` 프로파일(`RV_AWS_PROFILES`).
고객사 · 계정 · 진단 · 룰 목록(DB 스냅샷)을 받으려면 `python-tenant-helper/.env` 의 `*_DEV` / `*_OPS` 접속 정보와 bastion SSH 키(`RV_DB_ENV_FILE` 로 다른 파일 지정).

## 구성

```
backend/                  FastAPI + 엔진 워커 (uv, Python 3.12 — 엔진과 같은 버전)
  app/engine/worker.py    엔진 룰을 실제로 돌리는 서브프로세스. 표준 라이브러리 + 엔진 소스만 쓴다
  app/engine/source.py    엔진 변형 — k8s-engine git ref 를 git archive 로 풀어 쓴다 (엔진 레포에는 아무것도 쓰지 않음)
  app/cases.py            재현 케이스 실행 · 기대값 대조
  app/diagnosis.py        실데이터 실행 · 변형 간 비교 · 운영 실제 결과(Analyze/)와 대조
  app/s3source.py         S3 진단 폴더 탐색 · 받기
  app/dbconn.py           dev / 운영 DB 읽기 전용 접속 — bastion 터널을 그때만 열고 닫는다
  app/apiref.py           엔진 수집기 · 룰 AST 분석 + botocore 공식 API 모델 → catalog/aws_api/ (화면 "AWS API 참고")
  app/dbcatalog.py        DB 스냅샷(data/db/<env>.json) — 고객사 · 버킷 · AWS 계정 · 그룹/거버넌스 · 진단 · 마스터 룰
  variants.json           엔진 변형 정의 (baseline = 운영 태그, improved = 운영 + 오버레이)
  overlays/               빠른 시험용 오버레이(고친 룰 함수 · 수집 보정) — 엔진 수정은 k8s-engine 브랜치에서 (overlays/README.md)
  cases/                  재현 케이스 214개 (형식: cases/README.md)
catalog/
  findings.json           결함 카탈로그 214건 (F001~F150: 0107 전수 점검, X001~: 0107 후속 · 0106 · 고객 데이터 대조)
  rule_meta.json          룰 코드 · 항목명 · 등급
  aws_api/                엔진이 부르는 AWS API 356개의 응답 구조 · enum · 공식 설명 · 문서 링크, 룰 ↔ raw 키 ↔ API 연결 (`rv apiref` 생성물)
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

## 개선안 만들기 — 엔진 브랜치에서

엔진 수정은 **k8s-engine 브랜치 `fix/aws-master-rules`**(dev 에서 분기)에서, 별도 worktree `~/dclo/k8s-engine-fix` 로 한다
(`~/dclo/k8s-engine` 의 dev 작업 트리는 그대로 둔다).

```bash
git -C ~/dclo/k8s-engine worktree add -b fix/aws-master-rules ~/dclo/k8s-engine-fix dev   # 처음 한 번
# ~/dclo/k8s-engine-fix/src/AWS/... 를 고친다
./dev.sh cases          # 변형 improved = WORKTREE:k8s-engine-fix — 미커밋 수정까지 바로 돈다
```

- `variants.json` 의 `engine_ref` 는 git ref(태그 · 브랜치 · 커밋 — 커밋된 것만) 또는 `WORKTREE:<경로>`(worktree 를 미커밋까지).
  다른 브랜치를 나란히 보려면 변형을 하나 더: `{"id": "fix2", "label": "…", "engine_ref": "fix/rule-xxx"}`.
- 이미 수집된 raw(고객 데이터 · 케이스)로 결과를 보므로 **수집 결함은 룰 쪽에서도 견디게** 고친다(예: RDS 단독 인스턴스 — 수집기는 `DBClusters={}` 를 안 넣게, 룰은 빈 값도 단독으로).
- 엔진을 고치기 전에 생각만 빨리 확인하려면 오버레이(`backend/overlays/README.md`).

## 재현 케이스 상태

| 상태 | 뜻 |
|---|---|
| 결함 있음 | 결함이 드러나는 입력(bug 시나리오)을 이 엔진으로 돌리면 올바른 결과와 다르게 나온다 — 아직 안 고쳐짐 |
| 개선됨 | 현재 운영 엔진은 틀리던 입력을 이 엔진은 올바르게 판정한다 |
| 결함 없음 | 케이스의 모든 입력이 올바른 결과대로 나온다 |
| 수집 문제 | 룰은 맞게 판정하지만 수집 단계에서 정보가 빠져 실제 결과는 틀린다 — 수집기 수정 + 재수집 필요 |
| 케이스 오류 | 정상 입력(control)부터 올바른 결과와 다르다 — 결함이 아니라 케이스가 틀렸다 |
| 결함 확인 안 됨 | 케이스 작성 중 결함이 실제로 나타나지 않았다(메모에 근거) |
