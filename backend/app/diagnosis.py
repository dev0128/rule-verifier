"""받아 둔 진단(컨디션 파일 + raw)으로 변형마다 룰셋 전체를 돌리고, 변형끼리 결과를 비교한다."""

from __future__ import annotations

import json
import time
import uuid
from collections import Counter, defaultdict

from app.cases import load_catalog
from app.config import RULE_META_PATH, RUNS_DIR
from app.engine.runner import run_job
from app.engine.source import describe, get_variant
from app.s3source import diag_dir, production_result

ARGS_MODES = {
    "": "컨디션 파일 그대로",
    "empty_str": "모든 인자를 \"\" 로 (거버넌스 기본 룰 경로)",
    "none": "모든 인자를 None 으로 (커스텀룰 마스터 참조 경로)",
    "empty_list": "모든 인자를 [] 로",
}


def _meta() -> dict:
    return json.loads(RULE_META_PATH.read_text(encoding="utf-8"))


def _findings_by_rule() -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = defaultdict(list)
    for f in load_catalog():
        for r in f.get("rules", [f["rule"]]):
            out[r].append({"id": f["id"], "effect": f["effect"], "summary": f["summary"], "type": f["type"]})
    return out


def pick_ruleset(did: str, ruleset: str | None) -> str:
    d = diag_dir(did)
    if ruleset:
        p = d / ruleset
        if p.parent != d or not p.exists():
            raise FileNotFoundError(ruleset)
        return ruleset
    names = sorted(p.name for p in d.glob("*.json") if p.name != "meta.json")
    if not names:
        raise FileNotFoundError("컨디션 파일(SET-*.json)이 없다")
    return names[0]


def _as_of(did: str, mode: str) -> str | None:
    """'diagnosis' — 진단 시점(raw 업로드 시각)으로 '지금'을 고정. 'now' — 고정 안 함."""
    if mode == "now":
        return None
    p = diag_dir(did) / "meta.json"
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8")).get("raw_modified")
    return None


def _production(did: str, ruleset: str) -> dict | None:
    """운영 엔진이 그 진단에서 남긴 Analyze/<룰셋>.json → 룰별 요약 (워커 결과와 같은 모양)."""
    p = production_result(did, ruleset)
    if not p:
        return None
    doc = json.loads(p.read_text(encoding="utf-8"))
    out = {}
    for v in doc.values():
        if not isinstance(v, list):
            continue
        for r in v:
            if not isinstance(r, dict) or "id" not in r:
                continue
            res = {
                "checked": r.get("checked_items", 0),
                "flag": r.get("flag_items", 0),
                "good": r.get("good_items", 0),
                "na": r.get("n/a_items", 0),
                "flag_ids": [str(x) for x in r.get("flag_list") or []],
                "good_ids": [str(x) for x in r.get("good_list") or []],
                "na_ids": [str(x) for x in r.get("n/a_list") or []],
                "error": {"type": "ProductionError", "message": r["error_reason"]} if r.get("error_reason") else None,
            }
            c, f, g, n = res["checked"], res["flag"], res["good"], res["na"]
            res["verdict"] = "N/A" if r.get("error_reason") or c == 0 else "Vuln" if f > 0 else "Secure" if g > 0 else "N/A" if n > 0 else "Secure"
            out[r["id"]] = res
    return out


def _same(a: dict | None, b: dict | None) -> bool:
    if not a or not b:
        return False
    return all(a.get(k) == b.get(k) for k in ("checked", "flag", "good", "na")) and set(a.get("flag_ids", [])) == set(b.get("flag_ids", []))


def run_diagnosis(did: str, variant_ids: list[str], ruleset: str | None = None, args_override: str = "", progress=None, as_of_mode: str = "diagnosis") -> dict:
    d = diag_dir(did)
    ruleset = pick_ruleset(did, ruleset)
    meta = _meta()
    as_of = _as_of(did, as_of_mode)
    per_variant = {}
    for i, vid in enumerate(variant_ids):
        if progress:
            progress(i / max(len(variant_ids), 1), f"{vid} 실행 중")
        v = get_variant(vid)
        out = run_job(
            v,
            {
                "mode": "ruleset",
                "ruleset_path": str(d / ruleset),
                "raw_path": str(d / "Raw" / "raw_data.json"),
                "args_override": args_override or None,
                "rule_meta": meta,
                "as_of": as_of,
            },
        )
        out["variant"] = describe(v)
        per_variant[vid] = out

    base = variant_ids[0]
    findings = _findings_by_rule()
    if progress:
        progress(0.95, "운영 결과(Analyze) 대조")
    prod = _production(did, ruleset) if not args_override else None
    rules = []
    all_rules = sorted({r for o in per_variant.values() for r in o["results"]})
    for r in all_rules:
        m = meta.get(r, {})
        row = {
            "rule": r,
            "code": m.get("code", r),
            "name": m.get("name", ""),
            "category": m.get("category", ""),
            "level": m.get("report_lv", ""),
            "findings": findings.get(r, []),
            "variants": {},
        }
        for vid, o in per_variant.items():
            res = o["results"].get(r)
            row["variants"][vid] = res
        b = row["variants"].get(base) or {}
        row["args"] = b.get("args")
        if prod is not None:
            p = prod.get(r)
            row["production"] = p
            row["matches_production"] = _same(b, p)
        changes = {}
        for vid in variant_ids[1:]:
            o = row["variants"].get(vid) or {}
            if not o or not b:
                continue
            bf, of = set(b.get("flag_ids", [])), set(o.get("flag_ids", []))
            bg, og = set(b.get("good_ids", [])), set(o.get("good_ids", []))
            ch = {
                "verdict": [b.get("verdict"), o.get("verdict")] if b.get("verdict") != o.get("verdict") else None,
                "counts": any(b.get(k) != o.get(k) for k in ("checked", "flag", "good", "na")),
                "to_flag": sorted(of - bf)[:200],
                "to_good": sorted(og - bg)[:200],
                "left_flag": sorted(bf - of)[:200],
                "left_good": sorted(bg - og)[:200],
                "error_fixed": bool(b.get("error")) and not o.get("error"),
                "error_new": not b.get("error") and bool(o.get("error")),
            }
            ch["changed"] = bool(ch["verdict"] or ch["counts"] or ch["to_flag"] or ch["to_good"] or ch["error_fixed"] or ch["error_new"])
            changes[vid] = ch
        row["changes"] = changes
        rules.append(row)

    summary = {
        "diag": did,
        "ruleset": ruleset,
        "args_override": args_override,
        "variants": {},
    }
    for vid, o in per_variant.items():
        c = Counter((o["results"][r]["verdict"]) for r in o["results"])
        summary["variants"][vid] = {
            "label": o["variant"]["label"],
            "verdicts": dict(c),
            "rules": len(o["results"]),
            "errors": sum(1 for r in o["results"].values() if r.get("error")),
            "sec": o["meta"]["sec"],
            "overlay_rules": len(o["meta"].get("overlay_rules", {})),
            "preprocess": o.get("preprocess", []),
        }
    if prod is not None:
        summary["production"] = {
            "available": True,
            "rules": len(prod),
            "same": sum(1 for r in rules if r.get("matches_production")),
            "different": [r["code"] for r in rules if "production" in r and not r.get("matches_production")],
        }
    else:
        summary["production"] = {"available": False}
    summary["as_of"] = as_of
    for vid in variant_ids[1:]:
        summary["variants"][vid]["changed_rules"] = sum(1 for r in rules if r["changes"].get(vid, {}).get("changed"))
    run_id = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:4]
    doc = {
        "id": run_id,
        "created": time.strftime("%Y-%m-%d %H:%M:%S"),
        "diag": did,
        "ruleset": ruleset,
        "ruleset_name": per_variant[base].get("ruleset_name"),
        "args_override": args_override,
        "as_of": as_of,
        "base": base,
        "variant_ids": variant_ids,
        "variants": {vid: {"describe": o["variant"], "meta": o["meta"], "skipped": o.get("skipped", []), "enabled_rules": o.get("enabled_rules")} for vid, o in per_variant.items()},
        "summary": summary,
        "rules": rules,
    }
    (RUNS_DIR / f"{run_id}.json").write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    return doc


def list_runs() -> list[dict]:
    out = []
    for p in sorted(RUNS_DIR.glob("*.json"), reverse=True):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        out.append({"id": d["id"], "created": d["created"], "diag": d["diag"], "ruleset": d["ruleset"], "ruleset_name": d.get("ruleset_name"), "args_override": d.get("args_override"), "summary": d["summary"]})
    return out


def get_run(run_id: str) -> dict:
    p = (RUNS_DIR / f"{run_id}.json").resolve()
    if p.parent != RUNS_DIR.resolve() or not p.exists():
        raise FileNotFoundError(run_id)
    return json.loads(p.read_text(encoding="utf-8"))
