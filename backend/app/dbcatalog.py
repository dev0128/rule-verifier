"""dev / 운영 DB 에서 "무엇을 고를지" 목록을 스냅샷으로 받아 둔다 — 고객사 · 버킷 · AWS 계정 · 그룹/거버넌스 · 진단 · 룰.

S3 경로만으로는 고를 수 없다(위키 0060): 버킷 이름 끝은 sha1(root_id) 라 누구 것인지 모르고,
`CSPM/{group}/{key}/{his}/` 에는 고객사 · 별칭 · Account ID · 거버넌스 이름 · 진단 상태 · 삭제 여부가 없다.

- 동기화 때만 bastion 터널을 연다(dbconn). 화면은 스냅샷 `data/db/<env>.json` 만 읽는다.
- 스냅샷은 고객 환경 데이터 — data/ 안(.gitignore). 사람 정보는 회사명만 둔다(이름 · 메일 · 전화는 가져오지 않는다).
- 매번 전체 교체(이력 1.5만 행 수준이라 수십 초). 증분이면 삭제(del_yn) · status 변경을 놓친다.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from collections import Counter
from pathlib import Path

from app.config import DATA_DIR
from app.dbconn import connect, query

DB_DIR = DATA_DIR / "db"
SAFE_TENANT = re.compile(r"^[A-Za-z0-9_]+$")
TENANT_TABLES = ("cmm_user_dtl", "clo_key_mst", "clo_key_account", "clo_key_group_mst", "user_governance_mst", "clo_ruleset_mst", "clo_history_mst")


def snapshot_path(env: str) -> Path:
    return DB_DIR / f"{env}.json"


_CACHE: dict[str, tuple[float, dict]] = {}


def load(env: str) -> dict | None:
    p = snapshot_path(env)
    if not p.exists():
        return None
    mt = p.stat().st_mtime
    if env not in _CACHE or _CACHE[env][0] != mt:
        _CACHE[env] = (mt, json.loads(p.read_text(encoding="utf-8")))
    return _CACHE[env][1]


def _dt(v) -> str | None:
    return v.strftime("%Y-%m-%d %H:%M") if v else None


def _master_rules(conn) -> dict:
    """AWS 마스터 룰 — REME id 기준(엔진 · 컨디션 파일이 쓰는 id). 항목명 · 분류는 ko, 인자 기본값은 clo_rule_dtl."""
    rows = query(conn, (
        "SELECT m.rule_id, m.rem_id, m.use_yn, m.report_lv, m.arg_yn, m.arr_yn, r.category, r.name "
        "FROM dclo_master.lang_rule_mst m "
        "LEFT JOIN dclo_master.lang_rule_remediation_dtl r ON r.rem_id = m.rem_id AND r.lang_id = 'ko' "
        "WHERE m.provider = 'AMAZON' AND m.rem_id IS NOT NULL AND m.rem_id <> '' ORDER BY m.order_num"
    ))
    args: dict[str, list] = {}
    for a in query(conn, "SELECT rule_id, order_num, name, type, default_values, options FROM dclo_master.clo_rule_dtl ORDER BY rule_id, order_num"):
        args.setdefault(a["rule_id"], []).append(
            {"name": a["name"], "type": a["type"], "default": [x for x in (a["default_values"] or "").split(",") if x != ""], "options": a["options"]}
        )
    return {
        r["rem_id"]: {
            "rule_id": r["rule_id"],
            "category": r["category"],
            "name": r["name"],
            "report_lv": r["report_lv"],
            "use_yn": r["use_yn"],
            "arg_yn": r["arg_yn"],
            "args": args.get(r["rule_id"], []),
        }
        for r in rows
    }


def _tenant(conn, t: str, cols: dict[str, set[str]]) -> dict:
    """cols = 이 테넌트 스키마의 {테이블: 컬럼들}. 옛 테넌트는 테이블 · 컬럼이 빠져 있어(거버넌스 이전 스키마) 있는 것만 읽는다."""
    db = f"dclo_tenant_{t}"
    has = lambda table, col=None: table in cols and (col is None or col in cols[table])  # noqa: E731
    if not (has("clo_key_mst") and has("clo_history_mst")):
        raise RuntimeError("clo_key_mst / clo_history_mst 없음")
    company = query(conn, f"SELECT company, COUNT(*) n FROM `{db}`.cmm_user_dtl WHERE company <> '' GROUP BY company ORDER BY (user_id = %s) DESC, n DESC LIMIT 1", (t,))  # noqa: S608
    keys = query(conn, (
        f"SELECT k.key_id, k.alias, k.status, {'k.delete_target' if has('clo_key_mst', 'delete_target') else 'NULL'} AS delete_target, ka.account_id, ka.account_name "  # noqa: S608
        f"FROM `{db}`.clo_key_mst k LEFT JOIN `{db}`.clo_key_account ka ON ka.key_id = k.key_id WHERE k.provider = 'AMAZON'"
    ))
    groups = {}
    if has("clo_key_group_mst"):
        groups |= {r["group_id"]: {"name": r["name"], "kind": "group"} for r in query(conn, f"SELECT group_id, name FROM `{db}`.clo_key_group_mst")}  # noqa: S608
    if has("user_governance_mst"):
        groups |= {
            r["governance_id"]: {"name": r["name"], "kind": "governance"}
            for r in query(conn, f"SELECT governance_id, name FROM `{db}`.user_governance_mst WHERE provider = 'AMAZON'")  # noqa: S608
        }
    rulesets = {}
    if has("clo_ruleset_mst"):
        rulesets = {r["ruleset_id"]: r["name"] for r in query(conn, f"SELECT ruleset_id, name FROM `{db}`.clo_ruleset_mst")}  # noqa: S608
    hc = cols["clo_history_mst"]
    pick = lambda c: f"h.{c}" if c in hc else f"NULL AS {c}"  # noqa: E731
    hist = query(conn, (
        f"SELECT h.his_id, h.group_id, h.key_id, {', '.join(pick(c) for c in ('ruleset_id', 'use_governance', 'status', 'high', 'medium', 'low', 'good', 'na', 'del_yn'))}, h.ins_dt "  # noqa: S608
        f"FROM `{db}`.clo_history_mst h JOIN `{db}`.clo_key_mst k ON k.key_id = h.key_id AND k.provider = 'AMAZON' "
        "ORDER BY h.his_id DESC"
    ))
    return {
        "company": company[0]["company"] if company else None,
        "keys": {
            k["key_id"]: {
                "alias": k["alias"],
                "account_id": k["account_id"],
                "account_name": k["account_name"],
                "status": k["status"],
                "deleted": k.get("delete_target") == "Y",
            }
            for k in keys
        },
        "groups": groups,
        "rulesets": rulesets,
        "histories": [
            {
                "his_id": h["his_id"],
                "group_id": h["group_id"],
                "key_id": h["key_id"],
                "ruleset_id": h["ruleset_id"],
                "governance": h["use_governance"] == "Y",
                "status": h["status"],
                "high": h["high"], "medium": h["medium"], "low": h["low"], "good": h["good"], "na": h["na"],
                "ins_dt": _dt(h["ins_dt"]),
            }
            for h in hist
            if h["del_yn"] != "Y"
        ],
    }


def sync(env: str, progress=lambda p, m: None) -> dict:
    t0 = time.time()
    progress(0.0, f"{env} DB 터널 여는 중")
    with connect(env) as conn:
        rules = _master_rules(conn)
        master_rulesets = {r["ruleset_id"]: r["name"] for r in query(conn, "SELECT ruleset_id, name FROM dclo_master.clo_ruleset_mst")}
        center = {r["user_id"]: r for r in query(conn, "SELECT user_id, parent_id, user_alias, del_yn, UNIX_TIMESTAMP(ins_dt) ts FROM dclo_center.center_user")}
        names = [r[next(iter(r))][len("dclo_tenant_"):] for r in query(conn, "SHOW DATABASES LIKE 'dclo\\_tenant\\_%%'")]
        cols: dict[str, dict[str, set[str]]] = {}
        for r in query(conn, (
            "SELECT TABLE_SCHEMA s, TABLE_NAME t, COLUMN_NAME c FROM information_schema.COLUMNS "
            "WHERE TABLE_SCHEMA LIKE 'dclo\\_tenant\\_%%' AND TABLE_NAME IN %s"
        ), (TENANT_TABLES,)):
            cols.setdefault(r["s"][len("dclo_tenant_"):], {}).setdefault(r["t"], set()).add(r["c"])
        tenants, errors = [], {}
        for i, t in enumerate(names):
            if i % 10 == 0:
                progress(0.05 + 0.9 * i / max(len(names), 1), f"테넌트 {i}/{len(names)}")
            if not SAFE_TENANT.match(t):
                if t:
                    errors[t] = "테넌트 ID 형식이 다르다"
                continue
            try:
                info = _tenant(conn, t, cols.get(t, {}))
            except Exception as e:  # noqa: BLE001 — 스키마가 다른 옛 테넌트는 건너뛰고 사유를 남긴다
                errors[t] = str(e)[:200]
                continue
            # 버킷 = 엔진 Util/Set_Bucket.py 규칙: dclo-{env}-{UNIX_TIMESTAMP(root.ins_dt)}-{sha1(root_id)}
            cu = center.get(t)
            root = (cu or {}).get("parent_id") or t
            ts = (center.get(root) or {}).get("ts")
            bucket = f"dclo-{env}-{int(ts)}-{hashlib.sha1(root.encode()).hexdigest()}" if ts is not None else None  # noqa: S324 — 엔진과 같아야 한다
            hs = info["histories"]
            tenants.append({
                "id": t,
                "alias": (cu or {}).get("user_alias"),
                "deleted": (cu or {}).get("del_yn") == "Y",
                "bucket": bucket,
                **info,
                "last_diag": hs[0]["ins_dt"] if hs else None,
                "status_count": dict(Counter(h["status"] for h in hs)),
            })
    snap = {
        "env": env,
        "synced_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "sec": round(time.time() - t0, 1),
        "rules": rules,
        "master_rulesets": master_rulesets,
        "tenants": tenants,
        "errors": errors,
    }
    DB_DIR.mkdir(parents=True, exist_ok=True)
    tmp = snapshot_path(env).with_suffix(".part")
    tmp.write_text(json.dumps(snap, ensure_ascii=False, default=str), encoding="utf-8")
    tmp.replace(snapshot_path(env))
    progress(1.0, "완료")
    return summary(snap)


def summary(snap: dict | None) -> dict | None:
    if not snap:
        return None
    ts = snap["tenants"]
    return {
        "env": snap["env"],
        "synced_at": snap["synced_at"],
        "sec": snap.get("sec"),
        "tenants": len(ts),
        "tenants_with_aws": sum(1 for t in ts if t["histories"]),
        "histories": sum(len(t["histories"]) for t in ts),
        "rules": len(snap["rules"]),
        "errors": len(snap["errors"]),
    }


def tenant_list(env: str) -> list[dict]:
    snap = load(env)
    if not snap:
        return []
    out = []
    for t in snap["tenants"]:
        out.append({
            "id": t["id"],
            "company": t["company"],
            "alias": t["alias"],
            "deleted": t["deleted"],
            "bucket": t["bucket"],
            "keys": len(t["keys"]),
            "histories": len(t["histories"]),
            "end": t["status_count"].get("end", 0),
            "last_diag": t["last_diag"],
        })
    # 최근 진단이 있는 테넌트가 먼저(진단 없는 테넌트는 뒤)
    return sorted(out, key=lambda x: x["last_diag"] or "", reverse=True)


def tenant_detail(env: str, tid: str) -> dict:
    snap = load(env)
    t = next((x for x in (snap or {}).get("tenants", []) if x["id"] == tid), None)
    if not t:
        raise KeyError(tid)
    rs_names = {**snap.get("master_rulesets", {}), **t["rulesets"]}
    hist = [
        {
            **h,
            "group_name": (t["groups"].get(h["group_id"]) or {}).get("name"),
            "group_kind": (t["groups"].get(h["group_id"]) or {}).get("kind") or ("governance" if str(h["group_id"]).startswith("GOVERNANCE") else "group"),
            "ruleset_name": rs_names.get(h["ruleset_id"]) if h["ruleset_id"] else None,
        }
        for h in t["histories"]
    ]
    keys = []
    for kid, k in t["keys"].items():
        hs = [h for h in hist if h["key_id"] == kid]
        keys.append({"key_id": kid, **k, "histories": len(hs), "last_diag": hs[0]["ins_dt"] if hs else None})
    keys.sort(key=lambda k: k["last_diag"] or "", reverse=True)
    return {
        "id": t["id"], "company": t["company"], "alias": t["alias"], "bucket": t["bucket"],
        "keys": keys, "histories": hist, "ruleset_names": rs_names,
    }


def rule_meta(env: str | None = None) -> tuple[dict, str | None]:
    """화면의 룰 선택지용 — 운영 스냅샷 우선, 없으면 dev."""
    for e in [env] if env else ["ops", "dev"]:
        snap = load(e)
        if snap:
            return snap["rules"], e
    return {}, None


def labels_for(diag: dict) -> dict:
    """받아 둔 진단(meta: env · bucket · group_id · key_id · his_id) → 스냅샷의 고객사 · 계정 · 그룹 · 룰셋 이름. 못 찾으면 {}."""
    env, bucket = diag.get("env"), diag.get("bucket")
    snap = load(env) if env in ("dev", "ops") else None
    if not snap or not bucket:
        return {}
    t = next((x for x in snap["tenants"] if x["bucket"] == bucket), None)
    if not t:
        return {}
    k = t["keys"].get(diag.get("key_id") or "", {})
    g = t["groups"].get(diag.get("group_id") or "", {})
    rs = {**snap.get("master_rulesets", {}), **t["rulesets"]}
    return {
        "tenant": t["id"],
        "company": t["company"],
        "key_alias": k.get("alias"),
        "db_account_id": k.get("account_id"),
        "group_name": g.get("name"),
        "ruleset_names": {n: rs.get(n.removesuffix(".json")) for n in diag.get("rulesets", []) if rs.get(n.removesuffix(".json"))},
    }
