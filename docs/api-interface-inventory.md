# 对外 API 接口清单

最后审计：2026-07-31。调用链中的 `JWT` 表示 `current_user_id` 依赖（包含签名、过期和 Redis 吊销校验）；`ADMIN` 表示 `X-Admin-Token`。

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
| API-015 | `GET /v1/runtime-logs` | 自动下注面板 -> `ServerApiClient.runtime_logs` -> runtime_logs 路由 | JWT；级别/分类枚举、关键字≤200、时间顺序、游标、limit 1-100 | 服务端终点；返回当前用户的脱敏日志。 |
| API-016 | `GET /health/live` | 负载均衡 -> FastAPI | 无鉴权；固定状态 | 明确运维例外，无业务数据。 |
| API-017 | `GET /health/ready` | 受限反向代理运维网段 -> FastAPI -> PostgreSQL/Redis | 反向代理 IP 限制；不返回依赖详情 | 明确运维例外。 |

## 服务端出站调用

| ID | 协议/调用链 | 鉴权和校验 | 中转结论 |
| --- | --- | --- | --- |
| OUT-001 | worker -> `history_sources`/`current_period` -> 已注册的 PC28/澳门/澳洲/挪威开奖 HTTPS 源 | 站点来自固定 allowlist；响应解析与超时/重试 | 必须由 worker 中转；客户端不得直连。 |
| OUT-002 | worker -> `SharedAiClient` -> 服务器环境配置的 AI HTTPS 源 | AI URL/Key 只来自服务端配置；严格 JSON 响应校验 | 必须由 worker 中转。 |
| OUT-003 | sender worker -> Tencent Cloud Chat REST/WSS | 用户加密 userSig 只在 sender 临时解密；订单授权/状态复核 | 服务端可发送路径；单独审计。 |

## 桌面网络入口与例外

| ID | 入口 | 调用链与结论 |
| --- | --- | --- |
| CLIENT-001 | `app/services/server_api_client.py` | 唯一通用业务 HTTP 客户端；所有非 Tencent 生产网络请求必须经此入口。 |
| EXCEPTION-TENCENT-IM-001 | `app/services/ws_message_sender.py` | 腾讯聊天 WSS 直连例外；使用已登录本地会话，仅用于聊天发送。 |
| EXCEPTION-TENCENT-IM-002 | `app/services/rest_message_sender.py` | 腾讯聊天 REST 直连例外；仅用于聊天发送。 |
| LEGACY-001 | `app/utils/fetch_date.py`、`app/utils/history_records.py` | 发现客户端直连开奖源；仅兼容/诊断路径，生产服务器模式必须禁用并迁移至 API-006/API-007。 |
| LEGACY-002 | `app/services/ai_bet_client.py`、`app/services/update_service.py` | 发现客户端直连 AI/更新源；生产服务器模式必须禁用，后续改由受签名服务端资源提供。 |

## 诊断工具

`tools/diagnostics/**` 的 HTTP、浏览器、WebSocket 探针均为非生产人工诊断入口，不由桌面用户路径调用。其发现的目标包含开奖源、Tencent IM 和本地 IDA MCP。执行前必须由维护人员确认目标和凭据；工具不得被导入 `app/` 生产模块。

## 审计结果与修复优先级

1. Tencent REST/WSS 已依用户要求登记为唯一客户端直连例外。
2. `LEGACY-001` 与 `LEGACY-002` 是未完成的迁移项：当前仓库仍含直连实现。必须在生产构建中阻止这些路径并将更新、开奖及 AI 的读取契约补全到 FastAPI 后，才能达到“所有非 Tencent 调用均中转”的最终验收。
3. `/health/ready` 必须只由反向代理允许的运维网段访问；部署时不可直接公开 API 端口。
