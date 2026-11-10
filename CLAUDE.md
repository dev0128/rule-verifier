# rule-verifier 작업 규칙

- 워크스페이스 공통 규칙은 `~/dclo/CLAUDE.md`. 이 도구의 배경 · 결정은 위키 `0123-rule-verifier-tool`, 결함 원본은 `0107-aws-master-rule-bug-catalog`.
- **이 도구는 k8s-engine 에 쓰지 않는다.** 엔진 소스는 `git archive` 로 `data/engines/<sha>/` 에 풀거나, worktree 를 그대로 읽기만 한다.
- **엔진 수정은 k8s-engine 브랜치 `fix/aws-master-rules`(dev 에서 분기)에서, worktree `~/dclo/k8s-engine-fix` 로 한다.** `~/dclo/k8s-engine` 의 dev 작업 트리(미커밋 vpc.py 등)는 건드리지 않는다.
  변형 `improved` = `WORKTREE:k8s-engine-fix`(미커밋 수정까지). 고친 뒤 `./dev.sh cases` · 화면에서 비교. 커밋 · 푸시는 사용자가 요청할 때만.
- `data/` 는 고객 환경 데이터(S3 raw · 룰셋 · 운영 결과)다. 커밋 · 외부 전송 금지. 운영(`ops-dclo`) 데이터는 data/ 밖으로 옮기지 않는다.
- 결함을 새로 찾으면 `catalog/findings.json` 에 한 건 추가(id 는 다음 X 번호) — `outcome` 에 "상황 → 결과" 한 줄(40자 이내, 예: "일시 중지된 탐지기도 양호", "조건식 항상 참 → 전부 N/A")을 꼭 쓴다(메인 그리드 결과 칼럼) + `backend/cases/<id>.json` 케이스 — 형식은 `backend/cases/README.md`.
  케이스의 expect 는 **올바른 결과**다. 지금 엔진 출력에 맞추지 않는다.
- 오버레이(`backend/overlays/<이름>/`)는 엔진을 고치기 전 빠른 시험용으로만 — 확인되면 엔진 브랜치로 옮기고 지운다(`backend/overlays/README.md`).
- 바꾼 뒤 확인: `./dev.sh test` (케이스 전체가 깨지지 않는지 포함), `cd frontend && npm run build`.
- 엔진 ref(`variants.json`)를 바꾸거나 수집기 · 룰을 볼 때: `cd backend && uv run rv apiref` 로 `catalog/aws_api/` 를 다시 만든다. 룰 · 수집기가 응답에 없는 키를 읽으면 화면 "AWS API 참고" 상단에 뜬다(확인 후보).
  raw 를 손으로 쓸 때 필드 이름 · enum 은 여기(= botocore 공식 모델)를 기준으로 한다.
