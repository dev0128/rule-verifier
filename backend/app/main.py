"""rule-verifier API."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app import apiref, dbcatalog, dbconn, jobs, realdata, s3source
from app.cases import check, load_cases, load_catalog, run_cases, saved_results
from app.config import AWS_PROFILES, REPO_DIR, RULE_META_PATH
from app.diagnosis import ARGS_MODES, get_run, list_runs, run_diagnosis
from app.engine.runner import run_job
from app.engine.source import describe, get_variant, load_variants, resolve_ref

app = FastAPI(title="rule-verifier", version="0.1.0")

EFFECT_LABEL = {
    "false_positive": "오탐",
    "false_negative": "미탐",
    "not_checked": "점검 누락",
    "crash": "예외",
    "wrong_logic": "판정 오류",
}


def _nf(e: Exception):
    raise HTTPException(404, str(e))


# --------------------------------------------------------------------------- 공통
@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/api/variants")
def variants():
    return [describe(v) for v in load_variants()]


@app.get("/api/jobs")
def job_list():
    return jobs.recent()


@app.get("/api/jobs/{jid}")
def job_get(jid: str):
    j = jobs.get(jid)
    if not j:
        raise HTTPException(404, "job not found")
    return {k: v for k, v in j.items()}


# --------------------------------------------------------------------------- 결함 카탈로그 · 재현 케이스
def _rule_meta() -> dict:
    return json.loads(RULE_META_PATH.read_text(encoding="utf-8"))


VERDICT_KO = {"Vuln": "취약", "Secure": "양호", "N/A": "N/A", "ERROR": "예외"}


def _transitions(case: dict | None, result: dict | None) -> list[str]:
    """기대와 다르게 나온 결함 시나리오의 판정 전이 — '취약→양호' (올바른 결과 → 이 엔진 결과). 판정은 같은데 건수 · 목록만 틀리면 '취약(건수)'."""
    out: set[str] = set()
    for sc in (case or {}).get("scenarios", []):
        sr = ((result or {}).get("scenarios") or {}).get(sc["id"])
        if not sr or sc["role"] == "control" or sr.get("ok"):
            continue
        e, a = sc.get("expect", {}).get("verdict"), (sr.get("actual") or {}).get("verdict")
        ek, ak = VERDICT_KO.get(e, e), VERDICT_KO.get(a, a)
        out.add(f"{ek}→{ak}" if e and e != a else f"{ak}(건수)")
    return sorted(out)


def _catalog_rows() -> list[dict]:
    cases = load_cases()
    results = {v.id: (saved_results(v.id) or {}).get("cases", {}) for v in load_variants()}
    changed = _changed_rules()
    rows = []
    for f in load_catalog():
        c = cases.get(f["id"])
        effect = (c or {}).get("effect") or f["effect"]
        row = {
            **{k: f[k] for k in ("id", "rule", "rules", "code", "codes", "name", "level", "type", "summary", "impact", "confidence", "source")},
            "effect": effect,
            "effect_label": EFFECT_LABEL.get(effect, effect),
            "category": f["code"].split("-")[1] if f["code"].count("-") >= 2 else "",
            "has_case": c is not None,
            "case_status": (c or {}).get("status"),
            "scenario_count": len((c or {}).get("scenarios", [])),
            "results": {vid: (r.get(f["id"]) or {}).get("status") for vid, r in results.items()},
            "outcome": f.get("outcome") or "",
            "trigger": f.get("trigger") or "",
            "evidence": f.get("evidence") or "",
            "has_fix": _has_fix(f, changed),
            "transitions": {vid: _transitions(c, r.get(f["id"])) for vid, r in results.items()},
        }
        rows.append(row)
    return rows


@app.get("/api/catalog")
def catalog():
    return {"variants": [v.to_dict() for v in load_variants()], "effects": EFFECT_LABEL, "findings": _catalog_rows()}


@app.get("/api/overview")
def overview():
    rows = _catalog_rows()
    vs = load_variants()
    by_effect = Counter(r["effect"] for r in rows)
    by_category: dict[str, Counter] = defaultdict(Counter)
    for r in rows:
        by_category[r["category"]][r["effect"]] += 1
    status = {v.id: Counter((r["results"].get(v.id) or ("no_case" if not r["has_case"] else "not_run")) for r in rows) for v in vs}
    runs_meta = {}
    for v in vs:
        s = saved_results(v.id)
        runs_meta[v.id] = {"ran_at": s.get("ran_at"), "engine": s.get("variant", {}).get("engine")} if s else None
    return {
        "total_findings": len(rows),
        "total_rules": len({x for r in rows for x in r["rules"]}),
        "with_case": sum(1 for r in rows if r["has_case"]),
        "by_effect": dict(by_effect),
        "by_level": dict(Counter(r["level"] for r in rows)),
        "by_category": {k: dict(v) for k, v in sorted(by_category.items(), key=lambda kv: -sum(kv[1].values()))},
        "status": {k: dict(v) for k, v in status.items()},
        "case_runs": runs_meta,
        "variants": [describe(v) for v in vs],
        "effects": EFFECT_LABEL,
    }


@app.get("/api/findings/{fid}")
def finding(fid: str):
    f = next((x for x in load_catalog() if x["id"] == fid), None)
    if not f:
        raise HTTPException(404, fid)
    c = load_cases().get(fid)
    meta = _rule_meta()
    results = {}
    for v in load_variants():
        s = saved_results(v.id)
        if s and fid in s["cases"]:
            results[v.id] = s["cases"][fid]
    return {
        "finding": {**f, "effect": (c or {}).get("effect") or f["effect"], "effect_label": EFFECT_LABEL.get((c or {}).get("effect") or f["effect"]),
                    "has_fix": _has_fix(f, _changed_rules())},
        "rules_meta": {r: meta.get(r) for r in f.get("rules", [f["rule"]])},
        "case": c,
        "results": results,
    }


class CaseRunReq(BaseModel):
    variant: str | None = None  # 없으면 전부


@app.post("/api/cases/run")
def cases_run(req: CaseRunReq):
    vids = [req.variant] if req.variant else [v.id for v in load_variants()]

    def work(progress):
        out = {}
        for i, vid in enumerate(vids):
            progress(i / len(vids), f"{vid} 실행 중")
            doc = run_cases(get_variant(vid))
            out[vid] = dict(Counter(r["status"] for r in doc["cases"].values()))
        return out

    return jobs.submit("cases", f"재현 케이스 전체 실행 ({', '.join(vids)})", work)


@app.post("/api/findings/{fid}/run")
def finding_run(fid: str):
    """케이스 하나를 모든 변형으로 바로 돌린다(저장하지 않음)."""
    if fid not in load_cases():
        raise HTTPException(404, "case not found")
    return {v.id: run_cases(v, only={fid}, save=False)["cases"].get(fid) for v in load_variants()}


class PlaygroundReq(BaseModel):
    rule: str
    service: str | None = None
    args: object = None
    raw: dict = {}
    variants: list[str] | None = None
    as_of: str | None = None  # 룰이 보는 '지금' — 실데이터면 진단 시점(날짜 룰이 실데이터 실행과 같게)
    pre_rules: list[dict] | None = None  # 엔진 순서 재현 — 먼저 돌릴 같은 서비스 앞 룰 [{rule, args, service}]
    expect: dict | None = None  # 기대 결과(케이스 expect 와 같은 모양) — 주면 엔진마다 기대와 다른 점(diffs)을 붙인다


@app.post("/api/playground")
def playground(req: PlaygroundReq):
    """임의 입력(컨디션 + raw)으로 룰 하나를 변형마다 돌린다 — 케이스를 고쳐 보며 결과를 볼 때."""
    out = {}
    for vid in req.variants or [v.id for v in load_variants()]:
        r = run_job(get_variant(vid), {"mode": "scenarios", "timeout": 120, "as_of": req.as_of,
                                       "scenarios": [{"key": "p", "rule": req.rule, "service": req.service, "args": req.args, "raw": req.raw, "pre_rules": req.pre_rules}]})
        res = r["results"]["p"]
        if req.expect:
            res["diffs"] = check(req.expect, res)  # 재현 케이스 판정과 같은 규칙
            res["ok"] = not res["diffs"]
        out[vid] = res
    return out


_INVENTORY: dict[str, dict] = {}


def _inventory(variant) -> dict:
    """변형 엔진의 룰 → 서비스(service_code_func) · 룰 함수 목록. 엔진 sha 별로 한 번만 워커를 띄운다."""
    key = f"{resolve_ref(variant.engine_ref).get('full_sha') or variant.engine_ref}:{variant.overlay}"
    if variant.engine_ref.startswith("WORKTREE") or key not in _INVENTORY:
        inv = run_job(variant, {"mode": "inventory"}, timeout=300)
        _INVENTORY[key] = {"rules": inv["rules"], "functions": inv["functions"], "fingerprints": inv.get("fingerprints", {})}
    return _INVENTORY[key]


def _changed_rules() -> dict[str, set[str] | None]:
    """기준 변형(variants 첫 번째) 밖의 변형마다 — 기준과 룰 로직(룰 함수 + 부르는 헬퍼 소스 지문)이 다른 룰. 못 구하면 None."""
    variants = load_variants()
    try:
        base = _inventory(variants[0])["fingerprints"]
    except Exception:  # noqa: BLE001
        return {v.id: None for v in variants[1:]}
    out: dict[str, set[str] | None] = {}
    for v in variants[1:]:
        try:
            fp = _inventory(v)["fingerprints"]
            out[v.id] = {r for r in set(base) | set(fp) if base.get(r) != fp.get(r)} if base and fp else None
        except Exception:  # noqa: BLE001
            out[v.id] = None
    return out


def _has_fix(f: dict, changed: dict[str, set[str] | None]) -> dict[str, bool | None]:
    """결함의 룰 중 하나라도 그 변형에서 로직이 바뀌었나 — 변형 id → True/False/None(모름). 수집기(AWS/Raw) 수정은 보지 않는다."""
    rules = f.get("rules") or [f["rule"]]
    return {vid: (None if ch is None else any(r in ch for r in rules)) for vid, ch in changed.items()}


@app.get("/api/rules")
def rules():
    """입력 실험의 룰 · 서비스 선택지 — 기준 변형 엔진의 룰 목록 + DB 마스터 룰(항목명 · 분류 · 등급 · 기본 인자) + rule_meta(코드) + 결함 id."""
    meta = _rule_meta()
    db, db_env = dbcatalog.rule_meta()
    inv, error = {"rules": {}, "functions": [], "fingerprints": {}}, None
    variants = load_variants()
    try:
        inv = _inventory(variants[0])
    except Exception as e:  # noqa: BLE001 — 엔진을 못 풀어도 rule_meta 만으로 목록은 준다
        error = str(e)[-500:]
    # 기준 변형과 룰 로직(함수 + 부르는 헬퍼 소스)이 다른 변형 — 입력 실험에서 "개선 전후 비교" 가 되는 룰
    changed = _changed_rules() if inv["fingerprints"] else {}
    findings: dict[str, list[str]] = defaultdict(list)
    for f in load_catalog():
        for r in f.get("rules") or [f["rule"]]:
            findings[r].append(f["id"])
    ids = sorted(set(meta) | set(db) | set(inv["rules"]) | set(inv["functions"]))
    rows = []
    for r in ids:
        m, d = meta.get(r) or {}, db.get(r) or {}
        rows.append({
            "rule": r,
            "service": inv["rules"].get(r),
            "code": m.get("code"),
            "name": d.get("name") or m.get("name"),
            "category": d.get("category") or m.get("category"),
            "level": d.get("report_lv") or m.get("report_lv"),
            "in_master": bool(d) if db else None,
            # 컨디션 파일의 args 모양 그대로 — 기본 룰셋은 인자 있는 룰이면 ["90"], 없으면 []
            "default_args": [v for a in d.get("args", []) for v in a["default"]] if d else None,
            "arg_names": [f"{a['name']}({a['type']})" for a in d.get("args", [])],
            "has_function": r in inv["functions"] if inv["functions"] else None,
            "findings": findings.get(r, []),
            "changed_in": [vid for vid, ch in changed.items() if ch and r in ch] if changed and all(ch is not None for ch in changed.values()) else None,
        })
    return {"rules": rows, "services": sorted(set(inv["rules"].values())), "error": error, "db_env": db_env, "base_variant": variants[0].id}


@app.get("/api/playground/real")
def playground_real(diag: str, rule: str, ruleset: str | None = None, region: str | None = None, engine_order: bool = True):
    """입력 실험용 실데이터 — 받아 둔 진단에서 룰이 읽는 raw 만 + 컨디션 파일의 인자 + 진단 시점 + 운영 엔진의 실제 결과.
    engine_order 면 엔진 순서상 앞에 도는 같은 서비스 룰(pre_rules)과 그 raw 도 준다 — 룰셋 전체 실행과 같은 결과가 되게."""
    from app.diagnosis import _production

    try:
        pre = []
        if ruleset and engine_order:
            order = list(_inventory(load_variants()[0])["rules"].items())  # service_code_func 순서
            pre = realdata.pre_rules(diag, ruleset, rule, order)
        sl = realdata.slice_for_rule(diag, rule, region or None, [p["rule"] for p in pre])
        entry = realdata.ruleset_entry(diag, ruleset, rule) if ruleset else None
    except (FileNotFoundError, KeyError) as e:
        _nf(e)
    prod = None
    if ruleset and entry and entry.get("enabled"):
        try:
            prod = (_production(diag, ruleset) or {}).get(rule)
        except Exception:  # noqa: BLE001 — 운영 결과가 없거나 S3 에 못 닿으면 대조만 빠진다
            prod = None
    return {
        **sl,
        "args": entry.get("args") if entry else None,
        "enabled": entry.get("enabled") if entry else None,
        "ruleset_name": entry.get("ruleset_name") if entry else None,
        "as_of": realdata.as_of(diag),
        "production": prod,
        "pre_rules": pre,
    }


# --------------------------------------------------------------------------- 엔진이 부르는 AWS API 참고 (catalog/aws_api, `rv apiref` 로 생성)
@app.get("/api/apiref")
def apiref_index():
    idx = apiref.load_index()
    if not idx:
        raise HTTPException(404, "catalog/aws_api 가 없다 — backend 에서 `uv run rv apiref` 로 만든다")
    return idx


@app.get("/api/apiref/services/{svc}")
def apiref_service(svc: str):
    try:
        return apiref.load_service(svc)
    except FileNotFoundError as e:
        _nf(e)


# --------------------------------------------------------------------------- dev / 운영 DB 스냅샷 (고객사 · 계정 · 진단 · 룰 선택지)
@app.get("/api/db/status")
def db_status():
    return {
        "available": dbconn.available(),
        "snapshots": {e: dbcatalog.summary(dbcatalog.load(e)) for e in dbconn.ENVS},
        "profiles": {e: next((p for p in AWS_PROFILES if p.startswith(f"{e}-")), None) for e in dbconn.ENVS},
    }


class DbSyncReq(BaseModel):
    env: str


@app.post("/api/db/sync")
def db_sync(req: DbSyncReq):
    if req.env not in dbconn.ENVS:
        raise HTTPException(400, f"env: {req.env}")
    return jobs.submit("db-sync", f"{req.env} DB 목록 갱신", lambda progress: dbcatalog.sync(req.env, progress))


@app.get("/api/db/{env}/tenants")
def db_tenants(env: str):
    return dbcatalog.tenant_list(env)


@app.get("/api/db/{env}/tenants/{tid}")
def db_tenant(env: str, tid: str):
    try:
        return dbcatalog.tenant_detail(env, tid)
    except KeyError as e:
        _nf(e)


# --------------------------------------------------------------------------- S3 · 받아 둔 진단
@app.get("/api/s3/profiles")
def s3_profiles():
    return AWS_PROFILES


@app.get("/api/s3/buckets")
def s3_buckets(profile: str, tenant: str | None = None):
    # 버킷 이름만으로는 누구 것인지 모른다 — DB 스냅샷이 있으면 고객사 · 테넌트를 붙인다
    out = s3source.list_buckets(profile, tenant or None)
    owners = {}
    for env in {b["env"] for b in out}:
        for t in (dbcatalog.load(env) or {}).get("tenants", []):
            if t["bucket"]:
                owners[t["bucket"]] = {"tenant": t["id"], "company": t["company"]}
    return [{**b, **owners.get(b["bucket"], {})} for b in out]


@app.get("/api/s3/groups")
def s3_groups(profile: str, bucket: str):
    return s3source.list_groups(profile, bucket)


@app.get("/api/s3/keys")
def s3_keys(profile: str, bucket: str, group: str):
    return s3source.list_keys(profile, bucket, group)


@app.get("/api/s3/histories")
def s3_histories(profile: str, bucket: str, group: str, key: str):
    return s3source.list_histories(profile, bucket, group, key)


@app.get("/api/s3/files")
def s3_files(profile: str, bucket: str, group: str, key: str, his: str):
    return s3source.list_history_files(profile, bucket, group, key, his)


class DownloadReq(BaseModel):
    profile: str
    bucket: str
    group: str
    key: str
    his: str
    labels: dict | None = None  # DB 스냅샷에서 고른 경우 — 고객사 · 별칭 · 계정 · 그룹 이름 (meta.json 에 같이 둔다)


@app.post("/api/s3/download")
def s3_download(req: DownloadReq):
    return jobs.submit(
        "download",
        f"{req.key}/{req.his} 받기",
        lambda progress: s3source.download(req.profile, req.bucket, req.group, req.key, req.his, progress=lambda p: progress(p, "raw_data.json 받는 중"), labels=req.labels),
    )


@app.get("/api/diagnoses")
def diagnoses():
    # 받을 때 라벨이 없었던 진단(직접 넣은 폴더 · 예전 받기)도 스냅샷에서 누구 것인지 찾아 붙인다
    return [{**d, "labels": {**dbcatalog.labels_for(d), **(d.get("labels") or {})}} for d in s3source.local_diagnoses()]


@app.get("/api/diagnoses/{did}/rulesets/{name}")
def diagnosis_ruleset(did: str, name: str):
    try:
        rs = s3source.read_ruleset(did, name)
    except FileNotFoundError as e:
        _nf(e)
    meta = _rule_meta()
    rules = []
    for rid, v in (rs.get("rules") or {}).items():
        info = v[0] if isinstance(v, list) and v else {}
        m = meta.get(rid, {})
        rules.append({"rule": rid, "code": info.get("code") or m.get("code"), "name": m.get("name") or info.get("name"), "args": info.get("args"), "enabled": info.get("enabled"), "level": info.get("level"), "rule_type": info.get("rule_type", "logic")})
    return {k: rs.get(k) for k in ("ruleset_id", "ruleset_name", "ruleset_desc", "about", "com_id")} | {"rules": rules}


@app.delete("/api/diagnoses/{did}")
def diagnosis_delete(did: str):
    try:
        s3source.delete_local(did)
    except FileNotFoundError as e:
        _nf(e)
    return {"ok": True}


# --------------------------------------------------------------------------- 실데이터 실행
class RunReq(BaseModel):
    diag: str
    ruleset: str | None = None
    variants: list[str] | None = None
    args_override: str = ""


@app.get("/api/runs/args-modes")
def args_modes():
    return ARGS_MODES


@app.post("/api/runs")
def runs_create(req: RunReq):
    vids = req.variants or [v.id for v in load_variants()]
    if req.args_override not in ARGS_MODES:
        raise HTTPException(400, "args_override")

    def work(progress):
        doc = run_diagnosis(req.diag, vids, req.ruleset, req.args_override, progress=progress)
        return {"run_id": doc["id"], "summary": doc["summary"]}

    return jobs.submit("run", f"{req.diag} · {req.ruleset or '첫 룰셋'} 실행", work)


@app.get("/api/runs")
def runs_list():
    return list_runs()


def _slim(res: dict | None) -> dict | None:
    if not res:
        return res
    return {k: v for k, v in res.items() if k not in ("flag_ids", "good_ids", "na_ids", "flag_reason")}


@app.get("/api/runs/{run_id}")
def runs_get(run_id: str):
    try:
        d = get_run(run_id)
    except FileNotFoundError as e:
        _nf(e)
    for r in d["rules"]:
        r["variants"] = {k: _slim(v) for k, v in r["variants"].items()}
        for ch in r["changes"].values():
            for k in ("to_flag", "to_good", "left_flag", "left_good"):
                ch[f"{k}_n"] = len(ch.get(k, []))
                ch.pop(k, None)
    return d


@app.get("/api/runs/{run_id}/rules/{rule}")
def runs_rule(run_id: str, rule: str):
    try:
        d = get_run(run_id)
    except FileNotFoundError as e:
        _nf(e)
    row = next((r for r in d["rules"] if r["rule"] == rule), None)
    if not row:
        raise HTTPException(404, rule)
    return row


# --------------------------------------------------------------------------- 화면 (빌드된 FE)
DIST = REPO_DIR / "frontend" / "dist"
if DIST.exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{path:path}")
    def spa(path: str):
        # 없는 API 를 index.html 로 받으면 화면에 "Unexpected token '<'" 만 보인다 — API 경로는 404 JSON 으로
        if path == "api" or path.startswith("api/"):
            raise HTTPException(404, f"없는 API: /{path} — 서버가 화면보다 옛 코드면 다시 띄운다(./dev.sh serve)")
        p = (DIST / path).resolve()
        if path and DIST.resolve() in p.parents and p.is_file():
            return FileResponse(p)
        return FileResponse(DIST / "index.html")
