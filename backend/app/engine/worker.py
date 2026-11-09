"""엔진 룰 실행 워커 — 백엔드가 서브프로세스로 띄운다. 표준 라이브러리 + 엔진 소스만 쓴다.

    python worker.py <job.json> <out.json>

왜 서브프로세스인가
- 엔진 변형(ref · 오버레이)마다 같은 모듈 이름(AWS.…)을 다른 소스로 import 해야 한다.
- 엔진 src 에도 `app` · `Util` 패키지가 있어 백엔드 패키지와 이름이 겹친다. 이 파일은 백엔드 패키지를 import 하지 않는다.

엔진과 같게 하는 것
- 룰 모듈은 그대로 import 하고 DB · 설정 모듈(config, dbModule, crypts, Util.util …)만 가짜로 바꾼다.
- 룰 함수는 @error_handler 를 벗긴 원 함수(__wrapped__)로 부르고, 예외가 나면 엔진 `run_master_rule`(k8s-engine 7c527f46)처럼
  일부만 채운 결과를 버리고 N/A + error_reason 으로 남긴다.
- ruleset 모드는 `AWS/Analyze/Get_Analyze.py aws_analyze_run` 의 순서(service_code_func 순서) · 인자 · raw 공유를 따른다.
  컨디션 파일(룰셋 SET-….json)은 엔진의 setRuleData 로 읽는다(범위 인자 처리까지 같게).
- 판정(Vuln/Secure/N/A)은 k8s-convert `set_weak_state` 와 같은 규칙으로 매긴다.

엔진과 다른 것
- 외부 네트워크를 막는다(기본). ECS-011(GitHub API) · EKS-008(AWS 문서) 처럼 밖으로 나가는 룰은 "외부망 차단" 경로를 탄다.
- 커스텀 룰(CUSTOM-RULE-…)은 Couchbase 가 필요해 돌리지 않는다(결과에 skipped 로 남김).
"""

from __future__ import annotations

import copy
import importlib
import importlib.util
import io
import json
import os
import select
import signal
import socket
import sys
import time
import traceback
import types
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path

LIST_CAP = 5000  # 실데이터에서 리소스 id 목록을 이만큼까지만 남긴다


# --------------------------------------------------------------------------- 엔진 로드
def install_stubs(engine_src: str) -> None:
    sys.path.insert(0, engine_src)
    for name in ("config", "logging_config", "dbModule", "crypts", "dynamoModule"):
        mod = types.ModuleType(name)
        if name == "config":
            mod.worker = "MAX"
            mod.MASTER = None
        sys.modules[name] = mod
    util_pkg = types.ModuleType("Util")
    util_pkg.__path__ = []
    util_mod = types.ModuleType("Util.util")
    util_mod.execute_one = lambda *a, **k: {}
    util_mod.execute_all = lambda *a, **k: []
    qb_path = Path(engine_src) / "Util" / "Query_BASE.py"
    if qb_path.exists():
        spec = importlib.util.spec_from_file_location("Util.Query_BASE", qb_path)
        qb = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(qb)
    else:
        qb = types.ModuleType("Util.Query_BASE")
    util_pkg.util = util_mod
    util_pkg.Query_BASE = qb
    sys.modules.update({"Util": util_pkg, "Util.util": util_mod, "Util.Query_BASE": qb})


def block_network() -> None:
    def _blocked(*_a, **_k):
        raise OSError("network blocked by rule-verifier (외부망 차단)")

    socket.socket.connect = _blocked  # type: ignore[assignment]
    socket.socket.connect_ex = _blocked  # type: ignore[assignment]
    socket.create_connection = _blocked  # type: ignore[assignment]
    socket.getaddrinfo = _blocked  # type: ignore[assignment]


def freeze_time(as_of: str) -> None:
    """룰 모듈이 보는 '지금'을 고정한다 — 90일 경과 같은 날짜 룰을 진단 시점 기준으로 다시 돌리려고.

    룰은 `from datetime import datetime` 후 datetime.now() / now(timezone.utc) 를 쓴다. 로드된 엔진 모듈의
    `datetime` 이름을 now · utcnow · today 만 고정한 하위 클래스로 바꾼다.
    """
    import datetime as _dt

    fixed = _dt.datetime.fromisoformat(as_of.replace("Z", "+00:00"))
    if fixed.tzinfo is None:
        fixed = fixed.replace(tzinfo=_dt.timezone.utc)

    class FrozenDatetime(_dt.datetime):
        @classmethod
        def now(cls, tz=None):
            v = fixed.astimezone(tz) if tz else fixed.astimezone().replace(tzinfo=None)
            return cls(v.year, v.month, v.day, v.hour, v.minute, v.second, v.microsecond, v.tzinfo)

        @classmethod
        def utcnow(cls):
            v = fixed.astimezone(_dt.timezone.utc).replace(tzinfo=None)
            return cls(v.year, v.month, v.day, v.hour, v.minute, v.second, v.microsecond)

        @classmethod
        def today(cls):
            return cls.now()

    for name, mod in list(sys.modules.items()):
        if not (name.startswith("AWS") or name.startswith("ANALYZE_CORE") or name.startswith("rv_overlay")):
            continue
        if getattr(mod, "datetime", None) is _dt.datetime:
            mod.datetime = FrozenDatetime


class Engine:
    def __init__(self, engine_src: str, overlay: str | None):
        install_stubs(engine_src)
        sink = io.StringIO()
        with redirect_stdout(sink), redirect_stderr(sink):
            from ANALYZE_CORE.Util.ResultOrganizer import putBasicResult
            from ANALYZE_CORE.Util import common_util
            from AWS.Module.base import service_code_func
            rules_mod = importlib.import_module("AWS.Analyze.Service._init")
        self.putBasicResult = putBasicResult
        self.common_util = common_util
        self.service_code = service_code_func()
        self.rule_service = {r: s for s, rs in self.service_code.items() for r in rs}
        self.funcs = {k: v for k, v in vars(rules_mod).items() if k.startswith("REME_") and callable(v)}
        self.preprocessors: list = []
        self.overlay_rules: dict[str, str] = {}
        if overlay:
            self._load_overlay(Path(overlay))

    def _load_overlay(self, overlay: Path) -> None:
        for p in sorted(overlay.glob("*.py")):
            if p.name.startswith("_"):
                continue
            spec = importlib.util.spec_from_file_location(f"rv_overlay_{p.stem}", p)
            mod = importlib.util.module_from_spec(spec)
            sink = io.StringIO()
            with redirect_stdout(sink), redirect_stderr(sink):
                spec.loader.exec_module(mod)
            fixes = getattr(mod, "FIXES", {})
            for name, fn in vars(mod).items():
                if name.startswith("REME_") and callable(fn) and getattr(fn, "__module__", "") == mod.__name__:
                    self.funcs[name] = fn
                    self.overlay_rules[name.replace("_", "-", 1)] = fixes.get(name, f"{p.name}")
            pre = getattr(mod, "preprocess_raw", None)
            if callable(pre):
                self.preprocessors.append((p.name, pre))

    def preprocess(self, raw: dict) -> list[str]:
        applied = []
        for name, fn in self.preprocessors:
            fn(raw)
            applied.append(name)
        return applied

    def run_rule(self, rule: str, args, raw: dict, service: str | None, meta: dict | None = None) -> dict:
        """룰 1건. raw 는 엔진처럼 {"raw": {...}} 형태(json_given)."""
        service = service or self.rule_service.get(rule, "")
        fn = self.funcs.get(rule.replace("-", "_"))
        if fn is None:
            return {"rule": rule, "service": service, "missing": True, "verdict": "MISSING"}
        meta = meta or {}
        result = self.putBasicResult(
            {
                "rem_id": rule,
                "code": meta.get("code", rule),
                "category": meta.get("category", service),
                "name": meta.get("name", rule),
                "report_lv": meta.get("report_lv", "-"),
            }
        )
        pristine = copy.deepcopy(result)
        target = getattr(fn, "__wrapped__", fn)
        sink = io.StringIO()
        t0 = time.time()
        error = None
        try:
            with redirect_stdout(sink), redirect_stderr(sink):
                ret = target(result, args, raw, service)
            r = result if ret is None else ret
        except Exception as e:  # noqa: BLE001 — 룰 예외를 그대로 기록한다
            tb = traceback.extract_tb(sys.exc_info()[2])
            frames = [f for f in tb if "/AWS/" in f.filename or "/ANALYZE_CORE/" in f.filename or "rv_overlay" in f.filename or "overlays" in f.filename]
            f = frames[-1] if frames else tb[-1]
            where = f"{_short(f.filename)}:{f.lineno} {f.line or ''}".strip()
            error = {"type": type(e).__name__, "message": str(e)[:500], "where": where}
            r = pristine
            r.update({"status": "N/A", "error_reason": f"Analyze Error({type(e).__name__}): {str(e)[:500]}"})
        return summarize(rule, service, r, error, round(time.time() - t0, 3), rule in self.overlay_rules)


def _short(path: str) -> str:
    for marker in ("/src/", "/overlays/"):
        if marker in path:
            return path.split(marker, 1)[1] if marker == "/src/" else "overlays/" + path.split(marker, 1)[1]
    return path


def verdict_of(r: dict, error) -> str:
    if error:
        return "ERROR"
    checked, flag, good, na = (r.get(k, 0) or 0 for k in ("checked_items", "flag_items", "good_items", "n/a_items"))
    if checked == 0:
        return "N/A"
    if flag > 0:
        return "Vuln"
    if good > 0:
        return "Secure"
    if na > 0:
        return "N/A"
    return "Secure"


def summarize(rule: str, service: str, r: dict, error, sec: float, overlaid: bool) -> dict:
    def ids(key):
        v = r.get(key) or []
        return [str(x) for x in v][:LIST_CAP]

    reasons = {}
    for k, v in (r.get("flag_reason") or {}).items():
        if len(reasons) >= 200:
            break
        reasons[str(k)] = v if isinstance(v, (str, int, float)) else json.dumps(v, ensure_ascii=False, default=str)[:300]
    return {
        "rule": rule,
        "service": service,
        "verdict": verdict_of(r, error),
        "checked": r.get("checked_items", 0),
        "flag": r.get("flag_items", 0),
        "good": r.get("good_items", 0),
        "na": r.get("n/a_items", 0),
        "flag_ids": ids("flag_list"),
        "good_ids": ids("good_list"),
        "na_ids": ids("n/a_list"),
        "flag_reason": reasons,
        "error": error,
        "overlay": overlaid,
        "sec": sec,
    }


# --------------------------------------------------------------------------- 모드: 시나리오(재현 케이스)
def _run_forked(engine: Engine, sc: dict, timeout: float) -> dict:
    """시나리오 하나를 fork 한 자식에서 돌린다 — 룰 모듈의 전역 상태(CWH 등)가 케이스끼리 섞이지 않게."""
    rfd, wfd = os.pipe()
    pid = os.fork()
    if pid == 0:  # child
        os.close(rfd)
        try:
            raw = {"raw": sc.get("raw") or {}}
            applied = engine.preprocess(raw["raw"]) if sc.get("preprocess", True) else []
            res = engine.run_rule(sc["rule"], sc.get("args"), raw, sc.get("service"))
            res["preprocess"] = applied
            payload = json.dumps(res, ensure_ascii=False, default=str).encode()
        except BaseException as e:  # noqa: BLE001
            payload = json.dumps({"rule": sc.get("rule"), "verdict": "ERROR", "error": {"type": "WorkerError", "message": repr(e)}}).encode()
        with os.fdopen(wfd, "wb") as w:
            w.write(payload)
        os._exit(0)
    os.close(wfd)
    chunks = []
    deadline = time.time() + timeout
    with os.fdopen(rfd, "rb") as rf:
        while True:
            left = deadline - time.time()
            if left <= 0:
                os.kill(pid, signal.SIGKILL)
                os.waitpid(pid, 0)
                return {"rule": sc.get("rule"), "verdict": "ERROR", "error": {"type": "Timeout", "message": f">{timeout}s"}}
            ready, _, _ = select.select([rf], [], [], left)
            if not ready:
                continue
            b = rf.read1(1 << 20) if hasattr(rf, "read1") else rf.read(1 << 20)
            if not b:
                break
            chunks.append(b)
    os.waitpid(pid, 0)
    return json.loads(b"".join(chunks) or b"{}")


def run_scenarios(engine: Engine, job: dict) -> dict:
    out = {}
    for sc in job["scenarios"]:
        out[sc["key"]] = _run_forked(engine, sc, job.get("timeout", 60))
    return out


# --------------------------------------------------------------------------- 모드: 컨디션 파일 + 실데이터
ARGS_OVERRIDE = {"none": lambda a: None, "empty_str": lambda a: "", "empty_list": lambda a: []}


def run_ruleset(engine: Engine, job: dict) -> dict:
    meta_map = job.get("rule_meta") or {}
    sink = io.StringIO()
    with redirect_stdout(sink), redirect_stderr(sink):
        rule_json, target, ruleset_id = engine.common_util.setRuleData(job["ruleset_path"])
        with open(job["raw_path"], "r", encoding="utf-8") as f:
            raw = json.load(f)
    if rule_json is None:
        raise RuntimeError(f"룰셋을 읽지 못함: {job['ruleset_path']}")
    applied = engine.preprocess(raw.get("raw", {}))
    override = ARGS_OVERRIDE.get(job.get("args_override") or "")
    only = set(job.get("only_rules") or [])
    results, skipped = {}, []
    # 엔진과 같은 순서 — service_code_func 의 서비스 · 룰 순서로, 같은 raw 를 룰들이 차례로 공유한다
    for service_name, rules in engine.service_code.items():
        for rule in rules:
            if rule not in target or (only and rule not in only):
                continue
            info = rule_json["rules"][rule][0]
            if info.get("rule_type", "logic") != "logic":
                skipped.append({"rule": rule, "reason": f"rule_type={info.get('rule_type')}"})
                continue
            args = info["args"]
            if override:
                args = override(args)
            res = engine.run_rule(rule, args, raw, service_name, meta_map.get(rule))
            res["args"] = args
            results[rule] = res
    for rule in target:
        if rule.startswith("CUSTOM-RULE-"):
            skipped.append({"rule": rule, "reason": "커스텀 룰 — Couchbase 필요, 이 도구에서는 돌리지 않음"})
    return {
        "ruleset_id": ruleset_id,
        "ruleset_name": rule_json.get("ruleset_name"),
        "enabled_rules": len(target),
        "results": results,
        "skipped": skipped,
        "preprocess": applied,
    }


# --------------------------------------------------------------------------- main
def main(job_path: str, out_path: str) -> None:
    job = json.loads(Path(job_path).read_text(encoding="utf-8"))
    t0 = time.time()
    if job.get("network", "block") == "block":
        block_network()
    engine = Engine(job["engine_src"], job.get("overlay"))
    if job.get("as_of"):
        freeze_time(job["as_of"])
    out: dict = {
        "meta": {
            "engine_src": job["engine_src"],
            "overlay": job.get("overlay"),
            "overlay_rules": engine.overlay_rules,
            "preprocessors": [n for n, _ in engine.preprocessors],
            "network": job.get("network", "block"),
            "as_of": job.get("as_of"),
            "rule_count": len(engine.funcs),
            "python": sys.version.split()[0],
        }
    }
    if job["mode"] == "scenarios":
        out["results"] = run_scenarios(engine, job)
    elif job["mode"] == "ruleset":
        out.update(run_ruleset(engine, job))
    elif job["mode"] == "inventory":
        out["rules"] = {r: s for r, s in engine.rule_service.items()}
        out["functions"] = sorted(k.replace("_", "-", 1) for k in engine.funcs)
    else:
        raise ValueError(job["mode"])
    out["meta"]["sec"] = round(time.time() - t0, 2)
    Path(out_path).write_text(json.dumps(out, ensure_ascii=False, default=str), encoding="utf-8")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
