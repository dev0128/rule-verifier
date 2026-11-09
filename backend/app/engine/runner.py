"""워커(worker.py)를 서브프로세스로 띄워 변형 하나로 룰을 돌린다."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

from app.engine.source import Variant, engine_src, overlay_dir

WORKER = Path(__file__).resolve().parent / "worker.py"


class WorkerError(RuntimeError):
    pass


def run_job(variant: Variant, job: dict, timeout: float = 3600) -> dict:
    job = {
        **job,
        "engine_src": str(engine_src(variant.engine_ref)),
        "overlay": str(overlay_dir(variant)) if variant.overlay else None,
    }
    with tempfile.TemporaryDirectory(prefix="rv-") as td:
        jp, op = Path(td) / "job.json", Path(td) / "out.json"
        jp.write_text(json.dumps(job, ensure_ascii=False), encoding="utf-8")
        # cwd 를 임시 폴더로 — 엔진 src 의 `app` 패키지와 백엔드 `app` 이 섞이지 않게 워커는 스크립트로 띄운다
        proc = subprocess.run(
            [sys.executable, "-I", str(WORKER), str(jp), str(op)],
            cwd=td,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if proc.returncode != 0 or not op.exists():
            raise WorkerError((proc.stderr or proc.stdout or "worker failed")[-4000:])
        out = json.loads(op.read_text(encoding="utf-8"))
    out["meta"]["variant"] = variant.id
    return out
