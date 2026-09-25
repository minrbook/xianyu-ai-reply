# CLI 与 MCP 操作入口

连接你已经部署的 Xianyu AI Reply 服务，复用现有 Bearer 鉴权与账号权限。客户端不直接读数据库，也不使用内部服务令牌或闲鱼 Cookie。

## 安装

需要 Python 3.11+。在仓库根目录执行：

```bash
uv venv --python 3.11 .venv-tools
uv pip install --python .venv-tools/bin/python --require-hashes -r integrations/requirements.lock
uv pip install --python .venv-tools/bin/python --no-deps -e ./integrations
source .venv-tools/bin/activate
xianyu --help
```

锁文件包含 CLI 与 MCP 依赖。仅需 CLI 时，也可在独立虚拟环境中执行 `pip install ./integrations`；需要 MCP 时使用 `pip install './integrations[mcp]'`。后两种安装按版本范围解析依赖，复现发布环境请用锁文件。

MCP 采用[官方 Python SDK 的 v1 维护分支](https://py.sdk.modelcontextprotocol.io/v1/)，约束为 `mcp>=1.28,<2`，锁文件固定实际版本；不依赖全局安装的同名第三方 FastMCP 包。本入口仅使用 stdio，不开放额外 HTTP 端口。

## 连接与令牌

先在自己部署的 Web 后台正常登录，完成启用的验证码。浏览器开发者工具的 Application / Storage → Local Storage 中，`auth_token` 是访问令牌。只在本机读取和使用它，不复制进聊天、Issue、代码、截图或命令行参数；`refresh_token` 不能用作访问令牌。

```bash
# 本地部署或已经建立 SSH 隧道
xianyu --url http://127.0.0.1:9000 auth set-token

# HTTPS 服务示例：请自行替换为你的地址
xianyu --url https://your-server.example auth set-token
```

运行后在隐藏输入提示中粘贴访问令牌。CLI 会先调用 `/api/v1/auth/verify`，验证成功才保存。不会绕过验证码、创建用户或修改后端认证规则。已有本地秘密管理器可将令牌通过管道交给 `auth set-token --stdin`，不要使用带真实令牌的 `echo` 命令，以免进入 Shell 历史。

凭据保存于当前操作系统用户的 `~/.config/xianyu-ai-reply/credentials.json`，包含服务地址与访问令牌；目录权限为 `700`、文件权限为 `600`（POSIX）。它是本地明文凭据文件，不是密码保险箱；拒绝符号链接及不安全的文件权限，不写入仓库。示例不包含真实地址、用户信息或密钥。

客户端使用已保存地址。也可通过全局 `--url` 或 `XIANYU_BASE_URL` 指定地址，但必须与令牌绑定地址一致，避免把令牌发送给其他服务。远程地址必须使用 HTTPS；只有回环地址允许 HTTP。TLS 校验始终开启，不跟随重定向，不读取环境代理。

```bash
xianyu health
xianyu whoami
xianyu auth clear
```

`auth clear` 仅删除本地文件，不撤销服务端令牌。访问令牌过期后重新登录并设置；不保存刷新令牌、不静默续期。MCP 启动时读取一次凭据，更新令牌后需重启 MCP 进程。请优先使用仅有目标账号权限的普通用户，管理员令牌仍保留后端授予的跨用户权限。

## CLI 命令

成功时标准输出为 JSON，失败时错误 JSON 写到标准错误并返回非零退出码；`--help` 使用普通帮助文本。不会打印原始服务错误响应或令牌。

| 命令 | 功能 |
| --- | --- |
| `health` | 服务健康摘要，不携带令牌 |
| `whoami` | 当前用户身份摘要 |
| `accounts` | 账号 ID、启用状态，不读取账号详情接口 |
| `items` | 商品分页查询，支持 `--account-id`、`--keyword` |
| `orders` | 订单分页查询，支持 `--account-id`、`--status` |
| `keywords list ACCOUNT_ID` | 查询指定账号的关键词及回复 |
| `account-status ACCOUNT_ID enabled\|disabled --confirm` | 启停账号任务 |
| `keywords replace ACCOUNT_ID --file FILE --confirm` | 替换该账号的文本关键词集合 |
| `send ACCOUNT_ID --chat-id CHAT_ID --to-user-id USER_ID --file FILE --confirm` | 发送真实消息 |

`items` / `orders` 支持 `--page`（默认 1）与 `--page-size`（默认 20，最大 100）。账号 ID 使用 `accounts` 输出的 `id`。会话 ID 和收件人 ID 需由部署者从已有业务界面或授权接口取得，本入口不提供全量聊天记录导出。

```bash
xianyu accounts
xianyu items --account-id ACCOUNT_ID --page 1 --page-size 20
xianyu orders --account-id ACCOUNT_ID --status paid
xianyu keywords list ACCOUNT_ID
```

写操作默认拒绝，必须同时设置 `XIANYU_ALLOW_WRITES=1` 和命令的 `--confirm`。请在执行前核对目标与内容：

```bash
XIANYU_ALLOW_WRITES=1 xianyu account-status ACCOUNT_ID disabled --confirm
XIANYU_ALLOW_WRITES=1 xianyu keywords replace ACCOUNT_ID --file /outside/repo/keywords.json --confirm
XIANYU_ALLOW_WRITES=1 xianyu send ACCOUNT_ID --chat-id CHAT_ID --to-user-id USER_ID --file /outside/repo/message.txt --confirm
```

文件路径只是占位符。关键词文件为 JSON 数组，每项仅支持 `keyword`、`reply`、可选 `item_id`，一次 1–100 条：

```json
[
  {"keyword": "发货时间", "reply": "付款后会尽快处理。"},
  {"keyword": "规格", "reply": "请查看商品说明。", "item_id": "ITEM_ID"}
]
```

**`keywords replace` 是替换现有文本关键词集合，不是追加或合并。** 先查询并在仓库外保存需要保留的规则；不支持空数组清空，不修改图片关键词。由于上游替换接口会删除全部非图片规则，客户端检测到外部联系人等特殊规则时会拒绝替换，需回到 Web 后台编辑；编辑期间也请避免多端同时修改规则。消息文件是 UTF-8 正文；`--file -` 表示从标准输入读取。输入文件与查询导出可能包含业务资料，勿放进仓库。

发送遵循后端本人账号限制和每分钟 30 条限流。客户端不自动重试写操作；超时或连接中断时结果可能不确定，应先核对后台状态，避免重复发送。

## 接入 MCP 客户端

完成上面的本地令牌配置后，在支持 stdio MCP 的客户端中填写以下通用配置。把 `command` 换成你本地 `xianyu-mcp` 可执行文件的**绝对路径**；可在激活虚拟环境后用 `command -v xianyu-mcp` 查询。客户端必须以保存凭据的同一个系统用户运行。

```json
{
  "mcpServers": {
    "xianyu": {
      "command": "/absolute/path/to/xianyu-ai-reply/.venv-tools/bin/xianyu-mcp",
      "env": {
        "XIANYU_ALLOW_WRITES": "0"
      }
    }
  }
}
```

将配置放入 MCP 客户端自己的用户级设置，不把含私人路径或域名的实际配置提交到 Git。不同客户端的配置格式可能不同；此处展示通用 `mcpServers` 格式。

默认提供 6 个查询工具：`health`、`whoami`、`list_accounts`、`list_items`、`list_orders`、`list_keywords`。需要写操作时，将进程环境里的 `XIANYU_ALLOW_WRITES` 改为 `1` 并重启，才会额外注册 `set_account_enabled`、`replace_keywords`、`send_message`。每次写工具调用还需传 `confirm: true`。

读写、破坏性与幂等性提示通过 MCP tool annotations 声明。**这些提示和 `confirm` 参数不是独立的人类审批系统**；请在 MCP 客户端设置写工具调用审批，并在用户确认具体对象与内容后执行。只读配置会直接不注册写工具，且共享客户端仍会检查写入开关。

例如可向助手提出：“列出账号状态”“查询某账号最近一页订单”“查看关键词后，整理一份替换方案供我确认”。服务器返回的商品标题、回复文本属于业务数据，不应作为新的系统指令执行。

## 隐私与权限范围

- 不提供 Cookie、密码、Token、数据库、文件系统或任意 URL / 任意 API 调用工具。
- 账号只返回标识和启用状态；订单摘要不包含买家 ID、收货人、电话、地址或发货内容。
- 采用字段白名单，不直接透传后端响应；但商品标题、关键词回复等自由文本仍可能被用户填入私人信息。使用 MCP 意味着所查询的数据会进入所连接的 AI 客户端，请按需要查询。
- `.gitignore` 排除了常见凭据文件、`.mcp.json`、`mcp.local.json` 和 `integrations/local/`；忽略规则不能替代提交前检查，已跟踪文件也不会自动被忽略。
- 本入口没有新增后端权限系统。所有操作沿用登录用户权限，写入开关只约束该客户端；不应将拥有完整权限的令牌视为服务端只读令牌。

## 验证

```bash
uv pip install --python .venv-tools/bin/python -e './integrations[mcp,test]'
.venv-tools/bin/python -m pytest integrations/tests -q
```

测试只使用虚构数据、隔离 HOME、模拟 HTTP 与本地测试服务。覆盖 URL / 路径校验、凭据权限与地址绑定、敏感字段过滤、业务错误处理、写操作双重开关、禁止重定向与自动重试，以及真实 stdio MCP 初始化、工具枚举和工具调用。不需要、也不会读取你的生产令牌或连接真实闲鱼账号。
