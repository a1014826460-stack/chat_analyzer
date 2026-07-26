# 服务端 API 集中调度实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在本地 Docker 环境实现可扩展 FastAPI 后端首版：机器码授权、单设备会话、用户隔离的 WSS 凭据、开奖读取、确认订单和审计基础。

**Architecture:** `backend/` 独立于桌面客户端，FastAPI API 与 worker 共用领域/数据库模块；PostgreSQL 为事实库，Redis 提供锁、限流和队列。先完成安全的基础 API 和可测试的任务状态机，再迁移爬虫、AI、WSS sender 与客户端。

**Tech Stack:** FastAPI、SQLAlchemy 2 async、asyncpg、Redis、Pydantic、cryptography、PyJWT、Docker Compose、pytest。

---

### Task 1: 后端工程与本地容器骨架

**Files:**
- Create: backend/pyproject.toml
- Create: backend/Dockerfile
- Create: backend/docker-compose.yml
- Create: backend/.env.example
- Create: backend/app/main.py
- Create: backend/app/settings.py
- Create: backend/tests/test_health.py

- [ ] **Step 1: 写失败测试。** 断言 GET /health/live 返回 200 和 `{status: "ok"}`。
- [ ] **Step 2: 验证 RED。** pytest backend/tests/test_health.py -q，预期因模块不存在失败。
- [ ] **Step 3: 最小实现。** 创建 FastAPI app 与 liveness endpoint；定义环境设置模型和开发默认值；Compose 定义 API、worker、PostgreSQL、Redis 健康检查与仅本机端口映射。
- [ ] **Step 4: 验证 GREEN。** 运行定向测试；运行 docker compose config 验证 Compose 语法。

### Task 2: 授权、单设备会话与 JWT

**Files:**
- Create: backend/app/db/models.py
- Create: backend/app/db/session.py
- Create: backend/app/services/auth.py
- Create: backend/app/api/routes/auth.py
- Create: backend/tests/test_auth.py

- [ ] **Step 1: 写失败测试。** 覆盖激活、会话 JWT、过期授权、吊销授权、默认上限一台设备、登出释放会话。
- [ ] **Step 2: 验证 RED。** 运行 pytest backend/tests/test_auth.py -q。
- [ ] **Step 3: 最小实现。** `activation_codes`、`users`、`device_sessions`、JWT 依赖；机器码/激活码只保存 SHA-256；用事务确保设备限制。
- [ ] **Step 4: 验证 GREEN。** 运行该测试，随后使用并发测试验证两个不同机器码只能有一个成功会话。

### Task 3: 用户隔离与 WSS 凭据加密

**Files:**
- Create: backend/app/services/credentials.py
- Create: backend/app/api/routes/integrations.py
- Create: backend/tests/test_credentials.py

- [ ] **Step 1: 写失败测试。** 写入 credentials 后 GET 只返回脱敏 accid；另一用户不可读取或覆盖；数据库值不是明文 user_sig。
- [ ] **Step 2: 验证 RED。** pytest backend/tests/test_credentials.py -q。
- [ ] **Step 3: 最小实现。** AES-GCM 加密、用户绑定 AAD、版本号、JWT 用户过滤；加密主密钥仅从环境变量加载。
- [ ] **Step 4: 验证 GREEN。** 运行测试并在日志扫描中断言无 secret。

### Task 4: 共享开奖与频率 API

**Files:**
- Create: backend/app/services/draws.py
- Create: backend/app/api/routes/draws.py
- Create: backend/app/api/routes/analysis.py
- Create: backend/tests/test_draws_and_analysis.py

- [ ] **Step 1: 写失败测试。** 验证 `(site, period)` 幂等 upsert、站点历史读取、13/14 与八玩法概率返回。
- [ ] **Step 2: 验证 RED。** pytest backend/tests/test_draws_and_analysis.py -q。
- [ ] **Step 3: 最小实现。** 共享 `draw_results` 表、读取 API，复用/迁移桌面频率分析纯逻辑到 backend。
- [ ] **Step 4: 验证 GREEN。** 运行测试；worker crawler adapter 在此后接入。

### Task 5: 策略订单、确认状态机与审计

**Files:**
- Create: backend/app/services/bets.py
- Create: backend/app/api/routes/bets.py
- Create: backend/app/services/audit.py
- Create: backend/tests/test_bets.py

- [ ] **Step 1: 写失败测试。** 同一 user/site/period/group/play 重复创建只保留一个订单；仅所属用户可确认；确认一次后不可重复；过期不可确认；每次状态变化写审计。
- [ ] **Step 2: 验证 RED。** pytest backend/tests/test_bets.py -q。
- [ ] **Step 3: 最小实现。** `bet_orders` 和 `audit_events` 唯一约束/条件状态更新；pending、confirmed、skipped、expired、sending、sent、failed 状态机与 API。
- [ ] **Step 4: 验证 GREEN。** 并发 confirm 测试只有一个请求成功。

### Task 6: Worker、AI、WSS sender 和客户端迁移

**Files:**
- Create: backend/app/workers/*
- Modify: app/services/history_fetchers.py
- Modify: app/services/ai_bet_client.py
- Modify: app/services/ws_message_sender.py
- Create: app/services/server_api_client.py
- Create: backend/tests/test_worker_idempotency.py

- [ ] **Step 1: 先写 worker 幂等、授权复检、确认超时和凭据解密边界的失败测试。
- [ ] **Step 2: 实现站点 crawler、共享 AI client、用户 sender 和 Redis 锁/队列；发送前重新校验授权、订单状态、封盘窗口、凭据。
- [ ] **Step 3: 客户端增加 server-mode API client、登录和待确认订单 UI；server mode 禁用本地外部调用与 sender。
- [ ] **Step 4: 在 Compose 下运行集成测试和端到端测试。

### Task 7: 生产部署

**Files:**
- Create: backend/deploy/server.env.example
- Create: backend/deploy/deploy.sh
- Create: docs/server-deployment.md

- [ ] **Step 1: 完成镜像构建、迁移、liveness/readiness、备份和日志轮转脚本。
- [ ] **Step 2: 本地 docker compose up 后运行 API、并发、worker、密钥不泄漏检查。
- [ ] **Step 3: 使用 SSH 将无密钥部署包上传 Linux；服务器生成生产 `.env`，不上传密码或密钥。
- [ ] **Step 4: 在服务器运行迁移和健康检查；创建测试授权并完成单用户确认下注端到端验证。

### Task 8: 严格普通版在线会话与自动凭据同步

**Files:**
- Modify: `app/main.py`
- Modify: `app/services/license_service.py`
- Modify: `app/services/server_api_client.py`
- Modify: `app/ui/server_mode_dialog.py`
- Modify: `app/ui/main_window.py`
- Modify: `app/ui/auto_bet_panel.py`
- Modify: `backend/server_api/services/auth.py`
- Modify: `backend/server_api/api/routes/auth.py`
- Modify: `backend/server_api/db.py`
- Create: `backend/alembic/versions/20260726_07_online_license_records.py`
- Test: `tests/test_server_mode_dialog.py`
- Test: `tests/test_license_signing.py`
- Test: `backend/tests/test_auth.py`

- [ ] **Step 1: 写失败测试。** 普通用户仅以已签名本地授权令牌和匹配机器码取得会话；篡改、过期、错误 edition 或服务器吊销均失败；`--admin` 不改变用户版构建身份；WSS 从本机 shared preferences 自动同步且 UI 不含手填字段。
- [ ] **Step 2: 验证 RED。** 分别运行根目录与 backend 定向测试，确认新接口/行为尚不存在。
- [ ] **Step 3: 最小实现。** 服务端验证 Ed25519 本地授权证明并写入可吊销的授权记录；客户端自动读取本地授权令牌和现有 WSS 登录资料，JWT 只留内存；普通用户 UI 仅显示同步状态；删除运行时 `--admin` 升权和客户端 AI/WSS/服务器地址输入。
- [ ] **Step 4: 验证 GREEN。** 运行定向与全量服务端/客户端相关测试、Compose 迁移和 PostgreSQL/Redis 集成测试。
