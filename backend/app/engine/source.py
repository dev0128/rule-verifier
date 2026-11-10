"""엔진 변형(variant) — "어떤 엔진 소스 + 어떤 오버레이" 로 룰을 돌릴지.

- `engine_ref`: k8s-engine 의 git ref(태그 · 브랜치 · 커밋). `git archive` 로 DATA_DIR/engines/<sha>/ 에 풀어 쓴다.
  이 도구는 엔진 레포에 아무것도 쓰지 않는다. `WORKTREE` 면 k8s-engine 작업 트리를, `WORKTREE:<경로>` 면 그 git worktree
  (예: 수정 브랜치 `~/dclo/k8s-engine-fix`)를 그대로 쓴다 — 미커밋 수정 포함. 경로는 워크스페이스(~/dclo) 기준 상대 경로도 된다.
- `overlay`: 이 레포 backend/overlays/<이름>/ — 고친 룰 함수(REME_…)와 수집 보정(preprocess_raw)을 덮어쓴다.
  엔진에 고치기 전에 "고치면 결과가 어떻게 바뀌나" 를 먼저 보는 용도다. 엔진에 반영되면 engine_ref 를 그 커밋으로 바꾸고 오버레이를 비운다.
"""

from __future__ import annotations

import json
import subprocess
import tarfile
import io
from dataclasses import dataclass, asdict
from pathlib import Path

from app.config import ENGINE_REPO, ENGINES_DIR, OVERLAYS_DIR, VARIANTS_PATH

# 룰 실행에 필요한 경로만 푼다(엔진 src 에는 수십 MB 짜리 샘플 raw 등이 섞여 있다).
ARCHIVE_PATHS = ["src/AWS", "src/ANALYZE_CORE", "src/Util/Query_BASE.py"]


@dataclass
class Variant:
    id: str
    label: str
    engine_ref: str
    overlay: str | None = None
    description: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def load_variants() -> list[Variant]:
    return [Variant(**v) for v in json.loads(VARIANTS_PATH.read_text(encoding="utf-8"))]


def get_variant(variant_id: str) -> Variant:
    for v in load_variants():
        if v.id == variant_id:
            return v
    raise KeyError(f"unknown variant: {variant_id}")


def _git(*args: str) -> str:
    return subprocess.run(["git", "-C", str(ENGINE_REPO), *args], check=True, capture_output=True, text=True).stdout.strip()


def worktree_path(ref: str) -> Path | None:
    """`WORKTREE` → k8s-engine, `WORKTREE:<경로>` → 그 worktree. 아니면 None."""
    if ref == "WORKTREE":
        return ENGINE_REPO
    if ref.startswith("WORKTREE:"):
        p = Path(ref.split(":", 1)[1]).expanduser()
        return (p if p.is_absolute() else ENGINE_REPO.parent / p).resolve()
    return None


def _git_at(path: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(path), *args], check=True, capture_output=True, text=True).stdout.strip()


def resolve_ref(ref: str) -> dict:
    wt = worktree_path(ref)
    if wt:
        head = _git_at(wt, "rev-parse", "--short", "HEAD")
        branch = _git_at(wt, "branch", "--show-current")
        # porcelain 줄은 " M 경로" 처럼 앞 공백이 의미가 있어 strip 하지 않는다
        changed = subprocess.run(["git", "-C", str(wt), "status", "--porcelain", "--", *ARCHIVE_PATHS],
                                 check=True, capture_output=True, text=True).stdout.rstrip("\n")
        return {
            "ref": ref, "sha": head, "branch": branch, "path": str(wt), "dirty": bool(changed),
            "changed_files": [ln[3:] for ln in changed.splitlines()],
            "subject": f"작업 트리 {branch or ''}(미커밋 포함) — {_git_at(wt, 'log', '-1', '--format=%ci %s')}",
        }
    sha = _git("rev-parse", f"{ref}^{{commit}}")
    subject = _git("log", "-1", "--format=%ci %s", sha)
    return {"ref": ref, "sha": sha[:8], "full_sha": sha, "dirty": False, "subject": subject}


def engine_src(ref: str) -> Path:
    """ref 의 엔진 src 디렉터리. 이미 풀어 둔 것이 있으면 그대로 쓴다."""
    wt = worktree_path(ref)
    if wt:
        return wt / "src"
    sha = _git("rev-parse", f"{ref}^{{commit}}")
    dest = ENGINES_DIR / sha
    marker = dest / ".complete"
    if marker.exists():
        return dest / "src"
    data = subprocess.run(
        ["git", "-C", str(ENGINE_REPO), "archive", "--format=tar", sha, "--", *ARCHIVE_PATHS],
        check=True,
        capture_output=True,
    ).stdout
    dest.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(data)) as tf:
        tf.extractall(dest, filter="data")
    marker.write_text(sha)
    return dest / "src"


def overlay_dir(variant: Variant) -> Path | None:
    if not variant.overlay:
        return None
    p = (OVERLAYS_DIR / variant.overlay).resolve()
    if not p.is_dir() or OVERLAYS_DIR.resolve() not in p.parents:
        raise ValueError(f"overlay not found: {variant.overlay}")
    return p


def describe(variant: Variant) -> dict:
    out = variant.to_dict()
    try:
        out["engine"] = resolve_ref(variant.engine_ref)
    except subprocess.CalledProcessError as e:
        out["engine"] = {"ref": variant.engine_ref, "error": (e.stderr or str(e)).strip()}
    od = overlay_dir(variant) if variant.overlay else None
    if od:
        from app.engine.overlay_info import overlay_summary

        out["overlay_rules"] = overlay_summary(od)
    return out
