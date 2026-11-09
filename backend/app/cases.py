"""재현 케이스 — 결함 하나(findings.json 의 F…/X…)를 "이 입력이면 이 결과가 맞다" 로 적은 것.

케이스 형식은 backend/cases/README.md. 여기서는 읽고 · 돌리고 · 기대값과 대조한다.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from app.config import CASES_DIR, CASE_RESULTS_DIR, CATALOG_PATH
from app.engine.runner import run_job
from app.engine.source import Variant, describe

COUNT_KEYS = ("checked", "flag", "good", "na")
# 케이스는 날짜가 흘러도 결과가 같아야 한다 — 룰이 보는 '지금'을 이 시각으로 고정한다(90일 경과 같은 날짜 룰).
CASES_AS_OF = "2026-11-09T00:00:00+00:00"
CONTAINS_KEYS = {"flag_contains": "flag_ids", "good_contains": "good_ids", "na_contains": "na_ids"}


def load_catalog() -> list[dict]:
    return json.loads(CATALOG_PATH.read_text(encoding="utf-8"))


def load_cases() -> dict[str, dict]:
    out = {}
    for p in sorted(CASES_DIR.glob("*.json")):
        c = json.loads(p.read_text(encoding="utf-8"))
        c["_file"] = p.name
        out[c["finding"]] = c
    return out


def check(expect: dict, actual: dict) -> list[str]:
    """기대와 다른 점 목록. 비면 기대대로다."""
    diffs = []
    exp_verdict = expect.get("verdict")
    if actual.get("error") and exp_verdict != "ERROR":
        e = actual["error"]
        diffs.append(f"예외 {e.get('type')}: {e.get('message', '')[:120]}")
    if exp_verdict and actual.get("verdict") != exp_verdict:
        diffs.append(f"판정 {actual.get('verdict')} (기대 {exp_verdict})")
    for k in COUNT_KEYS:
        if k in expect and actual.get(k) != expect[k]:
            diffs.append(f"{k} {actual.get(k)} (기대 {expect[k]})")
    for k, field in CONTAINS_KEYS.items():
        for needle in expect.get(k, []):
            if not any(needle in i for i in actual.get(field, [])):
                diffs.append(f"{field} 에 '{needle}' 없음")
    for needle in expect.get("flag_excludes", []):
        if any(needle in i for i in actual.get("flag_ids", [])):
            diffs.append(f"flag_ids 에 '{needle}' 있음(취약이면 안 됨)")
    return diffs


def case_status(scenarios: dict[str, dict]) -> str:
    """시나리오 결과 → 케이스 상태.

    - control 이 기대와 다르면 케이스 자체를 믿을 수 없다 → case_broken
    - bug 시나리오가 하나라도 기대와 다르면 → defect (결함이 이 엔진에서 재현된다)
    - collection 시나리오만 기대와 다르면 → collection_only (수집 단계에서 정보가 사라져 룰만으로는 못 고친다 — 수집 수정 + 재수집 필요)
    - 전부 기대대로면 → ok (이 변형에서는 결함이 없다 = 개선됨)
    """
    roles: dict[str, list[bool]] = {}
    for s in scenarios.values():
        roles.setdefault(s["role"], []).append(s["ok"])
    if not all(roles.get("control", [])):
        return "case_broken"
    if not all(roles.get("bug", [])):
        return "defect"
    if not all(roles.get("collection", [])):
        return "collection_only"
    return "ok"


def run_cases(variant: Variant, only: set[str] | None = None, save: bool = True) -> dict:
    cases = load_cases()
    if only:
        cases = {k: v for k, v in cases.items() if k in only}
    scenarios = []
    for fid, c in cases.items():
        for s in c["scenarios"]:
            scenarios.append(
                {
                    "key": f"{fid}::{s['id']}",
                    "rule": s.get("rule", c["rule"]),
                    "service": s.get("service", c.get("service")),
                    "args": s.get("args"),
                    "raw": s.get("raw", {}),
                    "preprocess": s.get("preprocess", True),
                }
            )
    t0 = time.time()
    out = run_job(variant, {"mode": "scenarios", "scenarios": scenarios, "timeout": 60, "as_of": CASES_AS_OF})
    results = out["results"]
    per_case = {}
    for fid, c in cases.items():
        sc_out = {}
        for s in c["scenarios"]:
            actual = results.get(f"{fid}::{s['id']}", {})
            diffs = check(s.get("expect", {}), actual)
            sc_out[s["id"]] = {
                "role": s.get("role", "bug"),
                "ok": not diffs,
                "diffs": diffs,
                "actual": {k: actual.get(k) for k in ("verdict", "checked", "flag", "good", "na", "flag_ids", "good_ids", "na_ids", "error", "overlay", "preprocess")},
            }
        per_case[fid] = {"status": case_status(sc_out) if c.get("status") != "not_reproducible" else "not_reproducible", "scenarios": sc_out}
    doc = {
        "variant": describe(variant),
        "ran_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "sec": round(time.time() - t0, 2),
        "worker": out["meta"],
        "cases": per_case,
    }
    if save and not only:
        (CASE_RESULTS_DIR / f"{variant.id}.json").write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    return doc


def saved_results(variant_id: str) -> dict | None:
    p = CASE_RESULTS_DIR / f"{variant_id}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def case_path(fid: str) -> Path:
    return CASES_DIR / f"{fid}.json"
