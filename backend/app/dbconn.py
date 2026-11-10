"""dev / 운영 DB 읽기 전용 접속 — bastion SSH 터널을 그때만 열고 닫는다.

rql-helper `tools/governance_export.ops_connection` 과 같은 방식(위키 0060):
- 접속 정보는 `python-tenant-helper/.env` 의 `*_DEV` / `*_OPS` (RV_DB_ENV_FILE 로 바꿀 수 있다). 이 레포에는 두지 않는다.
- 세션은 `SET SESSION TRANSACTION READ ONLY` + `time_zone='+00:00'`(운영과 같은 값으로 보이게).
- 화면이 DB 를 상시 들고 있지 않는다. 목록 갱신(동기화) 때만 터널을 연다 — 서버가 터널을 늘 쥐고 있지 않게.
"""

from __future__ import annotations

import os
import re
import socket
import subprocess
import threading
import time
from contextlib import contextmanager
from pathlib import Path

from app.config import REPO_DIR

ENVS = ("dev", "ops")
ENV_FILE = Path(os.environ.get("RV_DB_ENV_FILE", REPO_DIR.parent / "python-tenant-helper" / ".env")).expanduser()
_LOCK = threading.Lock()


class DbError(RuntimeError):
    pass


def _keys(env: str) -> tuple[str, ...]:
    s = env.upper()
    return (f"DSN_{s}", f"BASTION_USER_{s}", f"BASTION_HOST_{s}", f"BASTION_PRIVATE_KEY_{s}", f"REMOTE_HOST_{s}")


def _config(env: str) -> dict:
    if env not in ENVS:
        raise DbError(f"알 수 없는 환경: {env}")
    keys = _keys(env)
    cfg = {k: os.environ.get(k, "") for k in keys}
    if not all(cfg.values()) and ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            k, sep, v = line.partition("=")
            if sep and k.strip() in keys and not cfg.get(k.strip()):
                cfg[k.strip()] = v.strip().strip('"').strip("'")
    missing = [k for k in keys if not cfg.get(k)]
    if missing:
        raise DbError(f"{env} DB 접속 정보가 없다: {', '.join(missing)} — {ENV_FILE} 또는 환경변수(RV_DB_ENV_FILE)")
    m = re.match(r"^([^:]+):(.*)@tcp\(", cfg[f"DSN_{env.upper()}"])
    if not m:
        raise DbError(f"DSN_{env.upper()} 형식이 다르다 — user:password@tcp(host:port)/")
    cfg["user"], cfg["password"] = m.group(1), m.group(2)
    return cfg


def available() -> dict[str, bool]:
    out = {}
    for env in ENVS:
        try:
            _config(env)
            out[env] = True
        except DbError:
            out[env] = False
    return out


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@contextmanager
def connect(env: str):
    """읽기 전용 커넥션. 같은 서버 안에서 DB 조회는 한 번에 하나만(겹치면 DbError)."""
    import pymysql

    cfg = _config(env)
    s = env.upper()
    if not _LOCK.acquire(blocking=False):
        raise DbError("다른 DB 조회가 진행 중이다 — 끝난 뒤 다시")
    try:
        host, _, ssh_port = cfg[f"BASTION_HOST_{s}"].partition(":")
        port = _free_port()
        proc = subprocess.Popen(
            [
                "ssh", "-N", "-o", "ExitOnForwardFailure=yes", "-o", "ConnectTimeout=10",
                "-o", "StrictHostKeyChecking=accept-new",
                "-i", os.path.expanduser(cfg[f"BASTION_PRIVATE_KEY_{s}"]), "-p", ssh_port or "22",
                "-L", f"{port}:{cfg[f'REMOTE_HOST_{s}']}:3306", f"{cfg[f'BASTION_USER_{s}']}@{host}",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        try:
            for _ in range(100):  # 최대 20초
                if proc.poll() is not None:
                    raise DbError(f"bastion 터널 실패: {proc.stderr.read().decode(errors='replace').strip()}")
                try:
                    socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
                    break
                except OSError:
                    time.sleep(0.2)
            else:
                raise DbError("bastion 터널이 20초 안에 열리지 않았다")
            conn = pymysql.connect(
                host="127.0.0.1", port=port, user=cfg["user"], password=cfg["password"],
                charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor, connect_timeout=10, read_timeout=120,
            )
            try:
                with conn.cursor() as cur:
                    cur.execute("SET SESSION TRANSACTION READ ONLY")
                    cur.execute("SET time_zone = '+00:00'")
                yield conn
            finally:
                conn.close()
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
    finally:
        _LOCK.release()


def query(conn, sql: str, params: tuple = ()) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return list(cur.fetchall())
