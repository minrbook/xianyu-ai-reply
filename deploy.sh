#!/usr/bin/env bash
# 安全加固版只构建本地源码，不拉取上游应用镜像。
set -euo pipefail
exec bash "$(dirname "$0")/build.sh" rebuild
