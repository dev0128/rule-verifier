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


def test_rules_endpoint_lists_engine_rules():
    from fastapi.testclient import TestClient

    from app.main import app

    d = TestClient(app).get("/api/rules").json()
    assert d["error"] is None
    by = {r["rule"]: r for r in d["rules"]}
    assert by["REME-0100100001"]["service"] == "iam" and by["REME-0100100001"]["code"] == "AWS-IAM-001"
    assert "guardduty" in d["services"]


def test_db_snapshot_lookup(tmp_path, monkeypatch):
    """DB 스냅샷 → 고객사 · 계정 · 진단 선택지와 받아 둔 진단 라벨. DB 접속 없이 스냅샷 파일만으로."""
    import json

    from app import dbcatalog

    monkeypatch.setattr(dbcatalog, "DB_DIR", tmp_path)
    dbcatalog._CACHE.clear()
    snap = {
        "env": "dev", "synced_at": "2026-11-10 00:00:00", "rules": {}, "errors": {},
        "master_rulesets": {"SET-00011014": "D-CLO Best Practice"},
        "tenants": [{
            "id": "acme", "company": "에이크미", "alias": "acme", "deleted": False, "bucket": "dclo-dev-1-abc",
            "keys": {"AWS-1": {"alias": "prod", "account_id": "111122223333", "account_name": None, "status": "Y", "deleted": False}},
            "groups": {"GOVERNANCE-9": {"name": "보안 점검", "kind": "governance"}},
            "rulesets": {},
            "histories": [{"his_id": "DIAG-2", "group_id": "GOVERNANCE-9", "key_id": "AWS-1", "ruleset_id": None, "governance": True,
                           "status": "end", "high": 1, "medium": 0, "low": 0, "good": 3, "na": 0, "ins_dt": "2026-11-09 01:00"}],
            "last_diag": "2026-11-09 01:00", "status_count": {"end": 1},
        }],
    }
    (tmp_path / "dev.json").write_text(json.dumps(snap), encoding="utf-8")
    assert dbcatalog.tenant_list("dev")[0]["company"] == "에이크미"
    d = dbcatalog.tenant_detail("dev", "acme")
    assert d["keys"][0]["histories"] == 1 and d["histories"][0]["group_name"] == "보안 점검"
    lab = dbcatalog.labels_for({"env": "dev", "bucket": "dclo-dev-1-abc", "key_id": "AWS-1", "group_id": "GOVERNANCE-9", "rulesets": ["SET-00011014.json"]})
    assert lab["company"] == "에이크미" and lab["key_alias"] == "prod" and lab["ruleset_names"] == {"SET-00011014.json": "D-CLO Best Practice"}
    assert dbcatalog.labels_for({"env": "dev", "bucket": "dclo-dev-2-zzz"}) == {}


def test_apiref_catalog():
    """catalog/aws_api (`rv apiref` 결과) — 엔진 API ↔ 공식 모델 연결과, 알려진 결함을 '모델에 없는 키' 로 잡는지."""
    from app import apiref

    idx = apiref.load_index()
    assert idx, "catalog/aws_api 없음 — uv run rv apiref"
    assert "guardduty.GetDetector" in idx["raw"]["guardduty"]["get_detector"]["ops"]
    r = idx["rules"]["REME-0103600001"]
    assert r["operations"] == ["guardduty.GetDetector", "guardduty.ListDetectors"]  # list_detectors → get_detector
    # 0107 F046 — EKS-006 이 존재하지 않는 IpPermissionsIngress 를 읽는다
    assert "IpPermissionsIngress" in idx["rules"]["REME-0105900006"]["unknown_fields"]
    # 0107 F082 — 수집기가 list_response_plans 응답 요약의 arn 을 Arn 으로 읽는다
    assert any(c["function"] == "list_response_plans" and "Arn" in c["unknown_fields"] for c in idx["collector_unknown"])
    # 위키 0123 — botocore 1.37.2 는 Athena ManagedQueryResultsConfiguration 을 버린다
    ath = apiref.load_service("athena")["athena.GetWorkGroup"]
    assert "WorkGroup.Configuration.ManagedQueryResultsConfiguration" in ath["added_in_latest"]
    assert ath["urls"]["aws"].startswith("https://docs.aws.amazon.com/goto/WebAPI/athena-")


def test_realdata_slice(tmp_path, monkeypatch):
    """실데이터 잘라 오기 — 룰이 읽는 키만, 리전 키는 전부 유지, 인자는 컨디션 파일, 엔진 순서의 앞 룰. 가짜 진단으로."""
    import json

    from app import realdata, s3source

    d = tmp_path / "dev__AWS-1__DIAG-1"
    (d / "Raw").mkdir(parents=True)
    raw = {"raw": {
        "ap-northeast-2": {"guardduty": {"get_detector": [{"DetectorId": "d1", "Status": "ENABLED"}]}, "s3": {"list_buckets": [{"Name": "b"}]}},
        "us-east-1": {"s3": {"list_buckets": []}},
    }}
    (d / "Raw" / "raw_data.json").write_text(json.dumps(raw), encoding="utf-8")
    rules = {"REME-0103600001": [{"args": [], "enabled": True, "level": "Low"}], "REME-X": [{"args": ["1"], "enabled": True}],
             "REME-Y": [{"args": [], "enabled": False}]}
    (d / "SET-1.json").write_text(json.dumps({"ruleset_name": "t", "rules": rules}), encoding="utf-8")
    monkeypatch.setattr(s3source, "DIAG_DIR", tmp_path)
    realdata._RAW_CACHE.clear()

    sl = realdata.slice_for_rule(d.name, "REME-0103600001")
    assert sl["raw"] == {"ap-northeast-2": {"guardduty": raw["raw"]["ap-northeast-2"]["guardduty"]}, "us-east-1": {}}  # s3 는 빠지고 리전 키는 남는다
    assert realdata.ruleset_entry(d.name, "SET-1.json", "REME-0103600001")["args"] == []
    order = [("REME-X", "guardduty"), ("REME-Y", "guardduty"), ("REME-Z", "s3"), ("REME-0103600001", "guardduty")]
    assert realdata.pre_rules(d.name, "SET-1.json", "REME-0103600001", order) == [{"rule": "REME-X", "args": ["1"], "service": "guardduty"}]


def test_every_finding_has_outcome():
    """메인 그리드의 '결과' 칼럼 — 결함마다 한 줄(40자 이내)로 어떤 상황에서 어떤 결과가 나오는지."""
    for f in load_catalog():
        assert f.get("outcome"), f["id"]
        assert len(f["outcome"]) <= 40, (f["id"], f["outcome"])
