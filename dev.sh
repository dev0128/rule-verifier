#!/usr/bin/env bash
# 사용:
#   ./dev.sh setup   — 백엔드 venv(uv) + 프런트 의존성(npm) 설치
#   ./dev.sh serve   — 프런트 빌드 후 백엔드 하나로 서빙 → http://127.0.0.1:8600 (포트를 쥔 프로세스는 먼저 종료)
#   ./dev.sh dev     — 개발 모드: 백엔드 8600(--reload) + Vite 5180(프록시) 동시에
#   ./dev.sh cases   — 재현 케이스 전체를 모든 엔진 변형으로 실행
#   ./dev.sh test    — 백엔드 테스트
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cmd="${1:-serve}"

# 포트를 쥔 프로세스가 있으면 종료한다(이전에 띄운 서버 · --reload 자식까지). TERM 후 3초 안에 안 끝나면 KILL.
free_port() {
  local port="$1" pids
  pids="$(lsof -t -iTCP:"$port" -sTCP:LISTEN 2>/dev/null || true)"
  [ -z "$pids" ] && return 0
  echo "[dev.sh] 포트 $port 사용 중 — 종료: $(echo $pids | tr '\n' ' ')"
  kill $pids 2>/dev/null || true
  for _ in 1 2 3 4 5 6; do
    sleep 0.5
    lsof -t -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1 || return 0
  done
  kill -9 $(lsof -t -iTCP:"$port" -sTCP:LISTEN 2>/dev/null) 2>/dev/null || true
}
case "$cmd" in
  setup)
    (cd "$ROOT/backend" && uv sync)
    (cd "$ROOT/frontend" && npm install)
    ;;
  serve)
    (cd "$ROOT/frontend" && npm run build)
    free_port "${PORT:-8600}"
    cd "$ROOT/backend" && exec uv run rv serve --port "${PORT:-8600}"
    ;;
  dev)
    free_port 8600
    free_port 5180
    (cd "$ROOT/backend" && uv run rv serve --port 8600 --reload) &
    trap 'kill 0' EXIT
    cd "$ROOT/frontend" && npm run dev
    ;;
  cases)
    cd "$ROOT/backend"
    for v in $(python3 -c "import json;print(' '.join(x['id'] for x in json.load(open('variants.json'))))"); do
      uv run rv cases --variant "$v"
    done
    ;;
  test)
    cd "$ROOT/backend" && uv run pytest -q
    ;;
  *) echo "unknown: $cmd"; exit 1 ;;
esac
