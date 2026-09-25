# 安全加固版部署说明

本地修改基于上游提交 `1be6493`。必须部署本目录源码构建的镜像；上游镜像、网盘 EXE、远程一键安装命令都不包含本次修复。这里的加固和测试不能证明系统绝对无漏洞，也不覆盖服务器操作系统、基础镜像或第三方服务的完整安全性。

## 新服务器部署

需要 Linux、Docker Compose v2、Python 3。前端源码构建使用 Node 24，容器会自动准备。

```bash
cd xianyu-ai-reply
bash build.sh rebuild
docker compose ps
```

首次运行生成 `.env` 和 `.secrets/`，文件权限为 600，密钥目录权限为 700。不会覆盖既有密钥。

- 管理员用户名：`admin`。初始随机密码由 `.secrets/admin_password` 提供，不写入日志。登录后更换。
- `.secrets/credential_key` 是凭据加密主密钥，必须独立备份。丢失后数据库中的加密凭据无法恢复；不要与数据库备份放在同一访问权限范围。
- 主密钥还按不同用途派生 JWT 和内部 API 密钥；数据库里旧的 JWT/内部令牌不再被采用。升级后旧登录令牌失效。
- 不要将 `.env`、`.secrets`、日志、浏览器数据目录提交或分享。服务器运行进程仍需要读到凭据；文件加密不能防御服务器已被完全控制的情况。
- 默认只发布宿主机 `127.0.0.1:9000`，8089/8090/8091 均不发布。容器内部通过服务名通信。
- 在宿主机配置自己的 HTTPS 反向代理，将流量转发到 `http://127.0.0.1:9000`，并支持 WebSocket Upgrade。不要为了访问后台把内部端口开放到公网。没有域名和证书前可先使用 SSH 本地转发验收。
- 设置 `FRONTEND_PUBLIC_URL`、`BACKEND_WEB_PUBLIC_URL` 为你的 HTTPS 入口域名；`CORS_ORIGINS` 默认为空，同域前端无需跨域。如果确需跨域，只填明确的受信任来源。

`deploy.sh` 和 `update.sh` 现在都从当前源码构建；不再拉取上游应用镜像。`deploy_remote.sh` 已禁用，避免绕过修复。已有外置数据库的部署者需自行修改 Compose 的连接配置，并保留 secrets、鉴权和端口隔离。

## 接口和功能兼容变化

- `/api/v1/messages/send` 只接受 `Authorization: Bearer <access_token>`，移除了 `api_key` 固定密钥认证。只能操作登录用户自己的启用账号，每用户每分钟最多 30 条，Redis 故障时拒绝发送。刷新令牌不能当访问令牌使用。
- `/password-login`、查询和取消会话都要求内部令牌。后端代理会自动附带令牌和用户 ID。查询/取消会话校验用户归属，登录保存校验闲鱼身份，禁止替换原账号。
- 公开注册默认关闭。需要开放时显式设置后端 `ENABLE_PUBLIC_REGISTRATION=true`；不要仅更改前端显示。
- Cookie、闲鱼密码、IM Token、账号 metadata 中的 Cookie 快照加密存储。账号导出、浏览器持久化目录以及其他业务记录仍可能包含敏感内容，应限制访问；不要将业务导出文件当作脱敏备份。
- SQL 不再输出语句/参数；删除已发现的完整 Cookie、Token、签名字符串日志，并关闭异常局部变量诊断。日志仍应按敏感文件保护。
- 远程广告、公告默认关闭并恢复 TLS 校验。卡券上游地址、预置 API 密钥默认清空。
- 远程 Token、滑块等凭据交互默认禁止。确需使用时，在部署环境 `REMOTE_CREDENTIAL_ORIGINS` 填写可信 HTTPS origin，例如 `https://service.example`，多个用逗号分隔；同时仍需在后台配置具体接口。严格匹配来源且不跟随重定向，不能填写用户信息或片段。允许某来源意味着主动信任它接收登录凭据；这不是第三方可信认证。
- 亦凡卡券不再使用预置 HTTP 商户/回调地址，需配置 `api_config.api_url` 和可信 HTTPS 回调来源。
- 桌面启动器的未签名下载、自动覆盖执行入口已禁用；更新需先审查源码，再重新构建。

## 升级已有数据

新安装无需迁移。旧安装请先更换默认管理员密码，再停机、备份数据库并限制旧备份的访问权限。旧的加密部署必须恢复原主密钥，不能生成替代密钥。

旧版明文数据首次迁移时，由部署者在停机后生成新主密钥（仅限原先确实没有密钥的明文安装）：

```bash
umask 077
mkdir -p .secrets
python3 - <<'PY'
import base64, os
from pathlib import Path
with Path('.secrets/credential_key').open('x') as f:
    f.write(base64.urlsafe_b64encode(os.urandom(32)).decode() + '\n')
PY
python3 scripts/prepare_secure_env.py
docker compose build
docker compose up -d mysql redis
docker compose run --rm --no-deps backend-web python scripts/migrate_credentials.py
docker compose up -d
```

迁移按事务执行，可重复运行；遇到错误密钥、损坏密文或容量超限则回滚。后端启动会拒绝遗留明文凭据。应在数据库健康后再执行迁移。旧管理员仍用 `admin123` 时会拒绝启动，不会静默改掉现有密码。

迁移不会删除旧备份和日志，也不会自动让已经泄露的闲鱼登录态失效。曾运行旧版本时，应另外撤销可能泄露的登录态、轮换相关密码/密钥，并处理旧日志和导出副本。加密主密钥轮换需要重新加密数据，不能直接覆盖文件。

## 验证及范围

生产 Python 依赖锁定在 `requirements.lock`，Docker 安装使用哈希校验；前端使用 `package-lock.json` 和 `npm ci --ignore-scripts`。依赖更新后必须重新运行审计与构建。

2026-09-25 发布整理时重新执行安全回归：19 项测试通过，主前端生产构建通过；测试覆盖请求级鉴权/越权、凭据加密、迁移、日志脱敏与部署配置。测试使用隔离数据库与模拟依赖，不代表真实闲鱼账号端到端验收。

本次发布整理环境的 Docker daemon 不可用，未重新执行完整容器部署与真实账号回归。部署者仍需验收 MySQL/Redis 初始化、Chromium、HTTPS、扫码/密码登录、消息回复、发货和重启恢复。返佣前端、移动客户端和预编译产物未纳入本次服务器发布验收。依赖审计结果具有时效性，请自行运行下面的检查，不将历史审计结果视为持续安全保证。

本地测试命令（独立虚拟环境，使用 Python 3.11）：

```bash
uv venv --python 3.11 .venv-test
uv pip install --python .venv-test/bin/python -r requirements.lock
uv pip install --python .venv-test/bin/python pytest pytest-asyncio aiosqlite PyYAML
PYTHONPATH=. .venv-test/bin/python -m pytest tests -q
cd frontend
npm ci --ignore-scripts
npm run build
npm audit
```

## 问题反馈

普通问题可在[本仓库 Issues](https://github.com/minrbook/xianyu-ai-reply/issues)提交。请使用测试数据复现，不在公开 Issue 中粘贴 Cookie、密码、Token、真实订单或未脱敏日志。此仓库为个人自用维护，没有安全响应时限承诺。

## CLI / MCP 客户端

接入方式见 [integrations/README.md](integrations/README.md)。凭据留在仓库外，绑定服务地址；HTTPS 校验开启且不跟随重定向。账号查询采用无凭据摘要接口，订单结果排除买家与收货字段。关键词回复等自由文本仍可能含私人信息，MCP 查询会将这些文本传给连接的 AI 客户端。

默认只读；开启写操作需要进程环境显式授权，每次调用还需确认参数。这不等价于服务端只读令牌或人类审批，应使用最低权限账号并配置 MCP 客户端审批。响应不记录或自动写入磁盘；操作超时不能证明未执行，发送等写请求不自动重试。
