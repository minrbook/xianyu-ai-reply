#!/usr/bin/env bash
# 原脚本拉取上游镜像，会丢失本地安全修复，因此禁用。
echo '安全加固版已禁用远程镜像部署。外置 MySQL/Redis 请修改源码 Compose 的连接配置，保留 secrets、内部鉴权与端口隔离。参见 SECURITY.md。' >&2
exit 1
