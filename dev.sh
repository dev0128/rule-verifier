#!/usr/bin/env bash
# 사용:
#   ./dev.sh setup   — 백엔드 venv(uv) + 프런트 의존성(npm) 설치
#   ./dev.sh serve   — 프런트 빌드 후 백엔드 하나로 서빙 → http://127.0.0.1:8600
#   ./dev.sh dev     — 개발 모드: 백엔드 8600(--reload) + Vite 5180(프록시) 동시에
#   ./dev.sh cases   — 재현 케이스 전체를 모든 엔진 변형으로 실행
#   ./dev.sh test    — 백엔드 테스트
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cmd="${1:-serve}"
case "$cmd" in
  setup)
    (cd "$ROOT/backend" && uv sync)
    (cd "$ROOT/frontend" && npm install)
    ;;
  serve)
    (cd "$ROOT/frontend" && npm run build)
    cd "$ROOT/backend" && exec uv run rv serve --port "${PORT:-8600}"
    ;;
  dev)
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
