"""경로 · 환경 설정. 전부 환경변수로 덮을 수 있다."""

from __future__ import annotations

import os
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_DIR = BACKEND_DIR.parent

# 엔진 레포 — 읽기만 한다. 특정 ref 의 소스는 git archive 로 DATA_DIR/engines 에 풀어 쓴다.
ENGINE_REPO = Path(os.environ.get("RV_ENGINE_REPO", REPO_DIR.parent / "k8s-engine")).resolve()

# 고객 환경 데이터(S3 에서 받은 raw · 룰셋)와 실행 결과. 전부 .gitignore.
DATA_DIR = Path(os.environ.get("RV_DATA_DIR", REPO_DIR / "data")).resolve()
ENGINES_DIR = DATA_DIR / "engines"
DIAG_DIR = DATA_DIR / "diagnoses"
RUNS_DIR = DATA_DIR / "runs"
CASE_RESULTS_DIR = DATA_DIR / "case-results"

CATALOG_PATH = REPO_DIR / "catalog" / "findings.json"
RULE_META_PATH = REPO_DIR / "catalog" / "rule_meta.json"
CASES_DIR = BACKEND_DIR / "cases"
VARIANTS_PATH = BACKEND_DIR / "variants.json"
OVERLAYS_DIR = BACKEND_DIR / "overlays"

# S3 — 기본은 dev. 운영(ops-dclo)은 고객 데이터라 받은 파일을 레포 밖으로 옮기지 않는다.
AWS_PROFILES = [p.strip() for p in os.environ.get("RV_AWS_PROFILES", "dev-dclo,ops-dclo").split(",") if p.strip()]

for d in (ENGINES_DIR, DIAG_DIR, RUNS_DIR, CASE_RESULTS_DIR):
    d.mkdir(parents=True, exist_ok=True)
