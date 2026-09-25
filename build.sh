#!/usr/bin/env bash
# 从当前检出的源码构建；不会下载上游应用镜像或删除数据库卷。
set -euo pipefail
cd "$(dirname "$0")"
command -v docker >/dev/null || { echo '请先安装 Docker 和 Compose v2'; exit 1; }
if [[ -f .shared-host ]]; then
  compose=(docker compose -p "${SHARED_HOST_PROJECT:-xianyu-hz}" -f docker-compose.yml -f docker-compose.shared.yml)
  if [[ "${1:-rebuild}" == start || "${1:-rebuild}" == restart ]]; then
    python3 "${SHARED_HOST_NETWORK_CHECK:-/opt/xianyu/ops/check-network.py}"
  fi
  case "${1:-rebuild}" in
    rebuild) echo '共机部署禁止现场构建；请在构建机生成并验收镜像后发布。'; exit 1 ;;
    start) "${compose[@]}" config --quiet; "${compose[@]}" up -d --no-build --pull never ;;
    stop) "${compose[@]}" stop ;;
    restart) "${compose[@]}" restart ;;
    logs) "${compose[@]}" logs -f --tail=100 ;;
    status) "${compose[@]}" ps ;;
    *) echo '用法: bash build.sh [start|stop|restart|logs|status]'; exit 2 ;;
  esac
  exit
fi
case "${1:-rebuild}" in
  rebuild|start)
    python3 scripts/prepare_secure_env.py
    docker compose config --quiet
    if [ "${1:-rebuild}" = rebuild ]; then
      docker compose up -d --build
    else
      docker compose up -d
    fi
    ;;
  stop) docker compose stop ;;
  restart) docker compose restart ;;
  logs) docker compose logs -f --tail=100 ;;
  status) docker compose ps ;;
  *) echo '用法: bash build.sh [rebuild|start|stop|restart|logs|status]'; exit 2 ;;
esac
