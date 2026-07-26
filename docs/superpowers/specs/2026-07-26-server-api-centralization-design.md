# 服务端 API 集中调度设计

## 目标

将站点当前期与历史开奖抓取、开奖数据库、AI 调用、在线授权校验和服务器直接下注统一迁移到 Linux 服务器上的 FastAPI 后端。普通客户端只负责已签名本地授权证明、策略配置、展示、每期确认以及读取状态；它不配置 AI、WSS、服务器地址或服务端激活码。

## 架构

服务端采用模块化单体：FastAPI API、异步 worker、PostgreSQL、Redis。开发与生产均通过 Docker Compose 运行相同服务；生产使用服务器 IP 访问，默认 API 端口仅由反向代理暴露。

- `api`：无状态 HTTP API，认证、用户资源、管理员资源和读取接口。
- `worker`：集中执行站点爬虫、AI 请求、策略调度、确认超时和 WSS 下注发送。
- `postgres`：授权、会话、凭据密文、策略、开奖、订单、发送结果和审计事件。
- `redis`：会话撤销、速率限制、分布式锁、任务队列和幂等键。

首版是一个部署单元，模块边界固定为 `auth`、`licensing`、`credentials`、`draws`、`analysis`、`ai`、`bets`、`audit`、`workers`。后续负载增长时可将 crawler、AI、sender worker 独立横向扩展。

## 身份、授权与设备

- 用户身份以机器码和本地签名授权令牌为准；机器码不直接等同数据库主键，服务器保存其 SHA-256 摘要。
- 普通用户版必须先完成既有离线激活。在线登录向 `POST /v1/auth/session` 提交机器码及本地签名授权令牌；服务端以授权公钥验证 Ed25519 签名、`edition=user`、schema、机器码和到期时间，再检查在线吊销、设备上限（默认 1）。客户端不再输入或保存第二份服务端激活码。
- 线上授权记录以本地令牌 `license_id` 的 SHA-256 摘要关联；管理员可吊销该授权。首次成功在线登录以令牌元数据创建记录，之后同一令牌只能在其设备上续期会话。
- 管理员身份只来自独立管理员构建产物的构建时标识，不接受 `--admin` 或环境变量将普通用户版升权。管理员构建只用于本地授权管理；服务端管理 API 仍要求独立管理员令牌。
- JWT 含 `sub=user_id`、`device_id`、`session_id`、过期时间和角色；Redis 与数据库同时检查撤销状态。
- 管理员可生成、吊销、修改设备上限及查询授权/设备/审计。普通用户所有数据查询均由 JWT 的 `user_id` 强制过滤。

## 用户凭据

- 客户端从本机已登录 Tencent Cloud Chat 的 `shared_preferences.json` 自动读取 `appid`、`accid`、`token/userSig`，并在成功在线登录后调用 `PUT /v1/integrations/wss-credentials` 同步。普通用户界面不显示、编辑或持久化这些字段。
- `user_sig` 使用服务端主加密密钥通过 AES-GCM 加密存储；关联数据加密上下文为 `user_id` 与凭据版本，防止密文跨用户复制使用。
- API 响应永不回传 `user_sig`，只返回脱敏账号、版本和更新时间。只有 sender worker 在发送时临时解密。
- 所有共享 AI 提供商 URL、模型与 API key 仅由服务器环境变量配置，客户端不再保存、校验、显示或传递 AI key。

## 外部服务集中调度

- 站点 crawler 以站点为粒度集中拉取当前期和历史开奖，写入共享 `draw_results`；同一站点不会按用户重复抓取。
- 历史结果保留站点、期号、规范化玩法、原始和值、开奖时间和抓取时间。`(site, period)` 唯一，更新遵循较新抓取时间。
- 概率分析读取共享开奖表，但策略结果及下注只属于对应用户。
- AI worker 使用共享密钥调用模型；每用户限流、排队，保存请求、输出、置信度、失败状态和耗时审计。

## 自动下注与确认

- 用户配置策略后，worker 在每期针对每个启用策略创建候选订单。
- 唯一键 `user_id, site, period, group_id, play_type` 和 Redis 分布式锁共同保证并发下的幂等性。
- 需要确认时订单状态为 `pending_confirmation`，客户端用 `GET /v1/bets/pending` 获取，并调用 `POST /v1/bets/{id}/confirm` 或 `/skip`。
- confirm 只将订单排入 sender 队列；worker 在发送前再次检查用户授权、策略启用、订单状态、封盘窗口与 WSS 凭据有效性。
- 不需要确认时直接排入队列。sender 使用用户凭据发送，写入 `bet_attempts`；网络重试复用订单幂等键，成功后不可重复发送。
- 订单过期、授权吊销、会话/策略禁用或缺少凭据均转为不可发送状态并写审计事件。

## API 契约

- `POST /v1/auth/session`：机器码、本地签名授权令牌，返回 access token、过期时间和当前用户摘要。
- `DELETE /v1/auth/session`：注销当前 JWT 会话。
- `PUT /v1/integrations/wss-credentials` / `GET /v1/integrations/wss-credentials`：写入或读取脱敏凭据状态。
- `GET /v1/draws/{site}`、`GET /v1/draws/{site}/history`：共享开奖数据。
- `GET /v1/analysis/frequency`：按站点/期数读取服务器频率分析。
- `GET/PUT /v1/strategies/auto-bet`：读取或修改当前用户策略。
- `GET /v1/bets/pending`、`POST /v1/bets/{id}/confirm`、`POST /v1/bets/{id}/skip`：确认流程。
- `GET /v1/audit-events`：当前用户审计；`/v1/admin/*`：仅管理员跨用户管理接口。

## 并发、隔离与可观测性

- API 不保存进程内用户状态，可多副本运行；Redis 限制每设备认证、每用户 AI 请求、每用户下注确认及每 IP 公共接口请求。
- PostgreSQL 使用事务、外键、唯一约束和行级状态更新；更新订单时使用条件更新避免确认/超时/发送竞态。
- 每个请求附带 request ID；审计记录 actor、user、设备、资源、动作、结果、IP、时间和关联订单。
- 健康检查区分 liveness 与 readiness；readiness 同时检查 PostgreSQL 与 Redis。

## 部署与密钥

- 本地以 Docker Compose 启动 `api`、`worker`、`postgres`、`redis`，依赖由后端独立 requirements 锁定。
- 生产服务器使用同一 Compose 文件和仅服务器持有的 `.env`。部署前通过环境变量提供 `DATABASE_URL`、`REDIS_URL`、`JWT_SECRET`、`CREDENTIAL_ENCRYPTION_KEY`、`ADMIN_BOOTSTRAP_TOKEN`、共享 AI 配置。
- 不在仓库、镜像、日志、API 响应或客户端配置中保存 SSH 密码、WSS user_sig、AI key、JWT 密钥或加密主密钥。
- 没有域名时，先将 API 绑定到服务器 IP 的受控端口；生产客户端必须使用 TLS。首版使用 Caddy/Nginx 的 IP 证书策略或客户端固定证书指纹，未启用 TLS 时禁止生产写凭据和下单。

## 测试与迁移

- 单元测试覆盖授权过期/吊销/设备上限、JWT 会话、用户隔离、凭据加解密、订单确认状态机和唯一幂等键。
- 集成测试用临时 PostgreSQL/Redis 或 Compose 服务验证并发确认与重复请求；接口契约测试确保客户端迁移稳定。
- 客户端只在本地授权有效后自动建立服务器会话；服务端模式启用后停止本地爬虫、AI 与直接 sender，仅保留本地展示缓存。普通用户界面只显示服务器连接、授权与 WSS 自动同步的脱敏状态。
- 本地 API/worker/容器/并发测试通过后再部署至 Linux，执行迁移、健康检查、管理员授权测试和单个测试用户的端到端发送验证。
