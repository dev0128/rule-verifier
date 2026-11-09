"""오래 걸리는 일(raw 다운로드 · 진단 실행 · 케이스 전체 실행)을 백그라운드 스레드로 돌리고 상태를 보여준다. 메모리에만 둔다."""

from __future__ import annotations

import threading
import time
import traceback
import uuid
from typing import Callable

_jobs: dict[str, dict] = {}
_lock = threading.Lock()


def submit(kind: str, label: str, fn: Callable[[Callable[[float, str], None]], object]) -> dict:
    jid = uuid.uuid4().hex[:12]
    job = {"id": jid, "kind": kind, "label": label, "status": "running", "progress": 0.0, "message": "", "result": None, "error": None, "started": time.time(), "ended": None}
    with _lock:
        _jobs[jid] = job

    def progress(p: float, msg: str = "") -> None:
        job["progress"] = round(p, 3)
        if msg:
            job["message"] = msg

    def target():
        try:
            job["result"] = fn(progress)
            job["status"] = "done"
            job["progress"] = 1.0
        except Exception as e:  # noqa: BLE001
            job["status"] = "error"
            job["error"] = f"{type(e).__name__}: {e}"
            job["trace"] = traceback.format_exc()[-3000:]
        job["ended"] = time.time()

    threading.Thread(target=target, daemon=True).start()
    return job


def get(jid: str) -> dict | None:
    return _jobs.get(jid)


def recent(limit: int = 30) -> list[dict]:
    with _lock:
        jobs = sorted(_jobs.values(), key=lambda j: j["started"], reverse=True)[:limit]
    return [{k: v for k, v in j.items() if k not in ("trace",)} for j in jobs]
