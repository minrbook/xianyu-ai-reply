<div align="center">

# Xianyu AI Reply

**闲鱼 AI 自动回复 · 多账号管理 · 自托管安全加固版**

基于 FastAPI、React、MySQL、Redis 与 Playwright，面向个人自用部署与源码学习。

[快速开始](#快速开始) · [改进对照](#相较上游的改进) · [安全与迁移](SECURITY.md) · [原项目](https://github.com/zhinianboke/xianyu-auto-reply)

</div>

## 项目定位

本项目是在 [zhinianboke/xianyu-auto-reply](https://github.com/zhinianboke/xianyu-auto-reply) 基础上维护的个人自用分支，用于保存、分享安全加固与部署改进。核心业务能力来自上游；本分支重点调整鉴权、敏感数据保护、第三方服务边界和源码构建流程。

- **上游基线**：[`1be6493`](https://github.com/zhinianboke/xianyu-auto-reply/commit/1be6493c36f8c66547b91d3940ac32580b1937b9)。
- **本次修改日期**：2026-09-25。
- **维护范围**：主系统的源码与自托管部署；个人维护，不承诺商业支持或持续跟进全部上游功能。
- **许可证**：[AGPL-3.0](LICENSE)，保留原项目及其他贡献者的版权与许可声明。

安全改进仅针对已检查的代码路径，不等同于完整安全审计。首次安装与旧版升级均请先阅读 [SECURITY.md](SECURITY.md)。

## 功能概览

以下业务能力主要继承自上游，不作为本分支原创功能宣称。

| 能力 | 内容 |
| --- | --- |
| 多账号管理 | 登录、账号状态、Cookie 维护与续期 |
| 自动回复 | 关键词、默认回复、商品专属回复、AI 上下文对话 |
| 在线聊天 | 会话列表、消息收发、处理与发送结果记录 |
| 自动发货 | 卡券与虚拟商品发货、补发、发货日志 |
| 商品与订单 | 商品发布、素材管理、订单同步、评价与状态跟踪 |
| 任务与通知 | 定时任务、通知渠道与风控记录 |

仓库同时保留 `promotion/` 返佣子系统、`xianyu-mobile/` 移动客户端和 `launcher/` 桌面启动器源码。默认 Docker Compose 仅部署主系统；这些附属客户端与子系统未纳入本次完整功能验收。

## 相较上游的改进

下表描述的是**所基于的上游提交中观察到的实现和风险**，不代表上游当前版本仍然存在相同问题，也不代表相关风险已被实际利用。

| 范围 | 基线中的实现 / 风险 | 本分支的改进 |
| --- | --- | --- |
| 外部消息发送 | 固定默认 API 密钥回退；发送路径缺少登录用户与账号归属绑定 | 改为 Bearer 访问令牌；校验本人启用账号；限制参数长度与格式；每用户每分钟最多 30 条，Redis 故障时拒绝发送 |
| 密码登录服务 | 登录任务与会话查询、取消路径的鉴权和归属检查不足 | 要求内部令牌与用户归属；保存登录结果前校验闲鱼身份，禁止替换成其他账号 |
| 默认管理员 | 固定初始密码，初始化日志输出密码 | 首次部署生成随机密码并通过 secret 文件读取；旧管理员仍使用默认密码时拒绝启动 |
| 凭据存储 | Cookie、登录密码、IM Token、Cookie 快照可在数据库中以明文保存 | 增加 Fernet 加密存储；主密钥独立于数据库；缺失或错误密钥拒绝处理；提供事务迁移与启动检查 |
| JWT 与内部令牌 | 鉴权密钥持久化于业务数据库，数据库泄露会扩大影响 | 从独立主密钥按用途派生不同密钥；限制 JWT 算法并要求必要字段；访问接口拒绝刷新令牌 |
| 敏感日志与错误 | SQL 参数、部分 Cookie / Token / 签名日志及异常细节可能暴露凭据 | 关闭 SQL 参数输出、移除已发现的凭据日志、增加日志脱敏、关闭异常局部变量诊断，通用错误不向客户端回传异常内容 |
| 第三方凭据交互 | 配置远程服务后可直接发送登录相关凭据 | 默认禁止；必须显式配置可信 HTTPS origin，严格匹配并禁止自动跟随重定向 |
| 远程内容与更新 | 远程内容默认开启，部分请求关闭 TLS 校验；桌面更新可下载后覆盖执行 | 远程广告与公告默认关闭，恢复 TLS 校验；禁用未签名自动下载与覆盖执行入口 |
| 部署默认值 | 预设数据库 / Redis 密码、宽泛 CORS、宿主机映射内部服务端口 | 随机生成部署密码；默认关闭公开注册；收紧 CORS；仅在 `127.0.0.1` 发布前端入口 |
| 构建与依赖 | 上游镜像无法包含本地加固；依赖安装难以复现 | 从当前源码构建；Python 锁文件与哈希校验；前端 `npm ci --ignore-scripts`；更新部分依赖 |
| 共机部署 | 需要额外限制单个项目对宿主机的影响 | 提供可选 CPU / 内存 / 进程 / 日志限制、共享运行时镜像与主机观测脚本 |

对应实现可从 [消息接口](backend-web/app/api/routes/message.py)、[凭据加密](common/utils/credential_crypto.py)、[远程来源校验](common/utils/remote_security.py)、[日志处理](common/utils/logging_utils.py)、[回归测试](tests/)和 [Compose 编排](docker-compose.yml)核对。

发布整理还移除了旧 README 的联系方式、群二维码、网盘分发与推广内容，并同步修正了环境变量示例。原项目的获取入口统一保留为 GitHub 链接。移除上游预填的验证码服务私钥；如启用后台极验验证码，需在根目录 `.env` 配置自己的 `GEETEST_CAPTCHA_ID` 和 `GEETEST_PRIVATE_KEY`，缺失时拒绝初始化。

为避免再次分发上游旧提交中的凭据示例，本仓库以清理后的源码快照作为初始提交；完整上游历史请访问原项目，基线提交见上文。

## 快速开始

### 环境准备

准备 Linux 主机、Docker Engine、Docker Compose v2、Git 和 Python 3。构建需要能够下载基础镜像、Python / npm 依赖和浏览器组件。容器构建使用 Python 3.11 与 Node.js 24，无需在宿主机另装 Node.js。

### 从源码部署

```bash
git clone https://github.com/minrbook/xianyu-ai-reply.git
cd xianyu-ai-reply
bash build.sh rebuild
docker compose ps
```

首次运行自动生成 `.env` 与 `.secrets/`，重复执行不会覆盖已有密钥。服务健康后，在**部署主机本地**访问 `http://127.0.0.1:9000`。

管理员用户名为 `admin`，初始密码保存在 `.secrets/admin_password`，仅在部署主机上读取，登录后更换。`.secrets/credential_key` 是解密现有数据必需的主密钥，必须单独备份；不要删除或重新生成它来修复启动问题。

远程服务器可先通过 SSH 隧道访问：

```bash
ssh -L 9000:127.0.0.1:9000 user@your-server
```

然后在自己电脑打开 `http://127.0.0.1:9000`。正式入口请使用支持 WebSocket 的 HTTPS 反向代理，并在根目录 `.env` 配置 `FRONTEND_PUBLIC_URL` 和 `BACKEND_WEB_PUBLIC_URL`。修改配置后执行 `bash build.sh start` 使 Compose 应用配置。

**不要使用上游预编译镜像、网盘 EXE 或远程一键安装脚本代替本仓库源码构建，它们不包含本分支修改。**

### 日常维护

```bash
bash build.sh status     # 查看服务状态
bash build.sh logs       # 查看最近日志并持续跟踪
bash build.sh restart    # 重启现有容器
bash build.sh stop       # 停止服务，保留数据卷
bash build.sh rebuild    # 从当前源码重新构建并启动
```

`deploy.sh` 与 `update.sh` 都调用当前源码构建流程；`update.sh` 不会自动拉取 Git 更新。更新前自行检查代码差异、备份数据与主密钥。`deploy_remote.sh` 已禁用。

**旧版本升级不能直接套用首次安装流程。** 请按 [数据迁移说明](SECURITY.md#升级已有数据)停机、备份并迁移明文凭据。旧版业务 API、令牌和第三方服务配置存在兼容变化。

## 配置与部署边界

| 配置 | 默认行为 / 用途 |
| --- | --- |
| `.env` | 部署脚本生成的数据库与 Redis 配置，不提交到 Git |
| `.secrets/credential_key` | 凭据加密及鉴权密钥派生，需独立保护与备份 |
| `.secrets/admin_password` | 首次管理员创建所用密码，不会自动重置已有管理员 |
| `ENABLE_PUBLIC_REGISTRATION` | 默认 `false`；需要时显式开启后端注册 |
| `CORS_ORIGINS` | 默认空，同域无需跨域授权；只允许明确的受信任来源 |
| `REMOTE_CREDENTIAL_ORIGINS` | 默认空；远程凭据服务必须显式允许 HTTPS origin |
| `ENABLE_REMOTE_ADS` / `ENABLE_REMOTE_ANNOUNCEMENTS` / `ENABLE_REMOTE_POPUP_ANNOUNCEMENTS` | 默认 `false` |
| `FRONTEND_PUBLIC_URL` / `BACKEND_WEB_PUBLIC_URL` | 部署者自己的 HTTPS 入口，用于分享与资源链接 |

各后端的 `.env.example` 是直接运行源码时的配置参考，不替代根目录 Compose 配置。AI 服务凭据和模型选项需按后台实际支持的提供商配置。允许远程凭据来源即表示信任该服务接收登录资料，不代表本项目为其安全性背书。

可选的 `docker-compose.shared.yml` 需要 Compose **2.24.4+**，应与主编排合用，并预先构建带 `RELEASE_ID` 标签的 `xianyu-app`、`xianyu-frontend` 镜像。该配置使用 `127.0.0.1:19000`，并限制各容器资源；不是首次安装的默认路径。共机观测脚本 `scripts/shared_host_guard.py` 要求显式设置 `SHARED_HOST_PROJECT` 和逗号分隔的 `SHARED_HOST_DOMAINS`，只有带 `--armed` 才会在连续失败后停止指定项目容器。`.shared-host` 模式还要求部署者提供网络检查脚本，可通过 `SHARED_HOST_NETWORK_CHECK` 指定路径。

## 项目结构

```text
.
├── backend-web/          # FastAPI 业务 API 与后台服务
├── websocket/            # 闲鱼连接、登录、消息与订单联动
├── scheduler/            # 定时任务
├── common/               # 共享模型、数据库、凭据保护与公共服务
├── frontend/             # React + TypeScript 管理界面
├── scripts/              # 密钥初始化、凭据迁移、部署验证
├── tests/                # 安全回归测试
├── docker/               # 前端与共享运行时镜像构建
├── promotion/            # 上游返佣子系统
├── xianyu-mobile/        # 上游移动客户端
├── launcher/             # 上游桌面启动器，自动覆盖更新已禁用
├── docker-compose.yml    # 默认源码部署
├── requirements.lock     # Python 生产依赖及哈希
└── SECURITY.md           # 加固范围、迁移步骤与安全注意事项
```

## 验证与已知限制

2026-09-25 发布整理时重新执行安全回归，**19 项测试通过**，主前端生产构建通过。覆盖请求鉴权、账号归属、发送限流、刷新令牌隔离、凭据加密与迁移、日志脱敏、第三方来源限制及部署配置。

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

测试使用隔离数据库和模拟依赖，不代表真实闲鱼账号端到端验收。本次发布整理没有重新验收完整 Docker 部署、真实账号登录与发货。上游平台协议变化、账号风控与第三方服务可用性仍会影响运行。

数据库字段加密不覆盖全部业务数据：订单、聊天记录、账号导出、浏览器目录与备份仍需限制访问。已有泄露不能靠升级撤销，需要另行轮换相关凭据。移动端、返佣子系统和桌面打包程序应单独验证。

## 致谢与原项目

感谢 **[zhinianboke](https://github.com/zhinianboke)** 及原项目贡献者开源完整的业务系统，为本分支提供基础。本仓库是基于其成果的派生维护版本。

- 原项目源码与文档：[zhinianboke/xianyu-auto-reply](https://github.com/zhinianboke/xianyu-auto-reply)
- 原项目提交记录：[上游历史](https://github.com/zhinianboke/xianyu-auto-reply/commits/main/)
- 原项目问题反馈：[上游 Issues](https://github.com/zhinianboke/xianyu-auto-reply/issues)

同时保留上游对以下项目的致谢：

- [cv-cat/XianYuApis](https://github.com/cv-cat/XianYuApis)：闲鱼 API 技术参考。
- [shaxiu/XianyuAutoAgent](https://github.com/shaxiu/XianyuAutoAgent)：自动化处理思路。
- [Kaguya233qwq/myfish](https://github.com/Kaguya233qwq/myfish)：扫码登录思路。

本分支的问题请提交至[本仓库 Issues](https://github.com/minrbook/xianyu-ai-reply/issues)，附上版本、复现步骤与脱敏日志。请勿公开真实 Cookie、Token、密码、买家资料或完整数据库。

## 许可证与使用说明

本项目沿用 [GNU AGPL v3.0](LICENSE)。请保留原作者及贡献者的版权与许可声明，分发修改版本时遵循许可证；通过网络提供修改后服务时，也应按许可证向使用者提供对应源码。子目录中的独立许可声明同样保留。

项目与闲鱼及其运营方无官方关联。请仅操作自己有权管理的账号，遵守平台规则，保护买家隐私。软件按许可证以现状提供，不附带担保。
