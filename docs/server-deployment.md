# 服务端部署

## 本地开发

在 `backend/` 从 `.env.example` 复制出本机 `.env` 并设置所有占位变量。该文件只能保留在机器本地，不能提交。

```powershell
Set-Location backend
docker compose up --build -d
docker compose ps
Invoke-WebRequest http://127.0.0.1:8080/health/ready
```

Compose 启动 PostgreSQL、Redis、一次性 Alembic 迁移、FastAPI API 和集中 worker。开发 Compose 只把 API 映射到 `127.0.0.1`。

## 生产 Linux

1. 将不含 `.env` 的仓库/发布包复制到服务器，安装 Docker Engine 与 Compose plugin。
2. 在 `backend/.env` 使用 `backend/deploy/server.env.example` 建立生产密钥；生成新的 PostgreSQL、JWT、凭据加密、管理员和 AI key，绝不复用开发值。`LICENSE_PUBLIC_KEY_PEM_B64` 必须是桌面普通用户版离线授权公钥的单行 Base64，私钥绝不能上传服务器。
3. 调整 `docker-compose.yml` 的 API 端口映射：仅在 TLS 反向代理可用时对外暴露。IP 访问必须使用受信任 TLS 证书或客户端固定证书指纹后才允许上传 `user_sig` 和发送下注。
4. 执行 `sh backend/deploy/deploy.sh`，确认 `migrate` 已成功退出，`api` 的 readiness 为 `ok`，`worker` 处于运行状态。
5. 通过管理员 API 创建有限期、默认单设备的测试激活码；在客户端“帮助 -> 服务器模式”登录，上传测试 WSS 凭据，并验证待确认订单确认流程。

## 运维

- 每日导出 PostgreSQL 卷并验证恢复；Redis 是会话撤销和锁缓存，不是事实来源。
- 使用 Docker 日志轮转或集中日志；日志禁止记录激活码、JWT、`user_sig`、AI key 与管理员令牌。
- 监控 `/health/live` 与 `/health/ready`；后者同时检查 PostgreSQL 和 Redis，必须由反向代理限制为运维网段，不能直接公开。
- 执行 Alembic `head` 后会创建 `runtime_log_events`；自动下注面板按默认 5 秒间隔以 JWT 分页读取日志。worker 记录 CPU、内存和服务周期，不记录密钥或 URL 查询参数。
- 轮换 `JWT_SECRET`、`CREDENTIAL_ENCRYPTION_KEY` 和 AI key 时按维护窗口重新登录客户端；凭据加密密钥轮换须先执行数据重加密迁移。
