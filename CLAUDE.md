# rule-verifier 작업 규칙

- 워크스페이스 공통 규칙은 `~/dclo/CLAUDE.md`. 이 도구의 배경 · 결정은 위키 `0123-rule-verifier-tool`, 결함 원본은 `0107-aws-master-rule-bug-catalog`.
- **k8s-engine 레포에는 쓰지 않는다.** 엔진 소스는 `git archive` 로 `data/engines/<sha>/` 에 풀어 읽기만 한다.
- `data/` 는 고객 환경 데이터(S3 raw · 룰셋 · 운영 결과)다. 커밋 · 외부 전송 금지. 운영(`ops-dclo`) 데이터는 data/ 밖으로 옮기지 않는다.
- 결함을 새로 찾으면 `catalog/findings.json` 에 한 건 추가(id 는 다음 X 번호) + `backend/cases/<id>.json` 케이스 — 형식은 `backend/cases/README.md`.
  케이스의 expect 는 **올바른 결과**다. 지금 엔진 출력에 맞추지 않는다.
- 룰을 고쳐 보려면 `backend/overlays/improved/` 에 같은 이름의 `REME_…` 함수. 엔진에 반영되면 `variants.json` 의 `engine_ref` 를 바꾸고 오버레이에서 뺀다.
- 바꾼 뒤 확인: `./dev.sh test` (케이스 전체가 깨지지 않는지 포함), `cd frontend && npm run build`.
