"""하네스 자체 검증 — 엔진 ref 가 풀리고, 케이스 판정 규칙이 맞고, 전 케이스가 깨지지 않는지."""

from app.cases import case_status, check, load_cases, load_catalog, run_cases
from app.engine.source import get_variant


def test_every_finding_has_case():
    cat = {f["id"] for f in load_catalog()}
    cases = load_cases()
    assert cat == set(cases)
    for fid, c in cases.items():
        assert c["finding"] == fid
        for s in c["scenarios"]:
            assert s["role"] in ("bug", "control", "collection"), (fid, s["id"])


def test_check_rules():
    actual = {"verdict": "Secure", "checked": 1, "flag": 0, "good": 1, "na": 0, "flag_ids": [], "good_ids": ["r.s.t.a"], "error": None}
    assert check({"verdict": "Secure", "good": 1, "good_contains": ["t.a"]}, actual) == []
    assert check({"verdict": "Vuln"}, actual)
    assert check({"verdict": "N/A"}, {**actual, "verdict": "ERROR", "error": {"type": "KeyError", "message": "x"}})


def test_case_status_rules():
    ok = lambda role, v: {"role": role, "ok": v}  # noqa: E731
    assert case_status({"a": ok("bug", False), "b": ok("control", True)}) == "defect"
    assert case_status({"a": ok("bug", True), "b": ok("collection", False)}) == "collection_only"
    assert case_status({"a": ok("bug", True), "b": ok("control", False)}) == "case_broken"
    assert case_status({"a": ok("bug", True), "b": ok("control", True)}) == "ok"


def test_baseline_has_no_broken_case():
    doc = run_cases(get_variant("baseline"), save=False)
    broken = [fid for fid, r in doc["cases"].items() if r["status"] == "case_broken"]
    assert not broken, broken
    # 운영 엔진에서는 재현 안 됨(not_reproducible) 으로 표시한 것 외에는 결함이 재현돼야 한다
    ok = [fid for fid, r in doc["cases"].items() if r["status"] == "ok"]
    assert not ok, ok


def test_improved_never_breaks_controls():
    doc = run_cases(get_variant("improved"), save=False)
    broken = [fid for fid, r in doc["cases"].items() if r["status"] == "case_broken"]
    assert not broken, broken
