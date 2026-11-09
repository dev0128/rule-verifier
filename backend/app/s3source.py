"""S3 에서 진단을 골라 컨디션 파일(룰셋 SET-….json)과 수집 데이터(Raw/raw_data.json)를 받는다.

경로 (엔진 Util/Set_Bucket.py 와 같다 — 위키 0060):
    버킷   dclo-{env}-{root_ins_dt}-{sha1(root_id)}       테넌트마다 하나
    진단   CSPM/{group_id}/{key_id}/{his_id}/
             SET-xxxxxxxx.json    ← 컨디션 파일: 그 진단에 쓴 룰셋(룰별 args · enabled · level)
             Raw/raw_data.json    ← 수집 데이터 {"info":…, "raw": {region: {service: {method: [...]}}}}
    group_id 는 일반 진단이면 GROUP-…, 거버넌스 진단이면 GOVERNANCE-….

받은 파일은 data/diagnoses/<진단 id>/ 에 엔진 폴더 모양 그대로 둔다(.gitignore — 고객 환경 데이터).
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import time
from pathlib import Path

import boto3

from app.config import AWS_PROFILES, DIAG_DIR

BUCKET_RE = re.compile(r"^dclo-(dev|ops|stg)-(\d+)-([0-9a-f]{40})$")
SAFE = re.compile(r"[^A-Za-z0-9._-]")


def _s3(profile: str):
    if profile not in AWS_PROFILES:
        raise ValueError(f"허용되지 않은 프로파일: {profile}")
    return boto3.Session(profile_name=profile).client("s3")


def _prefixes(profile: str, bucket: str, prefix: str) -> list[str]:
    s3 = _s3(profile)
    out = []
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix, Delimiter="/"):
        out += [p["Prefix"][len(prefix):].rstrip("/") for p in page.get("CommonPrefixes", [])]
    return out


def list_buckets(profile: str, tenant: str | None = None) -> list[dict]:
    """진단 버킷 목록. tenant(root_id) 를 주면 sha1 로 그 테넌트 버킷만."""
    want = hashlib.sha1(tenant.encode()).hexdigest() if tenant else None
    out = []
    for b in _s3(profile).list_buckets()["Buckets"]:
        m = BUCKET_RE.match(b["Name"])
        if not m or (want and m.group(3) != want):
            continue
        out.append({"bucket": b["Name"], "env": m.group(1), "root_ins_dt": int(m.group(2)), "root_sha1": m.group(3), "created": b["CreationDate"].isoformat()})
    return sorted(out, key=lambda x: x["bucket"])


def list_groups(profile: str, bucket: str) -> list[str]:
    return _prefixes(profile, bucket, "CSPM/")


def list_keys(profile: str, bucket: str, group: str) -> list[str]:
    return _prefixes(profile, bucket, f"CSPM/{group}/")


def list_histories(profile: str, bucket: str, group: str, key: str) -> list[dict]:
    his = _prefixes(profile, bucket, f"CSPM/{group}/{key}/")
    out = []
    for h in his:
        m = re.match(r"DIAG-(\d{4})(\d{2})(\d{2})", h)
        out.append({"his_id": h, "date": f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else None})
    return sorted(out, key=lambda x: x["his_id"], reverse=True)


def list_history_files(profile: str, bucket: str, group: str, key: str, his: str) -> dict:
    """진단 폴더의 컨디션 파일(SET-*.json)과 raw 유무 · 크기."""
    s3 = _s3(profile)
    prefix = f"CSPM/{group}/{key}/{his}/"
    rulesets, raw = [], None
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix, Delimiter="/"):
        for o in page.get("Contents", []):
            name = o["Key"][len(prefix):]
            if re.match(r"^SET-[\w-]+\.json$", name) or re.match(r"^GOVERNANCE-[\w-]+\.json$", name):
                rulesets.append({"name": name, "size": o["Size"], "modified": o["LastModified"].isoformat()})
    try:
        h = s3.head_object(Bucket=bucket, Key=prefix + "Raw/raw_data.json")
        raw = {"size": h["ContentLength"], "modified": h["LastModified"].isoformat()}
    except s3.exceptions.ClientError:
        raw = None
    return {"prefix": prefix, "rulesets": sorted(rulesets, key=lambda x: x["name"]), "raw": raw}


def diag_id(env: str, key: str, his: str) -> str:
    return SAFE.sub("_", f"{env}__{key}__{his}")


def download(profile: str, bucket: str, group: str, key: str, his: str, progress=None) -> str:
    """컨디션 파일 전부 + raw 를 받아 data/diagnoses/<id>/ 에 둔다. 이미 있으면 raw 는 다시 받지 않는다."""
    m = BUCKET_RE.match(bucket)
    if not m:
        raise ValueError(f"진단 버킷 이름이 아님: {bucket}")
    s3 = _s3(profile)
    files = list_history_files(profile, bucket, group, key, his)
    if not files["raw"]:
        raise FileNotFoundError(f"{files['prefix']}Raw/raw_data.json 없음")
    did = diag_id(m.group(1), key, his)
    dest = DIAG_DIR / did
    (dest / "Raw").mkdir(parents=True, exist_ok=True)
    for rs in files["rulesets"]:
        s3.download_file(bucket, files["prefix"] + rs["name"], str(dest / rs["name"]))
    raw_path = dest / "Raw" / "raw_data.json"
    if not raw_path.exists() or raw_path.stat().st_size != files["raw"]["size"]:
        total = files["raw"]["size"]
        done = {"n": 0}

        def cb(n):
            done["n"] += n
            if progress:
                progress(done["n"] / total if total else 1.0)

        tmp = raw_path.with_suffix(".part")
        s3.download_file(bucket, files["prefix"] + "Raw/raw_data.json", str(tmp), Callback=cb)
        tmp.replace(raw_path)
    meta = {
        "id": did,
        "profile": profile,
        "env": m.group(1),
        "bucket": bucket,
        "group_id": group,
        "key_id": key,
        "his_id": his,
        "s3_prefix": files["prefix"],
        "raw_size": files["raw"]["size"],
        "raw_modified": files["raw"]["modified"],
        "rulesets": [r["name"] for r in files["rulesets"]],
        "downloaded_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    (dest / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    return did


def local_diagnoses() -> list[dict]:
    """받아 둔 진단. 손으로 넣은 폴더(Raw/raw_data.json + SET-*.json)도 meta 없이 보인다."""
    out = []
    for d in sorted(DIAG_DIR.iterdir() if DIAG_DIR.exists() else []):
        raw = d / "Raw" / "raw_data.json"
        if not d.is_dir() or not raw.exists():
            continue
        meta = {}
        if (d / "meta.json").exists():
            meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
        rulesets = sorted(p.name for p in d.glob("*.json") if p.name != "meta.json")
        out.append({"id": d.name, **meta, "rulesets": rulesets, "raw_size": raw.stat().st_size, "account_id": _account_id(raw)})
    return out


def _account_id(raw: Path) -> str | None:
    # raw_data.json 앞부분의 "info" 만 읽는다(파일 전체를 읽지 않게)
    with raw.open("r", encoding="utf-8", errors="replace") as f:
        head = f.read(4096)
    m = re.search(r'"account_id"\s*:\s*"?(\d{12})', head)
    return m.group(1) if m else None


def diag_dir(did: str) -> Path:
    p = (DIAG_DIR / did).resolve()
    if DIAG_DIR.resolve() not in p.parents or not p.is_dir():
        raise FileNotFoundError(did)
    return p


def delete_local(did: str) -> None:
    shutil.rmtree(diag_dir(did))


def production_result(did: str, ruleset: str) -> Path | None:
    """운영 엔진이 그 진단에서 실제로 남긴 결과(Analyze/<룰셋>.json). 없으면 S3 에서 그 파일만 받는다."""
    d = diag_dir(did)
    local = d / "Analyze" / ruleset
    if local.exists():
        return local
    meta_p = d / "meta.json"
    if not meta_p.exists():
        return None
    meta = json.loads(meta_p.read_text(encoding="utf-8"))
    s3 = _s3(meta["profile"])
    local.parent.mkdir(exist_ok=True)
    tmp = local.with_suffix(".part")
    try:
        s3.download_file(meta["bucket"], f"{meta['s3_prefix']}Analyze/{ruleset}", str(tmp))
    except Exception:  # noqa: BLE001 — 오래된 진단은 Analyze 결과가 없을 수 있다
        tmp.unlink(missing_ok=True)
        return None
    tmp.replace(local)
    return local


def read_ruleset(did: str, name: str) -> dict:
    p = diag_dir(did) / name
    if p.parent != diag_dir(did) or not p.exists():
        raise FileNotFoundError(name)
    return json.loads(p.read_text(encoding="utf-8"))
