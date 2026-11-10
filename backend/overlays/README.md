# 오버레이 — 엔진을 고치기 전에 빠르게 시험해 보는 곳

엔진 수정은 k8s-engine 브랜치 `fix/aws-master-rules`(worktree `~/dclo/k8s-engine-fix`)에서 한다.
`variants.json` 의 `improved` 변형이 그 worktree(`WORKTREE:k8s-engine-fix`)를 미커밋 수정까지 그대로 돌린다.

오버레이는 엔진 코드를 건드리기 전에 생각을 확인하는 용도로만 쓴다:

- `overlays/<이름>/*.py` 에 같은 이름의 `REME_…` 함수를 두면 원 함수를 덮어쓴다(원 모듈 이름공간을 `from AWS.Analyze.Service.<svc> import *`).
- `preprocess_raw(raw)` 를 두면 룰 실행 전에 raw 를 고친다(이미 수집된 raw 에 수집 수정을 흉내 낼 때).
- `FIXES = {"REME_…": "설명"}` 은 화면 표시용.
- 변형에 `"overlay": "<이름>"` 을 붙여 쓴다. 확인이 끝나면 엔진 브랜치로 옮기고 오버레이는 지운다.

2026-11-10 까지 쓰던 `improved/` 6건(RDS DBClusters 보정, ACM-001 · R53-007 · S3-003/004 · ECR-003)은 엔진 브랜치로 옮겼다.
