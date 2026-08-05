# 管理后台与生产部署 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 部署集中服务到生产服务器，提供 TOTP 管理后台并让桌面客户端固定使用生产 API。

**Architecture:** FastAPI 同源提供 Jinja2 管理后台和 `/v1/admin` JSON 接口；管理员 Cookie
会话与现有桌面 JWT 完全分离。PostgreSQL 保存管理员、会话、审计和引导状态，Redis 保存
限流、在线状态和服务心跳；Docker Compose 在生产服务器公开 API 的 8080 端口。

**Tech Stack:** Python 3.12、FastAPI、SQLAlchemy Async、Alembic、Jinja2、PyOTP、Argon2、
Docker Compose、PostgreSQL、Redis、PyInstaller。

---

## 文件结构

- 修改 `backend/server_api/db.py`：管理员、会话、审计、引导与心跳模型。
- 创建 `backend/alembic/versions/20260805_10_admin_console.py`：生产数据库迁移。
- 创建 `backend/server_api/services/admin_auth.py`：密码、TOTP、会话与引导逻辑。
- 创建 `backend/server_api/services/admin_management.py`：用户、激活码、设备、订单与监控查询。
- 创建 `backend/server_api/api/routes/admin.py`：后台页面及管理员 JSON API。
- 创建 `backend/server_api/templates/admin/*.html`、`backend/server_api/static/admin.css`、
  `backend/server_api/static/admin.js`：固定导航和指标条后台界面。
- 修改 `backend/server_api/main.py`：模板/静态资源、管理员路由、请求指标和心跳。
- 修改 `backend/server_api/worker.py`：worker 心跳。
- 修改 `backend/server_api/settings.py`、`backend/requirements.txt`、`backend/.env.example`、
  `backend/deploy/server.env.example`：认证与 Cookie 配置。
- 修改 `backend/server_api/api/routes/auth.py`：移除 Bootstrap Header 对管理 API 的依赖。
- 修改 `backend/server_api/services/auth.py`：激活码延期、用户授权状态和设备撤销服务。
- 修改 `app/build_config.py`、`tools/build.py`：固定生产 API 地址。
- 修改 `backend/docker-compose.yml`、`backend/deploy/deploy.sh`、`docs/server-deployment.md`：
  生产端口、密钥生成与验证步骤。
- 创建 `backend/tests/test_admin_auth.py`、`backend/tests/test_admin_api.py`、
  `backend/tests/test_admin_dashboard.py`、`tests/test_build_config.py`：回归覆盖。

### Task 1: 管理员数据模型和迁移

**Files:**
- Modify: `backend/server_api/db.py`
- Create: `backend/alembic/versions/20260805_10_admin_console.py`
- Test: `backend/tests/test_admin_auth.py`

- [ ] **Step 1: 写入失败测试，验证数据库有管理员、引导状态与可撤销会话。**

```python
async def test_admin_schema_supports_single_use_bootstrap_state(session):
    state = BootstrapState(key="admin_setup", consumed_at=None)
    admin = AdminUser(username="admin", password_hash="hash", totp_secret_encrypted="secret")
    session.add_all([state, admin])
    await session.commit()
    assert admin.id is not None and state.consumed_at is None
```

- [ ] **Step 2: 运行测试，确认因模型缺失失败。**

Run: `Set-Location backend; ..\.venv\Scripts\python.exe -m pytest tests/test_admin_auth.py -q`

- [ ] **Step 3: 添加模型与 Alembic 迁移。**

```python
class AdminUser(Base):
    __tablename__ = "admin_users"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(512))
    totp_secret_encrypted: Mapped[str] = mapped_column(String(512))
    disabled: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
```

迁移创建 `admin_users`、`admin_sessions`、`admin_audit_events`、`bootstrap_state` 和
`service_heartbeats`，为查询字段建立索引。

- [ ] **Step 4: 运行模型测试与迁移升级。**

Run: `Set-Location backend; ..\.venv\Scripts\python.exe -m pytest tests/test_admin_auth.py -q; docker compose run --rm migrate`

### Task 2: 管理员认证、TOTP 与一次性引导

**Files:**
- Create: `backend/server_api/services/admin_auth.py`
- Modify: `backend/server_api/settings.py`, `backend/requirements.txt`, `backend/server_api/main.py`
- Test: `backend/tests/test_admin_auth.py`

- [ ] **Step 1: 写入失败测试，覆盖引导令牌单次消费、密码与 TOTP 双重校验。**

```python
async def test_setup_consumes_bootstrap_token_and_login_requires_totp(service):
    secret = await service.setup_admin("bootstrap", "admin", "Correct-Horse-99")
    assert await service.login("admin", "Correct-Horse-99", "000000") is None
    assert await service.login("admin", "Correct-Horse-99", pyotp.TOTP(secret).now()) is not None
    with pytest.raises(AdminAuthorizationError):
        await service.setup_admin("bootstrap", "other", "Correct-Horse-99")
```

- [ ] **Step 2: 运行测试，确认失败。**

Run: `Set-Location backend; ..\.venv\Scripts\python.exe -m pytest tests/test_admin_auth.py -q`

- [ ] **Step 3: 实现 Argon2id、Fernet 加密的 TOTP 秘钥和随机 Cookie 会话。**

```python
async def require_admin_session(request: Request, session: AsyncSession) -> AdminUser:
    raw = request.cookies.get("startrace_admin")
    record = await find_active_admin_session(session, raw)
    if record is None:
        raise HTTPException(status_code=401, detail="管理员登录已失效")
    return record.admin
```

使用 `secrets.token_urlsafe(48)` 生成会话；数据库仅保存 SHA-256 哈希；会话绝对有效期
24 小时。设置管理端登录限流与 `ADMIN_COOKIE_SECURE` 配置。

- [ ] **Step 4: 运行管理员认证测试。**

Run: `Set-Location backend; ..\.venv\Scripts\python.exe -m pytest tests/test_admin_auth.py -q`

### Task 3: 管理员 API 与后台数据服务

**Files:**
- Create: `backend/server_api/services/admin_management.py`, `backend/server_api/api/routes/admin.py`
- Modify: `backend/server_api/api/routes/auth.py`, `backend/server_api/services/auth.py`, `backend/server_api/main.py`
- Test: `backend/tests/test_admin_api.py`

- [ ] **Step 1: 写入失败 API 测试，验证未认证拒绝、默认激活码、设备撤销和审计。**

```python
def test_admin_creates_default_one_day_two_device_code(client, admin_cookie):
    response = client.post("/v1/admin/activation-codes", cookies=admin_cookie, json={})
    assert response.status_code == 201
    assert response.json()["max_devices"] == 2
    assert response.json()["expires_in_seconds"] == 86400
    assert response.json()["activation_code"]
```

- [ ] **Step 2: 运行测试，确认失败。**

Run: `Set-Location backend; ..\.venv\Scripts\python.exe -m pytest tests/test_admin_api.py -q`

- [ ] **Step 3: 实现受管理员会话保护的 API。**

```text
GET  /v1/admin/dashboard
GET  /v1/admin/users?keyword=&status=&page=
POST /v1/admin/users/{id}/disable
POST /v1/admin/users/{id}/restore
DELETE /v1/admin/users/{id}/devices/{device_id}
POST /v1/admin/activation-codes
POST /v1/admin/activation-codes/{id}/revoke
POST /v1/admin/activation-codes/{id}/extend
GET  /v1/admin/orders
GET  /v1/admin/runtime-logs
GET  /v1/admin/audit-events
GET  /v1/admin/system-health
```

请求创建码的缺省值为 `quantity=1`、`expires_in_days=1`、`max_devices=2`；批量响应仅返回
本次新生成的明文码。每个变更写入 `admin_audit_events`。

- [ ] **Step 4: 运行 API 测试。**

Run: `Set-Location backend; ..\.venv\Scripts\python.exe -m pytest tests/test_admin_api.py -q`

### Task 4: 后台页面、指标和服务心跳

**Files:**
- Create: `backend/server_api/templates/admin/base.html`, `backend/server_api/templates/admin/setup.html`, `backend/server_api/templates/admin/login.html`, `backend/server_api/templates/admin/dashboard.html`, `backend/server_api/templates/admin/users.html`, `backend/server_api/templates/admin/codes.html`, `backend/server_api/templates/admin/operations.html`, `backend/server_api/static/admin.css`, `backend/server_api/static/admin.js`
- Modify: `backend/server_api/main.py`, `backend/server_api/worker.py`
- Test: `backend/tests/test_admin_dashboard.py`

- [ ] **Step 1: 写入失败页面测试，检查指标条和登录保护。**

```python
def test_admin_users_page_requires_session_and_has_fixed_metric_bar(client, admin_cookie):
    assert client.get("/admin/users").status_code in {302, 401}
    response = client.get("/admin/users", cookies=admin_cookie)
    assert response.status_code == 200
    assert 'data-testid="global-metrics"' in response.text
```

- [ ] **Step 2: 运行测试，确认失败。**

Run: `Set-Location backend; ..\.venv\Scripts\python.exe -m pytest tests/test_admin_dashboard.py -q`

- [ ] **Step 3: 实现服务器渲染页面、固定指标条与异步刷新。**

```html
<section id="global-metrics" data-testid="global-metrics">
  <article>在线用户 <strong data-metric="online_users">--</strong></article>
  <article>今日请求 <strong data-metric="api_requests">--</strong></article>
  <article>异常 <strong data-metric="errors">--</strong></article>
  <article>API <strong data-metric="api_status">--</strong></article>
</section>
```

`main.py` 通过中间件记录请求/异常计数，API 每 15 秒上报心跳；worker 每 15 秒上报
`worker` 心跳。后台 JavaScript 通过 `/v1/admin/dashboard` 每 5 秒刷新指标。

- [ ] **Step 4: 运行页面测试。**

Run: `Set-Location backend; ..\.venv\Scripts\python.exe -m pytest tests/test_admin_dashboard.py -q`

### Task 5: 固定桌面生产 API 地址

**Files:**
- Modify: `app/build_config.py`, `tools/build.py`
- Test: `tests/test_build_config.py`

- [ ] **Step 1: 写入失败测试，验证环境变量不能覆盖生产地址。**

```python
def test_server_api_base_url_is_fixed_to_production(monkeypatch):
    monkeypatch.setenv("STARTRACE_SERVER_API_BASE_URL", "http://evil.invalid")
    assert build_config.server_api_base_url() == "http://207.56.2.71:8080"
```

- [ ] **Step 2: 运行测试，确认失败。**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_build_config.py -q`

- [ ] **Step 3: 将源码和打包构建配置限制为生产地址。**

```python
SERVER_API_BASE_URL = "http://207.56.2.71:8080"

def server_api_base_url() -> str:
    return SERVER_API_BASE_URL
```

构建脚本验证 `STARTRACE_SERVER_API_BASE_URL` 若存在必须完全等于该常量，防止错误工件。

- [ ] **Step 4: 运行客户端配置测试。**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_build_config.py tests/test_server_api_client.py -q`

### Task 6: 生产 Compose、部署文档与远程发布

**Files:**
- Modify: `backend/docker-compose.yml`, `backend/deploy/deploy.sh`, `backend/deploy/server.env.example`, `docs/server-deployment.md`, `README.md`
- Test: `backend/tests/test_admin_api.py`, `backend/tests/test_admin_dashboard.py`

- [ ] **Step 1: 写入/更新 Compose 配置验证，确认 API 为 `0.0.0.0:8080` 且数据库未映射端口。**

```python
def test_production_compose_exposes_only_api_port():
    compose = yaml.safe_load(Path("docker-compose.yml").read_text())
    assert "8080:8080" in compose["services"]["api"]["ports"]
    assert "ports" not in compose["services"]["postgres"]
```

- [ ] **Step 2: 生成生产 `.env`，使用随机长密钥与一次性 Bootstrap Token。**

Run: `ssh -p 62594 root@207.56.2.71 'install -d -m 700 /opt/startrace'`

- [ ] **Step 3: 使用 rsync/ssh 上传排除 `.env`、密钥和工件的后端代码，并在远端运行 Compose。**

```powershell
tar --exclude=backend/.env --exclude=.git --exclude=.venv -czf startrace-backend.tgz backend
scp -P 62594 startrace-backend.tgz root@207.56.2.71:/opt/startrace/
ssh -p 62594 root@207.56.2.71 'cd /opt/startrace && tar xzf startrace-backend.tgz --strip-components=1 && cd backend && docker compose up --build -d --wait api worker'
```

- [ ] **Step 4: 在远端验证健康、迁移、管理引导页面和客户端授权 API。**

Run: `Invoke-WebRequest http://207.56.2.71:8080/health/ready`

Expected: HTTP 200 with `{"status":"ok"}`; `/admin/setup` 可访问，首次引导完成后只允许
`/admin/login`。

### Task 7: 全量回归与交付检查

**Files:**
- Test: `backend/tests`, `tests`

- [ ] **Step 1: 运行后端全部测试。**

Run: `Set-Location backend; ..\.venv\Scripts\python.exe -m pytest tests -q`

- [ ] **Step 2: 运行桌面相关测试与编译检查。**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_build_config.py tests\test_server_api_client.py tests\test_auto_bet_panel_help.py tests\test_runtime_stability.py -q; .\.venv\Scripts\python.exe -m compileall -q app backend\server_api`

- [ ] **Step 3: 检查差异与生产容器日志。**

Run: `git diff --check; ssh -p 62594 root@207.56.2.71 'cd /opt/startrace/backend && docker compose ps && docker compose logs --tail=100 api worker'`

## 计划自检

- 覆盖：管理员引导/TOTP、固定指标条、全部确认的管理范围、客户端固定地址、生产部署与
  健康验证均有对应任务。
- 一致性：管理员 API 一律使用 Cookie 会话；桌面一律使用现有用户 JWT；默认激活码参数
  在设计、API 和测试中均为 1 天、2 设备、1 个。
- 范围：不引入独立 SPA，也不提前实施 HTTPS，保持后续反向代理迁移的配置入口。
