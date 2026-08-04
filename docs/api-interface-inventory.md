# 对外 API 接口清单

最后审计：2026-08-04。调用链中的 `JWT` 表示 `current_user_id` 依赖（包含签名、过期和 Redis 吊销校验）；`ADMIN` 表示 `X-Admin-Token`。

## FastAPI 入站 REST

| ID | 方法和路径 | 调用链 | 鉴权和校验 | 中转结论 |
| --- | --- | --- | --- | --- |
| API-001 | `POST /v1/auth/session` | 桌面 `ServerApiClient.login_with_local_license` -> auth 路由 -> Ed25519 本地授权校验 -> PostgreSQL/Redis | 机器码 8-512、令牌 1-8192、固定窗口限流 | 服务端终点；写入登录日志。 |
| API-002 | `DELETE /v1/auth/session` | 桌面 -> auth 路由 -> Redis 吊销 | JWT | 服务端终点。 |
| API-003 | `POST /v1/admin/activation-codes` | 管理工具 -> auth 路由 -> PostgreSQL | ADMIN；激活码长度、设备上限 | 服务端终点。 |
| API-004 | `POST /v1/admin/activation-codes/{id}/revoke` | 管理工具 -> auth 路由 -> PostgreSQL | ADMIN；路径整数 | 服务端终点。 |
| API-005 | `PUT/GET /v1/integrations/wss-credentials` | 桌面自动读取本地 Tencent 会话 -> integrations 路由 -> 加密凭据库 | JWT；appid 数字、各字段长度 | 服务端中转/存储；响应不回传 userSig。 |
| API-006 | `GET /v1/draws/{site}/history` | 桌面 `ServerApiClient` -> draws 路由 -> 共享开奖库 | JWT；site、limit 1-500 | 服务端中转，worker 唯一访问开奖源。 |
| API-007 | `GET /v1/analysis/frequency` | 自动下注面板 -> `ServerApiClient` -> draws 路由 | JWT；history 1-500、阈值 0-100 | 服务端中转。 |
| API-008 | `PUT /v1/admin/draws` | 管理工具 -> draws 路由 -> 开奖库 | ADMIN；Pydantic 字段边界 | 服务端终点。 |
| API-009 | `GET/PUT /v1/strategies/auto-bet` | 自动下注面板 -> `ServerApiClient` -> strategies 路由 | JWT；群组最多 100、金额/阈值范围 | 服务端中转；保存操作写日志。 |
| API-010 | `POST /v1/bets` | 策略调度/桌面 -> bets 路由 -> 订单库 | JWT；站点、期号、群组、玩法、金额边界 | 服务端中转；幂等键和日志。 |
| API-011 | `GET /v1/bets/pending` | 面板轮询 -> bets 路由 | JWT；用户隔离 | 服务端终点。 |
| API-012 | `POST /v1/bets/{id}/confirm|skip|expire` | 面板操作 -> bets 路由 -> sender 队列 | JWT；路径整数、条件状态转换 | 服务端中转；操作写日志。 |
| API-013 | `GET /v1/bets/statistics|events|events/latest` | 面板轮询 -> bets 路由 -> 订单/事件库 | JWT；分页/站点/日期范围 | 服务端终点。 |
| API-014 | `GET /v1/audit-events` | 桌面 -> bets 路由 -> 审计库 | JWT；用户隔离 | 服务端终点。 |
| API-015 | `GET /v1/runtime-logs` | 自动下注面板 -> `ServerApiClient.runtime_logs` -> runtime_logs 路由 | JWT；级别/分类枚举、关键字≤200、时间顺序、游标、limit 1-100 | 服务端终点；时间统一以显式 UTC 传输、桌面按北京时间显示/筛选；返回当前用户事件及 `user_id IS NULL` 的脱敏全局服务事件，不返回其他用户事件。策略日志以保存的群名快照附带 `【群组名】【站点 期号】` 上下文。 |
| API-016 | `GET /health/live` | 负载均衡 -> FastAPI | 无鉴权；固定状态 | 明确运维例外，无业务数据。 |
| API-017 | `GET /health/ready` | 受限反向代理运维网段 -> FastAPI -> PostgreSQL/Redis | 反向代理 IP 限制；不返回依赖详情 | 明确运维例外。 |
| API-018 | `GET /v1/draws/{site}/current` | 桌面线路卡片/开奖时钟 -> `ServerApiClient.current_draw` -> draws 路由 -> 注册开奖源 | JWT；site 固定四站 allowlist；源不可用返回 503 | FastAPI 实时中转；同时返回已开奖的 `current_period` 和唯一允许下注的 `next_period`。桌面无第三方回退，worker 只用 `next_period` 创建和发送订单。 |
| API-019 | `GET /v1/updates/manifest` | 桌面更新检查 -> `ServerApiClient.update_manifest` -> updates 路由 -> 只读发布目录 `latest.json` | JWT；清单必须为对象，包含合法文件名、正整数大小、64 位 SHA-256 和非空签名；桌面继续执行 Ed25519 验签 | 服务端受控分发。 |
| API-020 | `GET /v1/updates/files/{file_name}` | 桌面更新下载 -> `ServerApiClient.download_update_file` -> updates 路由 -> 只读发布目录 | JWT；路径解析防穿越；文件名必须等于当前清单引用文件；桌面按签名大小分块落盘并校验 SHA-256 | 服务端二进制代理，无任意 URL/SSRF 输入。 |

## 服务端出站调用

| ID | 协议/调用链 | 鉴权和校验 | 中转结论 |
| --- | --- | --- | --- |
| OUT-001 | FastAPI/worker -> `history_sources`/`current_period` -> 已注册的 PC28/澳门/澳洲/挪威开奖 HTTPS 源 | 站点来自固定 allowlist；响应解析与超时/重试；worker 写入脱敏耗时与异常日志 | 必须由服务端中转；客户端不得直连。历史由 worker 入库，当前期由 API-018 实时代理。 |
| OUT-002 | worker -> `SharedAiClient` -> 服务器环境配置的 AI HTTPS 源 | AI URL/Key 只来自服务端配置；严格 JSON 响应校验 | 必须由 worker 中转。 |
| OUT-003 | sender worker -> Tencent Cloud Chat REST/WSS | 用户加密 userSig 只在 sender 临时解密；订单授权/状态复核 | 服务端可发送路径；单独审计。 |

## 桌面网络入口与例外

| ID | 入口 | 调用链与结论 |
| --- | --- | --- |
| CLIENT-001 | `app/services/server_api_client.py` | 唯一通用业务 HTTP 客户端；所有非 Tencent 生产网络请求必须经此入口。 |
| EXCEPTION-TENCENT-IM-001 | `app/services/ws_message_sender.py` | 腾讯聊天 WSS 直连例外；使用已登录本地会话，仅用于聊天发送。 |
| EXCEPTION-TENCENT-IM-002 | `app/services/rest_message_sender.py` | 腾讯聊天 REST 直连例外；仅用于聊天发送。 |
| MIGRATED-001 | `app/utils/fetch_date.py`、`app/utils/history_records.py` | 网络获取已禁用，仅保留元数据与纯解析兼容函数；当前期和历史分别由 API-018/API-006 提供，活动 UI 无第三方回退。 |
| MIGRATED-002 | 本地 AI 与更新模块 | `app/services/ai_bet_client.py` 已删除，客户端不提供通用 AI 建议调用；AI 仅由 worker 的 `SharedAiClient` 决策。`update_service.py` 仅保留签名、哈希和服务器下载编排，网络入口为 API-019/API-020。 |

## 诊断工具

`tools/diagnostics/**` 的 HTTP、浏览器、WebSocket 探针均为非生产人工诊断入口，不由桌面用户路径调用。其发现的目标包含开奖源、Tencent IM 和本地 IDA MCP。执行前必须由维护人员确认目标和凭据；工具不得被导入 `app/` 生产模块。

## 审计结果与修复优先级

1. Tencent REST/WSS 已依用户要求登记为唯一客户端直连例外。
2. 历史开奖、当前期开奖、更新检查/下载均已迁移到 JWT FastAPI 路由；本地 AI 网络客户端和本地凭据配置已移除。服务端没有客户端可调用的通用 AI 建议路由，AI 只存在于 worker 内部决策链。
3. 静态审计测试限制生产 `urlopen` 仅可出现在 `ServerApiClient` 和两项 Tencent IM 例外中。
4. `/health/ready` 必须只由反向代理允许的运维网段访问；部署时不可直接公开 API 端口。
