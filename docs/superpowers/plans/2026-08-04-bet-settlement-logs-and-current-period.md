# 下注结算日志与多线路当前期修复 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 补齐逐笔下注与每期收益日志，修复三条非 PC28 当前期适配，并部署验证后端运行版本。

**Architecture:** sender 继续负责逐笔发送结果；新增独立结算服务，以 `StrategyEvent.settled` 幂等标记在开奖写入后产生用户级汇总日志。当前期适配器按各站真实响应字段解析，运行日志查询合并当前用户和脱敏全局事件。

**Tech Stack:** Python 3.12、FastAPI、SQLAlchemy async、PostgreSQL、PySide6、pytest、Docker Compose

---

### Task 1: 修复澳门、澳洲、挪威当前期适配

**Files:**
- Modify: `backend/server_api/workers/current_period.py`
- Modify: `backend/tests/test_current_period.py`
- Modify: `backend/server_api/api/routes/draws.py`
- Modify: `backend/tests/test_draws_and_analysis.py`

- [x] 添加澳门 `opentime`、澳洲 `next.sec`、挪威 `next_periods` 的失败测试。
- [x] 运行 `python -m pytest backend/tests/test_current_period.py -q`，确认新测试因截止时间为空或期号为空而失败。
- [x] 增加字符串时间解析和各站新字段回退，保持 PC28 行为不变。
- [x] 添加未知站点 `/v1/draws/{site}/current` 返回 422 的测试和固定 allowlist 校验。
- [x] 运行当前期与 draws 路由测试，确认通过。

### Task 2: 增加幂等的每期结算日志

**Files:**
- Create: `backend/server_api/services/bet_settlements.py`
- Modify: `backend/server_api/worker.py`
- Modify: `backend/server_api/services/bet_statistics.py`
- Create: `backend/tests/test_bet_settlements.py`

- [x] 写失败测试：同一用户同一期多个 `sent` 订单只生成一条包含 result、total、staked、payout、profit、outcome 的日志。
- [x] 写失败测试：重复执行结算不新增第二条 `settled` 事件或运行日志。
- [x] 写失败测试：`failed`、`expired`、`confirmed` 订单不计入结算。
- [x] 实现 `settle_new_draws(session)`，按用户、站点、期号聚合，复用统一赔率与命中判定。
- [x] 在每轮所有站点 crawl 完成后、发送处理前调用结算服务。
- [x] 运行结算、统计和 worker 测试，确认通过。

### Task 3: 补齐全局服务日志查询和分类筛选

**Files:**
- Modify: `backend/server_api/services/runtime_logs.py`
- Modify: `backend/tests/test_runtime_logs.py`
- Modify: `app/ui/auto_bet_panel.py`
- Modify: `app/ui/main_window_data.py`
- Modify: `tests/test_auto_bet_panel_help.py`
- Modify: `tests/test_runtime_stability.py`

- [x] 写失败测试：用户能读取自己的事件和 `user_id IS NULL` 全局事件，但不能读取其他用户事件。
- [x] 修改查询条件为当前用户事件与全局事件的并集。
- [x] 写失败 UI 测试：分类下拉框默认 `strategy`，筛选请求包含 `category`。
- [x] 增加“下注与结算/全部/用户操作/系统/第三方/异常”分类选项，并沿用现有刷新、搜索和分页路径。
- [x] 运行 runtime log 服务、客户端和面板测试。

### Task 4: 记录第三方调用和异常

**Files:**
- Modify: `backend/server_api/worker.py`
- Modify: `backend/tests/test_worker_crawler.py`

- [x] 写失败测试：成功站点周期写入带耗时和站点信息的 `DEBUG/third_party` 全局事件。
- [x] 写失败测试：抓取异常写入 `ERROR/exception`，包含脱敏 traceback，且不会阻断其他站点。
- [x] 在 worker 站点边界计时并写结构化事件，不记录 URL 查询参数或凭据。
- [x] 运行 worker、runtime log 和脱敏测试。

### Task 5: 文档、完整回归和运行部署

**Files:**
- Modify: `docs/api-interface-inventory.md`
- Modify: `docs/ui_and_flow.md`
- Modify: `README.md`

- [x] 更新 API 清单中的当前期实时代理、全局日志可见性、四站字段适配和已知例外。
- [x] 运行客户端与后端定向测试、`compileall` 和 `git diff --check`。
- [x] 执行 `docker compose -f backend/docker-compose.yml up -d --build api worker`。
- [x] 检查 `/health/live`、`/health/ready` 和容器状态。
- [x] 在容器内探测四站当前期，确认四站期号与截止时间均非空。
- [x] 查询数据库确认新 worker 已写入 `strategy`、`third_party` 或 `exception` 分类，不再只有 `system/user_action`。
