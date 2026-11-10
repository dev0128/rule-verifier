"""CLI — 화면 없이 같은 일을 한다.

    uv run rv cases [--variant baseline] [--only F001,F002] [-v]   재현 케이스 실행
    uv run rv run <diag_dir> [--variants baseline,improved]        받아 둔 진단(컨디션 + raw)으로 실행
    uv run rv serve [--port 8600]                                   API 서버
    uv run rv apiref [--variant baseline]                           엔진이 부르는 AWS API 참고 자료 → catalog/aws_api/
"""

from __future__ import annotations

import argparse
import json
import sys


def _cases(a) -> int:
    from app.cases import load_catalog, run_cases
    from app.engine.source import get_variant

    only = set(a.only.split(",")) if a.only else None
    doc = run_cases(get_variant(a.variant), only=only)
    cat = {f["id"]: f for f in load_catalog()}
    counts: dict[str, int] = {}
    for fid, r in doc["cases"].items():
        counts[r["status"]] = counts.get(r["status"], 0) + 1
        if a.verbose or only:
            f = cat.get(fid, {})
            print(f"{fid} {f.get('code')} [{r['status']}] {f.get('summary', '')[:70]}")
            for sid, s in r["scenarios"].items():
                mark = "기대대로" if s["ok"] else "다름"
                act = s["actual"]
                print(f"   - {sid}({s['role']}): {mark} — {act.get('verdict')} c={act.get('checked')} f={act.get('flag')} g={act.get('good')} na={act.get('na')}")
                for d in s["diffs"]:
                    print(f"       · {d}")
                if a.verbose > 1:
                    print("       " + json.dumps(act, ensure_ascii=False)[:1500])
    print(f"[{a.variant}] {len(doc['cases'])} cases in {doc['sec']}s — " + ", ".join(f"{k} {v}" for k, v in sorted(counts.items())))
    return 0


def _run(a) -> int:
    from app.diagnosis import run_diagnosis

    doc = run_diagnosis(a.diag, a.variants.split(","), ruleset=a.ruleset)
    print(json.dumps(doc["summary"], ensure_ascii=False, indent=1))
    return 0


def _apiref(a) -> int:
    from app import apiref
    from app.config import RULE_META_PATH
    from app.engine.runner import run_job
    from app.engine.source import engine_src, get_variant, resolve_ref

    v = get_variant(a.variant)
    inv = run_job(v, {"mode": "inventory"}, timeout=300)  # 룰 → 서비스(service_code_func)
    ref = resolve_ref(v.engine_ref)
    meta = json.loads(RULE_META_PATH.read_text(encoding="utf-8"))
    doc = apiref.build(engine_src(v.engine_ref), v.engine_ref, ref.get("sha"), inv["rules"], meta)
    apiref.write(doc)
    m = doc["meta"]
    print(f"{apiref.OUT_DIR} — {m['counts']} · botocore {m['botocore']}" + (f" · 최신 비교 실패 {list(m['latest_errors'])}" if m["latest_errors"] else ""))
    return 0


def _serve(a) -> int:
    import uvicorn

    uvicorn.run("app.main:app", host=a.host, port=a.port, reload=a.reload)
    return 0


def main() -> None:
    p = argparse.ArgumentParser(prog="rv")
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("cases")
    c.add_argument("--variant", default="baseline")
    c.add_argument("--only")
    c.add_argument("-v", "--verbose", action="count", default=0)
    c.set_defaults(fn=_cases)
    r = sub.add_parser("run")
    r.add_argument("diag", help="data/diagnoses 아래 진단 id")
    r.add_argument("--variants", default="baseline,improved")
    r.add_argument("--ruleset")
    r.set_defaults(fn=_run)
    ar = sub.add_parser("apiref")
    ar.add_argument("--variant", default="baseline")
    ar.set_defaults(fn=_apiref)
    s = sub.add_parser("serve")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8600)
    s.add_argument("--reload", action="store_true")
    s.set_defaults(fn=_serve)
    a = p.parse_args()
    sys.exit(a.fn(a))


if __name__ == "__main__":
    main()
