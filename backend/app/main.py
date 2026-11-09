"""rule-verifier API."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app import jobs, s3source
from app.cases import load_cases, load_catalog, run_cases, saved_results
from app.config import AWS_PROFILES, REPO_DIR, RULE_META_PATH
from app.diagnosis import ARGS_MODES, get_run, list_runs, run_diagnosis
from app.engine.runner import run_job
from app.engine.source import describe, get_variant, load_variants

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


def _catalog_rows() -> list[dict]:
    cases = load_cases()
    results = {v.id: (saved_results(v.id) or {}).get("cases", {}) for v in load_variants()}
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
        "finding": {**f, "effect": (c or {}).get("effect") or f["effect"], "effect_label": EFFECT_LABEL.get((c or {}).get("effect") or f["effect"])},
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


@app.post("/api/playground")
def playground(req: PlaygroundReq):
    """임의 입력(컨디션 + raw)으로 룰 하나를 변형마다 돌린다 — 케이스를 고쳐 보며 결과를 볼 때."""
    out = {}
    for vid in req.variants or [v.id for v in load_variants()]:
        r = run_job(get_variant(vid), {"mode": "scenarios", "timeout": 60, "scenarios": [{"key": "p", "rule": req.rule, "service": req.service, "args": req.args, "raw": req.raw}]})
        out[vid] = r["results"]["p"]
    return out


# --------------------------------------------------------------------------- S3 · 받아 둔 진단
@app.get("/api/s3/profiles")
def s3_profiles():
    return AWS_PROFILES


@app.get("/api/s3/buckets")
def s3_buckets(profile: str, tenant: str | None = None):
    return s3source.list_buckets(profile, tenant or None)


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


@app.post("/api/s3/download")
def s3_download(req: DownloadReq):
    return jobs.submit(
        "download",
        f"{req.key}/{req.his} 받기",
        lambda progress: s3source.download(req.profile, req.bucket, req.group, req.key, req.his, progress=lambda p: progress(p, "raw_data.json 받는 중")),
    )


@app.get("/api/diagnoses")
def diagnoses():
    return s3source.local_diagnoses()


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
        p = (DIST / path).resolve()
        if path and DIST.resolve() in p.parents and p.is_file():
            return FileResponse(p)
        return FileResponse(DIST / "index.html")
