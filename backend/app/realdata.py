"""입력 실험에 실제 고객 데이터를 넣는다 — 받아 둔 진단에서 룰 하나가 읽는 raw 만 잘라 낸다.

- 어떤 raw 키를 자를지는 `catalog/aws_api` 의 룰 → raw 키(엔진 룰 코드 AST 분석)를 쓴다. 못 찾으면 그 룰 서비스의 raw 전체.
- **리전 키는 전부 남긴다**(관련 데이터가 없는 리전은 빈 dict). 리전 수만큼 점검 건수를 세는 룰(GuardDuty 등)이 있어서,
  리전을 빼면 실데이터 실행(룰셋 전체)과 결과가 달라진다. 리전을 골라 좁히면 결과가 달라질 수 있다는 것을 화면에 적는다.
- 인자는 그 진단의 컨디션 파일(SET-….json)의 `rules[rule][0].args`, 기준 시각은 진단 시점(raw 업로드 시각) — 실데이터 실행과 같다.
- 데이터는 data/ 안에서만 읽어 응답으로 준다(브라우저 메모리). 파일로 다른 곳에 쓰지 않는다.
"""

from __future__ import annotations

import json

from app import apiref
from app.s3source import diag_dir

_RAW_CACHE: dict[str, tuple[float, dict]] = {}


def _raw(did: str) -> dict:
    p = diag_dir(did) / "Raw" / "raw_data.json"
    mt = p.stat().st_mtime
    if did not in _RAW_CACHE or _RAW_CACHE[did][0] != mt:
        if len(_RAW_CACHE) >= 2:  # raw 는 수십 MB — 최근 2개만 들고 있는다
            _RAW_CACHE.pop(next(iter(_RAW_CACHE)))
        _RAW_CACHE[did] = (mt, json.loads(p.read_text(encoding="utf-8")).get("raw", {}))
    return _RAW_CACHE[did][1]


def _keys_for(rule: str) -> tuple[list[tuple[str, str | None]], str]:
    """룰이 읽는 (raw 서비스, raw 키). 키가 None 이면 그 서비스 전체."""
    idx = apiref.load_index() or {}
    r = (idx.get("rules") or {}).get(rule)
    if r and r.get("raw_keys"):
        return [(k["service"], k["key"]) for k in r["raw_keys"]], "catalog/aws_api 의 룰 → raw 키"
    if r and r.get("raw_service"):
        return [(r["raw_service"], None)], f"룰이 읽는 raw 키를 못 찾아 {r['raw_service']} 서비스 전체"
    raise KeyError(f"{rule} — catalog/aws_api 에 없는 룰 (uv run rv apiref)")


def ruleset_entry(did: str, ruleset: str, rule: str) -> dict | None:
    d = diag_dir(did)
    p = d / ruleset
    if p.parent != d or not p.exists():
        raise FileNotFoundError(ruleset)
    doc = json.loads(p.read_text(encoding="utf-8"))
    e = (doc.get("rules") or {}).get(rule)
    return {**e[0], "ruleset_name": doc.get("ruleset_name")} if e else None


def pre_rules(did: str, ruleset: str, rule: str, order: list[tuple[str, str]]) -> list[dict]:
    """엔진(Get_Analyze) 순서에서 이 룰보다 앞에 도는 같은 서비스 룰 — 그 진단 컨디션 파일에서 켜진 것만, 그 인자로.
    order = [(룰, 서비스)] service_code_func 순서."""
    d = diag_dir(did)
    doc = json.loads((d / ruleset).read_text(encoding="utf-8"))
    rules = doc.get("rules") or {}
    svc = dict(order).get(rule)
    out = []
    for r, s in order:
        if r == rule:
            break
        e = (rules.get(r) or [{}])[0]
        if s == svc and e.get("enabled") and e.get("rule_type", "logic") == "logic":
            out.append({"rule": r, "args": e.get("args"), "service": s})
    return out


def slice_for_rule(did: str, rule: str, region: str | None = None, extra_rules: list[str] | None = None) -> dict:
    raw = _raw(did)
    keys, how = _keys_for(rule)
    for r in extra_rules or []:  # 앞 룰이 읽는 raw 도 같이(엔진 순서 재현)
        keys += [k for k in _keys_for(r)[0] if k not in keys]
    out: dict = {}
    counts: dict[str, int] = {}
    for reg, svcs in raw.items():
        if region and reg != region:
            continue
        part: dict = {}
        for svc, key in keys:
            data = (svcs or {}).get(svc)
            if data is None:
                continue
            if key is None:
                part[svc] = data
            elif key in data:
                part.setdefault(svc, {})[key] = data[key]
        out[reg] = part  # 데이터가 없어도 리전 키는 남긴다(리전 수를 세는 룰)
        counts[reg] = sum(len(v) if isinstance(v, list) else 1 for s in part.values() for v in (s.values() if isinstance(s, dict) else [s]))
    text = json.dumps(out, ensure_ascii=False, default=str)
    return {
        "raw": out,
        "keys": [f"{s}.{k}" if k else f"{s}.*" for s, k in keys],
        "how": how,
        "regions": counts,
        "all_regions": sorted(raw),
        "records": sum(counts.values()),
        "bytes": len(text.encode()),
    }


def meta(did: str) -> dict:
    p = diag_dir(did) / "meta.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def as_of(did: str) -> str | None:
    return meta(did).get("raw_modified")
