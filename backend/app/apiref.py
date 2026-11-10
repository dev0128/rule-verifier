"""엔진이 부르는 AWS API 참고 자료 — 수집기 · 룰 코드에서 API 를 뽑고, 공식 API 모델로 응답 구조를 붙인다.

출처
- 엔진 소스(variants.json 기준 변형의 engine_ref): 수집기 `AWS/Raw/Service/*.py`, 룰 `AWS/Analyze/Service/*.py` — AST 로 정적 분석.
- AWS 공식 API 모델: botocore `data/<서비스>/<버전>/service-2.json`. AWS API Reference 문서와 같은 원본(Smithy 모델)에서
  생성된 것으로, 필드 · 타입 · enum · 설명(documentation)이 그대로 들어 있다. **엔진이 고정한 botocore 1.37.2**(백엔드 venv 와 같음)를 기준으로 하고,
  최신 botocore(GitHub develop)와 비교해 "고정 버전에서는 응답 파서가 버리는 필드" 를 따로 표시한다(위키 0123 의 Athena 사례).
- 문서 링크: AWS API Reference(`docs.aws.amazon.com/goto/WebAPI/<uid>/<Operation>`) · boto3 문서.

결과는 `catalog/aws_api/` (index.json + 서비스별 json) — 공개 정보와 엔진 코드에서만 만든다. 고객 데이터는 넣지 않는다.
정적 분석이라 동적으로 만든 메서드 이름 · 키는 놓칠 수 있다. 룰이 읽는 필드가 모델에 없다는 표시는 "확인 필요" 후보다(엔진이 붙인 키일 수 있음).
"""

from __future__ import annotations

import ast
import html
import json
import re
import time
import urllib.request
from collections import defaultdict
from pathlib import Path

import botocore
import botocore.session
from botocore import xform_name

from app.config import DATA_DIR, REPO_DIR

OUT_DIR = REPO_DIR / "catalog" / "aws_api"
LATEST_DIR = DATA_DIR / "botocore-latest"  # 최신 모델 캐시(공개 데이터)
LATEST_URL = "https://raw.githubusercontent.com/boto/botocore/develop/botocore/data/{svc}/{ver}/service-2.json"
MAX_DEPTH = 9
DOC_LEN = 500

_session = botocore.session.get_session()
_loader = _session.get_component("data_loader")
BOTO_SERVICES = set(_session.get_available_services())


# --------------------------------------------------------------------------- 공식 모델
def _doc(s: str | None, n: int = DOC_LEN) -> str:
    if not s:
        return ""
    t = re.sub(r"<[^>]+>", " ", s)
    t = html.unescape(re.sub(r"\s+", " ", t)).strip()
    return t if len(t) <= n else t[: n - 1] + "…"


_models: dict[str, object] = {}


def service_model(svc: str):
    if svc not in _models:
        _models[svc] = _session.get_service_model(svc)
    return _models[svc]


def snake_ops(svc: str) -> dict[str, str]:
    return {xform_name(op): op for op in service_model(svc).operation_names}


def shape_tree(shape, depth: int = 0, seen: tuple = ()) -> dict:
    """응답 shape → 화면용 트리. 재귀 shape 는 이름만 남긴다."""
    node: dict = {"type": shape.type_name}
    if shape.documentation:
        node["doc"] = _doc(shape.documentation)
    if getattr(shape, "enum", None):
        node["enum"] = list(shape.enum)
    if shape.name in seen or depth >= MAX_DEPTH:
        if shape.type_name in ("structure", "list", "map"):
            node["ref"] = shape.name
        return node
    seen = (*seen, shape.name)
    if shape.type_name == "structure":
        req = set(shape.required_members or [])
        node["members"] = {}
        for name, m in shape.members.items():
            child = shape_tree(m, depth + 1, seen)
            if name in req:
                child["required"] = True
            node["members"][name] = child
    elif shape.type_name == "list":
        node["item"] = shape_tree(shape.member, depth + 1, seen)
    elif shape.type_name == "map":
        node["key"] = shape_tree(shape.key, depth + 1, seen)
        node["value"] = shape_tree(shape.value, depth + 1, seen)
    return node


def member_names(shape, seen: set | None = None) -> set[str]:
    """shape 안의 모든 구조체 멤버 이름(중첩 포함)."""
    seen = seen if seen is not None else set()
    if shape is None or shape.name in seen:
        return set()
    seen.add(shape.name)
    out: set[str] = set()
    if shape.type_name == "structure":
        for name, m in shape.members.items():
            out.add(name)
            out |= member_names(m, seen)
    elif shape.type_name == "list":
        out |= member_names(shape.member, seen)
    elif shape.type_name == "map":
        out |= member_names(shape.value, seen)
    return out


def member_paths(shape, prefix: str = "", seen: tuple = ()) -> set[str]:
    """최신 모델과 비교할 경로 집합 — `Detector.Status`, `Items[].Name` 처럼."""
    if shape is None or shape.name in seen or prefix.count(".") > MAX_DEPTH:
        return set()
    seen = (*seen, shape.name)
    out: set[str] = set()
    if shape.type_name == "structure":
        for name, m in shape.members.items():
            p = f"{prefix}.{name}" if prefix else name
            out.add(p)
            out |= member_paths(m, p, seen)
    elif shape.type_name == "list":
        out |= member_paths(shape.member, prefix + "[]", seen)
    elif shape.type_name == "map":
        out |= member_paths(shape.value, prefix + "{}", seen)
    return out


def doc_urls(svc: str, op: str) -> dict:
    meta = service_model(svc).metadata
    uid = meta.get("uid")
    out = {"boto3": f"https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/{svc}/client/{xform_name(op)}.html"}
    if uid:
        out["aws"] = f"https://docs.aws.amazon.com/goto/WebAPI/{uid}/{op}"
    return out


# --------------------------------------------------------------------------- 최신 botocore 모델(비교용)
def _latest_model(svc: str):
    ver = service_model(svc).api_version
    p = LATEST_DIR / svc / ver / "service-2.json"
    if not p.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
        req = urllib.request.Request(LATEST_URL.format(svc=svc, ver=ver), headers={"User-Agent": "rule-verifier-apiref"})
        with urllib.request.urlopen(req, timeout=30) as r:  # noqa: S310 — 고정된 GitHub raw URL
            p.write_bytes(r.read())
    from botocore.model import ServiceModel

    return ServiceModel(json.loads(p.read_text(encoding="utf-8")), service_name=svc)


# --------------------------------------------------------------------------- 수집기 분석
def _consts(node) -> list[str]:
    return [n.value for n in ast.walk(node) if isinstance(n, ast.Constant) and isinstance(n.value, str)]


def _name_values(fn) -> dict[str, set[str]]:
    """함수 안에서 이름에 대입된 문자열 상수들 — `method = "x"`, `method, key = "x", "Y"`, `for method in {..}.keys()`."""
    vals: dict[str, set[str]] = defaultdict(set)
    dicts: dict[str, list[str]] = {}
    for n in ast.walk(fn):
        if isinstance(n, ast.Assign):
            for t in n.targets:
                if isinstance(t, ast.Name) and isinstance(n.value, ast.Constant) and isinstance(n.value.value, str):
                    vals[t.id].add(n.value.value)
                elif isinstance(t, ast.Name) and isinstance(n.value, ast.Dict):
                    dicts[t.id] = [k.value for k in n.value.keys if isinstance(k, ast.Constant) and isinstance(k.value, str)]
                elif isinstance(t, ast.Tuple) and isinstance(n.value, ast.Tuple):
                    for a, b in zip(t.elts, n.value.elts):
                        if isinstance(a, ast.Name):
                            if isinstance(b, ast.Constant) and isinstance(b.value, str):
                                vals[a.id].add(b.value)
                            elif isinstance(b, ast.Dict):
                                dicts[a.id] = [k.value for k in b.keys if isinstance(k, ast.Constant) and isinstance(k.value, str)]
        elif isinstance(n, ast.For) and isinstance(n.target, ast.Name):
            src = ast.unparse(n.iter)
            for d, keys in dicts.items():
                if re.search(rf"\b{re.escape(d)}\b", src):
                    vals[n.target.id].update(keys)
            if isinstance(n.iter, (ast.List, ast.Tuple)):
                vals[n.target.id].update(e.value for e in n.iter.elts if isinstance(e, ast.Constant) and isinstance(e.value, str))
    return vals


def _resolve(node, names: dict[str, set[str]]) -> set[str]:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return {node.value}
    if isinstance(node, ast.Name):
        return set(names.get(node.id, ()))
    if isinstance(node, ast.JoinedStr):
        return set()
    return set()


def _is_raw_chain(node) -> bool:
    return "f_json_raw" in ast.unparse(node)


def _subscript_depth(node) -> int:
    d = 0
    while isinstance(node, ast.Subscript):
        d += 1
        node = node.value
    return d


def analyze_collector(path: Path) -> dict:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    module = path.stem
    raw_service = module
    clients: set[str] = set()
    client_attr: dict[str, str] = {}  # self.iamclient → "iam"
    for n in ast.walk(tree):
        if isinstance(n, ast.Assign) and isinstance(n.value, ast.Call) and ast.unparse(n.value.func).endswith("boto3_client") and len(n.value.args) > 1:
            a = n.value.args[1]
            svc = a.value if isinstance(a, ast.Constant) else None
            for t in n.targets:
                if isinstance(t, ast.Attribute):
                    client_attr[t.attr] = svc or "__self__"
    for n in ast.walk(tree):
        if isinstance(n, ast.FunctionDef) and n.name == "__init__":
            for a in ast.walk(n):
                if isinstance(a, ast.Assign) and isinstance(a.value, ast.Constant) and isinstance(a.value.value, str):
                    for t in a.targets:
                        if (isinstance(t, ast.Name) and t.id == "service") or (isinstance(t, ast.Attribute) and t.attr == "service"):
                            raw_service = a.value.value
        if isinstance(n, ast.Call) and ast.unparse(n.func).endswith("boto3_client"):
            for a in n.args[1:2]:
                if isinstance(a, ast.Constant) and isinstance(a.value, str):
                    clients.add(a.value)
        if isinstance(n, ast.Assign) and isinstance(n.value, ast.Constant) and isinstance(n.value.value, str):
            for t in n.targets:
                tn = t.attr if isinstance(t, ast.Attribute) else t.id if isinstance(t, ast.Name) else ""
                if "service" in tn and n.value.value in BOTO_SERVICES:
                    clients.add(n.value.value)
    # 클라이언트 서비스는 boto3_client 인자 · *_service 대입으로만 잡는다(문자열 우연 일치 방지)
    if raw_service in BOTO_SERVICES:
        clients.add(raw_service)
    for k, v in list(client_attr.items()):
        if v == "__self__":
            client_attr[k] = raw_service if raw_service in BOTO_SERVICES else next(iter(sorted(clients)), raw_service)
    ops_by_svc = {c: snake_ops(c) for c in clients if c in BOTO_SERVICES}

    functions = []
    for cls in [n for n in tree.body if isinstance(n, ast.ClassDef)]:
        for fn in [n for n in cls.body if isinstance(n, ast.FunctionDef)]:
            if fn.name == "__init__":
                continue
            names = _name_values(fn)
            key_patterns: set[str] = set()
            words = set(_consts(fn)) | {v for vs in names.values() for v in vs}
            words |= {n.attr for n in ast.walk(fn) if isinstance(n, ast.Attribute)}
            # f"list_attached_{kind}_policies" 처럼 이름을 조립해 부르는 경우 — 패턴으로 연산 이름을 맞춘다
            for n in ast.walk(fn):
                if isinstance(n, ast.JoinedStr):
                    pat = "".join(re.escape(v.value) if isinstance(v, ast.Constant) else "[a-z0-9_]+" for v in n.values)
                    fixed = [v.value for v in n.values if isinstance(v, ast.Constant)]
                    # 앞뒤가 모두 고정 문자열일 때만(“describe_{x}” 처럼 열린 패턴은 거의 모든 연산에 맞는다)
                    if len(fixed) >= 2 and isinstance(n.values[0], ast.Constant) and isinstance(n.values[-1], ast.Constant) and sum(map(len, fixed)) >= 12:
                        words |= {o for m in ops_by_svc.values() for o in m if re.fullmatch(pat, o)}
            calls = sorted({n.func.attr for n in ast.walk(fn) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                            and isinstance(n.func.value, ast.Name) and n.func.value.id == "self"})
            ops = []
            # 1) 어떤 클라이언트로 불렀는지 보이는 호출 — self.iamclient.get_role(…) · get_response(…, self.iamclient, …, "get_policy")
            bound: set[str] = set()
            for n in ast.walk(fn):
                if not isinstance(n, ast.Call):
                    continue
                f = n.func
                if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Attribute) and f.value.attr in client_attr:
                    sv = client_attr[f.value.attr]
                    if sv in ops_by_svc and f.attr in ops_by_svc[sv]:
                        ops.append((sv, ops_by_svc[sv][f.attr]))
                        bound.add(f.attr)
                cl = [a.attr for a in n.args if isinstance(a, ast.Attribute) and a.attr in client_attr]
                if cl:
                    sv = client_attr[cl[0]]
                    for a in n.args:
                        for v in _resolve(a, names):
                            if sv in ops_by_svc and v in ops_by_svc[sv]:
                                ops.append((sv, ops_by_svc[sv][v]))
                                bound.add(v)
            # 2) 그 밖의 이름 — 수집기 서비스 우선
            for w in sorted(words - bound):
                hit = [(s, m[w]) for s, m in ops_by_svc.items() if w in m]
                if len(hit) > 1:
                    pref = [h for h in hit if h[0] == raw_service]
                    hit = pref or hit
                ops += hit
            raw_keys: set[str] = set()
            attach: set[str] = set()
            for n in ast.walk(fn):
                if isinstance(n, ast.Subscript) and _is_raw_chain(n.value) and _subscript_depth(n) == 3:
                    raw_keys |= _resolve(n.slice, names)
                    if isinstance(n.slice, ast.JoinedStr):  # f"list_{kind}s" — 아래에서 이 수집기의 raw 키와 맞춘다
                        key_patterns.add("".join(re.escape(v.value) if isinstance(v, ast.Constant) else "[a-z0-9_]+" for v in n.slice.values))
                if isinstance(n, ast.Call) and any(_is_raw_chain(a) and not isinstance(a, ast.Subscript) for a in n.args):
                    # append_result(response, self.f_json_raw, region, service, method, key) · boto3_module.all_paginator(..., method, ...)
                    for a in n.args:
                        for v in _resolve(a, names):
                            if any(v in m for m in ops_by_svc.values()):
                                raw_keys.add(v)
                # 응답을 레코드에 붙이는 키 — item["X"] = … · item.update({"X": …})
                if isinstance(n, ast.Assign):
                    for t in n.targets:
                        if isinstance(t, ast.Subscript) and not _is_raw_chain(t):
                            attach |= _resolve(t.slice, names)
                        elif isinstance(t, ast.Subscript) and _is_raw_chain(t):
                            # raw[...]["key"] = [{"OwnerId": …}] — 엔진이 직접 만든 레코드의 키
                            attach |= {k.value for d in ast.walk(n.value) if isinstance(d, ast.Dict)
                                       for k in d.keys if isinstance(k, ast.Constant) and isinstance(k.value, str)}
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "update" and not _is_raw_chain(n.func.value):
                    for a in n.args:
                        if isinstance(a, ast.Dict):
                            attach |= {v for k in a.keys if k is not None for v in _resolve(k, names)}  # {method_key: …} 도
                # raw[region][service].get("describe_x", []) 로 읽는 raw 키
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "get" and n.args \
                        and _is_raw_chain(n.func.value) and _subscript_depth(n.func.value) == 2:
                    raw_keys |= _resolve(n.args[0], names)
            raw_keys = {k for k in raw_keys if k and not k.startswith("_")}
            if raw_keys or key_patterns:
                # raw 를 쓰는 함수가 만드는 dict 의 키 — 엔진이 직접 만든 레코드(apigateway v1_apis 의 apis · v1_id 등)
                attach |= {k.value for d in ast.walk(fn) if isinstance(d, ast.Dict)
                           for k in d.keys if isinstance(k, ast.Constant) and isinstance(k.value, str)}
            if ops or raw_keys or attach or key_patterns:
                functions.append({
                    "fields_read": sorted(_fields_read(fn) - _local_keys(fn)),
                    "key_patterns": sorted(key_patterns),
                    "function": fn.name, "line": fn.lineno, "calls": calls,
                    "ops": [{"service": s, "operation": o} for s, o in sorted(set(ops))],
                    "raw_keys": sorted(raw_keys),
                    "attach_keys": sorted(k for k in attach if k and re.match(r"^[A-Za-z][\w-]*$", k)),
                })
    known = {k for f in functions for k in f["raw_keys"]}
    for f in functions:
        for pat in f.pop("key_patterns"):
            f["raw_keys"] = sorted(set(f["raw_keys"]) | {k for k in known if re.fullmatch(pat, k)})
    return {"module": module, "file": f"AWS/Raw/Service/{path.name}", "raw_service": raw_service, "clients": sorted(clients), "functions": functions}


# --------------------------------------------------------------------------- 룰 분석
def _fields_read(fn) -> set[str]:
    """x["Field"] · x.get("Field") 로 읽는 키. ("x" in y 는 문자열 포함 검사와 구분이 안 돼 뺀다)"""
    out: set[str] = set()
    for n in ast.walk(fn):
        if isinstance(n, ast.Subscript) and isinstance(n.slice, ast.Constant) and isinstance(n.slice.value, str):
            out.add(n.slice.value)
        elif isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "get" and n.args:
            a = n.args[0]
            if isinstance(a, ast.Constant) and isinstance(a.value, str):
                out.add(a.value)
    return {f for f in out if re.match(r"^[A-Za-z][\w:.-]*$", f)}


# 모델 필드가 아닌데 룰이 읽는 키 — "모델에 없는 필드" 후보에서 뺀다
POLICY_KEYS = {  # IAM 정책 문서 문법 (응답 안의 JSON 문자열을 파싱해서 읽는다) — 조건 연산자 포함
    "Version", "Id", "Statement", "Sid", "Effect", "Principal", "NotPrincipal", "Action", "NotAction",
    "Resource", "NotResource", "Condition", "AWS", "Service", "Federated", "CanonicalUser",
    "StringEquals", "StringNotEquals", "StringLike", "StringNotLike", "StringEqualsIgnoreCase", "ArnEquals", "ArnLike",
    "ArnNotEquals", "ArnNotLike", "Bool", "IpAddress", "NotIpAddress", "NumericEquals", "NumericLessThan", "DateGreaterThan", "Null",
}
# AWS API 가 아닌 출처의 키 — 룰이 다른 라이브러리 · 외부 API 결과를 읽는다
OTHER_SOURCE_KEYS = {
    "line_number": "detect-secrets 스캔 결과", "type": "detect-secrets 스캔 결과", "hashed_secret": "detect-secrets 스캔 결과",
    "tag_name": "GitHub releases API (ECS-011 최신 버전 조회)",
}
# IAM 자격 증명 보고서(get_credential_report → Content = base64 CSV)의 컬럼 — API 모델에는 없고 문서에 정의돼 있다
CREDENTIAL_REPORT_DOC = "https://docs.aws.amazon.com/IAM/latest/UserGuide/id_credentials_getting-report.html#id_credentials_understanding_the_report_format"
CREDENTIAL_REPORT_COLUMNS = [
    "user", "arn", "user_creation_time", "password_enabled", "password_last_used", "password_last_changed", "password_next_rotation", "mfa_active",
    "access_key_1_active", "access_key_1_last_rotated", "access_key_1_last_used_date", "access_key_1_last_used_region", "access_key_1_last_used_service",
    "access_key_2_active", "access_key_2_last_rotated", "access_key_2_last_used_date", "access_key_2_last_used_region", "access_key_2_last_used_service",
    "cert_1_active", "cert_1_last_rotated", "cert_2_active", "cert_2_last_rotated",
]
# 엔진 결과 dict 의 f-string 키(putBasicResult: f"{flag|good|n/a|del}_{list|total|select|key|reason}")
RESULT_KEYS = {f"{a}_{b}" for a in ("flag", "good", "n/a", "del") for b in ("list", "total", "select", "key", "reason")}
REGION_RE = re.compile(r"^(globals|[a-z]{2}(-gov|-iso[a-z]*)?-[a-z]+-\d)$")


def _local_keys(fn) -> set[str]:
    """함수가 스스로 만드는 dict 의 키 — dict 리터럴 · x["k"] = … · x.update({"k": …}) · setdefault("k")."""
    out: set[str] = set()
    for n in ast.walk(fn):
        if isinstance(n, ast.Dict):
            out |= {k.value for k in n.keys if isinstance(k, ast.Constant) and isinstance(k.value, str)}
        elif isinstance(n, (ast.Assign, ast.AugAssign)):
            targets = n.targets if isinstance(n, ast.Assign) else [n.target]
            targets = [e for t in targets for e in (t.elts if isinstance(t, ast.Tuple) else [t])]  # x["k"], y = {}, {}
            for t in targets:
                if isinstance(t, ast.Subscript) and isinstance(t.slice, ast.Constant) and isinstance(t.slice.value, str):
                    out.add(t.slice.value)
        elif isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "setdefault" and n.args:
            a = n.args[0]
            if isinstance(a, ast.Constant) and isinstance(a.value, str):
                out.add(a.value)
    return out


def _framework_keys(src: Path) -> set[str]:
    """엔진 공통 모듈(결과 dict · 결과 정리 함수)이 쓰는 키 — checked_items · check_value 등."""
    out: set[str] = set()
    out |= RESULT_KEYS
    for p in [src / "ANALYZE_CORE" / "Util" / "ResultOrganizer.py", src / "ANALYZE_CORE" / "Util" / "keyword_base.py",
              src / "AWS" / "Raw" / "Get_Raw.py", *sorted((src / "AWS" / "Module").glob("*.py"))]:
        if p.exists():
            tree = ast.parse(p.read_text(encoding="utf-8"))
            out |= _fields_read(tree) | _local_keys(tree)
    return out


def analyze_rules(src: Path, raw_keys_by_service: dict[str, set[str]], module_raw: dict[str, str], rule_service: dict[str, str]) -> dict:
    rules = {}
    framework = _framework_keys(src)
    for p in sorted((src / "AWS" / "Analyze" / "Service").glob("*.py")):
        if p.name.startswith("_"):
            continue
        tree = ast.parse(p.read_text(encoding="utf-8"))
        module_local = _local_keys(tree)  # 같은 파일의 헬퍼가 만드는 dict 키도 엔진이 만든 키다
        for fn in [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name.startswith("REME_")]:
            rid = fn.name.replace("_", "-", 1)
            consts = set(_consts(fn))
            own = module_raw.get(rule_service.get(rid, ""), rule_service.get(rid, ""))
            svcs = {own} | {s for s in raw_keys_by_service if s in consts}
            used = sorted({(s, k) for s in svcs for k in raw_keys_by_service.get(s, ()) if k in consts})
            rules[rid] = {
                "file": f"AWS/Analyze/Service/{p.name}", "line": fn.lineno, "service": rule_service.get(rid), "raw_service": own,
                "raw_keys": [{"service": s, "key": k} for s, k in used],
                "fields_read": sorted(_fields_read(fn) - {k for _, k in used} - set(raw_keys_by_service) - {"raw"}),
                "local_keys": sorted((_local_keys(fn) | module_local | framework) & _fields_read(fn)),
            }
    return rules


# --------------------------------------------------------------------------- 생성
def build(src: Path, engine_ref: str, engine_sha: str | None, rule_service: dict[str, str], rule_meta: dict, progress=print) -> dict:
    collectors = []
    for p in sorted((src / "AWS" / "Raw" / "Service").glob("*.py")):
        if p.name.startswith("_") or " " in p.name or p.stem in ("s3_acync",):
            continue
        collectors.append(analyze_collector(p))
    module_raw = {c["module"]: c["raw_service"] for c in collectors}

    # raw 키 → 그 키를 만들거나 채우는 API
    raw: dict[str, dict[str, dict]] = defaultdict(dict)
    for c in collectors:
        # 하위 헬퍼(self._get_x(repo) 처럼 레코드를 받아 채우는 함수)의 API · 붙이는 키를 부른 쪽으로 올린다 — 2단계까지
        by_name = {f["function"]: f for f in c["functions"]}
        for f in c["functions"]:
            seen, frontier = {f["function"]}, list(f["calls"])
            for _ in range(2):
                nxt = []
                for name in frontier:
                    h = by_name.get(name)
                    if h and name not in seen and not h["raw_keys"]:
                        seen.add(name)
                        f["ops"] = [*f["ops"], *[o for o in h["ops"] if o not in f["ops"]]]
                        f["attach_keys"] = sorted(set(f["attach_keys"]) | set(h["attach_keys"]))
                        nxt += h["calls"]
                frontier = nxt
        for f in c["functions"]:
            for k in f["raw_keys"]:
                e = raw[c["raw_service"]].setdefault(k, {"ops": set(), "functions": [], "attach_keys": set()})
                e["ops"] |= {(o["service"], o["operation"]) for o in f["ops"]}
                e["functions"].append({"file": c["file"], "function": f["function"], "line": f["line"]})
                e["attach_keys"] |= set(f["attach_keys"])
    raw_keys_by_service = {s: set(ks) for s, ks in raw.items()}
    rules = analyze_rules(src, raw_keys_by_service, module_raw, rule_service)

    # 연산별 모델 정보
    ops_used = sorted({op for ks in raw.values() for e in ks.values() for op in e["ops"]} | {(o["service"], o["operation"]) for c in collectors for f in c["functions"] for o in f["ops"]})
    progress(f"API {len(ops_used)}개 — 모델 · 최신 비교")
    operations: dict[str, dict] = {}
    names_by_op: dict[tuple, set[str]] = {}
    latest_err: dict[str, str] = {}
    for svc, op in ops_used:
        sm = service_model(svc)
        om = sm.operation_model(op)
        out_shape = om.output_shape
        names_by_op[(svc, op)] = member_names(out_shape)
        added: list[str] = []
        try:
            lm = _latest_model(svc)
            if op in lm.operation_names:
                lo = lm.operation_model(op).output_shape
                added = sorted(member_paths(lo) - member_paths(out_shape))
        except Exception as e:  # noqa: BLE001 — 네트워크가 없으면 비교만 빠진다
            latest_err[svc] = str(e)[:200]
        operations[f"{svc}.{op}"] = {
            "service": svc,
            "operation": op,
            "method": xform_name(op),
            "doc": _doc(om.documentation, 1200),
            "urls": doc_urls(svc, op),
            "paginated": _loader_has_paginator(svc, op),
            "input_required": list(om.input_shape.required_members) if om.input_shape else [],
            "output": shape_tree(out_shape) if out_shape else None,
            "added_in_latest": added,
            "raw_keys": sorted(f"{s}.{k}" for s, ks in raw.items() for k, e in ks.items() if (svc, op) in e["ops"]),
        }

    # 수집기가 응답에서 읽는 키 중 모델에 없는 것(확인 후보) — 예: ssm list_response_plans 의 "Arn"(실제 "arn", 0107 F082)
    collector_unknown = []
    for c in collectors:
        c_attach = {k for f in c["functions"] for k in f["attach_keys"]}
        c_raw = {k for f in c["functions"] for k in f["raw_keys"]}
        for f in c["functions"]:
            ops_here = {(o["service"], o["operation"]) for o in f["ops"]}
            for k in f["raw_keys"]:
                ops_here |= raw[c["raw_service"]].get(k, {}).get("ops", set())
            if not ops_here:
                continue
            known = set().union(*(member_names(service_model(sv).operation_model(op).output_shape) for sv, op in ops_here))
            known |= set().union(*(member_names(service_model(sv).operation_model(op).input_shape) for sv, op in ops_here))
            bad = sorted(
                x for x in f["fields_read"]
                if x not in known and x not in c_attach and x not in c_raw and x not in POLICY_KEYS and x not in OTHER_SOURCE_KEYS
                and not REGION_RE.match(x) and x not in ("ResponseMetadata", "NextToken", "nextToken", "Marker") and x not in BOTO_SERVICES
            )
            if bad:
                collector_unknown.append({"file": c["file"], "function": f["function"], "line": f["line"], "raw_service": c["raw_service"],
                                          "raw_keys": f["raw_keys"], "unknown_fields": bad})

    # 룰 → API · 모델에 없는 필드(확인 후보)
    attach_all = {k for ks in raw.values() for e in ks.values() for k in e["attach_keys"]}
    for rid, r in rules.items():
        ops = sorted({op for rk in r["raw_keys"] for op in raw[rk["service"]][rk["key"]]["ops"]})
        r["operations"] = [f"{s}.{o}" for s, o in ops]
        known = set().union(*(names_by_op.get(o, set()) for o in ops)) if ops else set()
        attach = {k for rk in r["raw_keys"] for k in raw[rk["service"]][rk["key"]]["attach_keys"]}
        skip = set(r.pop("local_keys")) | attach | attach_all | POLICY_KEYS | set(CREDENTIAL_REPORT_COLUMNS) | set(OTHER_SOURCE_KEYS)
        r["documented_extra"] = sorted(set(r["fields_read"]) & set(CREDENTIAL_REPORT_COLUMNS))
        r["unknown_fields"] = sorted(
            f for f in r["fields_read"] if ops and f not in known and f not in skip and not REGION_RE.match(f) and ":" not in f
        )
        m = rule_meta.get(rid) or {}
        r["code"], r["name"] = m.get("code"), m.get("name")
        for o in r["operations"]:
            operations[o].setdefault("rules", []).append(rid)

    raw_out = {
        s: {
            k: {"ops": [f"{a}.{b}" for a, b in sorted(e["ops"])], "functions": e["functions"], "attach_keys": sorted(e["attach_keys"])}
            for k, e in sorted(ks.items())
        }
        for s, ks in sorted(raw.items())
    }
    return {
        "meta": {
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "engine_ref": engine_ref, "engine_sha": engine_sha,
            "botocore": botocore.__version__,
            "latest_source": "github.com/boto/botocore@develop",
            "latest_errors": latest_err,
            "counts": {"collectors": len(collectors), "raw_keys": sum(len(v) for v in raw_out.values()), "operations": len(operations), "rules": len(rules)},
        },
        "collectors": collectors,
        "raw": raw_out,
        "operations": operations,
        "rules": rules,
        "collector_unknown": collector_unknown,
        "documented_extra": {"iam.get_credential_report": {"doc": CREDENTIAL_REPORT_DOC, "columns": CREDENTIAL_REPORT_COLUMNS}},
        "other_source_keys": OTHER_SOURCE_KEYS,
    }


def _loader_has_paginator(svc: str, op: str) -> bool:
    try:
        return op in _loader.load_service_model(svc, "paginators-1").get("pagination", {})
    except Exception:  # noqa: BLE001
        return False


def write(doc: dict) -> None:
    """index.json(메타 · raw · 룰 · 연산 요약) + 서비스별 연산 상세."""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for old in OUT_DIR.glob("*.json"):
        old.unlink()
    by_svc: dict[str, dict] = defaultdict(dict)
    summary = {}
    for key, o in doc["operations"].items():
        by_svc[o["service"]][key] = o
        summary[key] = {k: o[k] for k in ("service", "operation", "method", "urls", "paginated", "raw_keys")} | {
            "rules": o.get("rules", []), "added_in_latest": len(o["added_in_latest"]), "doc": _doc(o["doc"], 200),
        }
    for svc, ops in by_svc.items():
        (OUT_DIR / f"{svc}.json").write_text(json.dumps(ops, ensure_ascii=False, indent=1), encoding="utf-8")
    index = {k: doc[k] for k in ("meta", "collectors", "raw", "rules", "collector_unknown", "documented_extra", "other_source_keys")} | {"operations": summary}
    (OUT_DIR / "index.json").write_text(json.dumps(index, ensure_ascii=False, indent=1), encoding="utf-8")


def load_index() -> dict | None:
    p = OUT_DIR / "index.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def load_service(svc: str) -> dict:
    if not re.fullmatch(r"[a-z0-9-]+", svc):
        raise FileNotFoundError(svc)
    p = OUT_DIR / f"{svc}.json"
    if not p.exists():
        raise FileNotFoundError(svc)
    return json.loads(p.read_text(encoding="utf-8"))
