# 纯算法下注实施计划（暂时停用 AI 干涉）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 通过 `AI_DECISION_ENABLED` 开关（默认关闭）让服务端自动下注策略完全由频率算法决策，不再调用 DeepSeek AI；四站点开奖数据持续自动落库备份（现状已满足）。

**Architecture:** 在 `strategy_scheduler.schedule_frequency_orders` 中，`ai_client is None` 分支由"跳过本期"改为"算法直接下注"，复用 `ai_execute` 事件类型以兼容旧 exe。`worker._run_cycle` 仅当开关开启时才构造 `ai_client`（保留现有 `saved_ai`/`SharedAiClient` 构造代码）。改动基准是服务器源码 `/opt/startrace/backend`，本地 TDD 验证后同步部署。

**Tech Stack:** Python 3.12 / FastAPI / SQLAlchemy 2.0 async / pytest / docker compose。

## Global Constraints

- 改动基准：服务器源码 `/opt/startrace/backend`（非 git 仓库，生产实际运行代码）。
- `AI_DECISION_ENABLED` 默认 `false`（纯算法模式）；置 `true` 即恢复 AI 流程。
- 纯算法判定：`analyze()` 返回 `should_bet=True`（三门最高概率 ≥ 阈值）即直接下注。
- 算法下注复用 `ai_execute` 事件类型，消息含"算法决策下注"字样；纯算法模式不再产生 `ai_error`/`ai_skip`。
- `_DECISION_EVENT_TYPES = {"frequency_skip", "ai_error", "ai_skip", "ai_execute"}` 保持不变。
- 不修改客户端 exe；不修改开奖数据抓取逻辑。
- 服务器容器可跑 pytest（已装 pytest 8.4.2 / aiosqlite 0.22.1 / sqlalchemy 2.0.51）。
- 本地测试在 `backend/` 目录下运行：`.venv/Scripts/python.exe -m pytest tests/... -q`（pyproject `pythonpath=["."]`）。

---

### Task 1: 更新策略调度器测试（TDD 红）

**Files:**
- Modify: `backend/tests/test_strategy_scheduler.py`

**Interfaces:**
- Consumes: 现有 `schedule_frequency_orders(session, *, site, period, betting_deadline_at=None, ai_client=None)` 签名。
- Produces: 更新后的测试，断言新行为——不传 `ai_client` 时频率达标直接算法下注（事件 `ai_execute`、创建 3 个 `BetOrder`）；频率未达标 `frequency_skip`。

- [ ] **Step 1: 修改测试文件**

将 `test_frequency_scheduler_records_ai_error_without_server_ai_configuration`（当前断言 AI 未配置→`ai_error`）**替换**为：

```python
def test_frequency_scheduler_places_algorithm_orders_without_ai():
    from server_api.workers.strategy_scheduler import schedule_frequency_orders

    async def scenario() -> None:
        engine = create_engine("sqlite+aiosqlite:///:memory:")
        await create_schema(engine)
        factory = create_session_factory(engine)
        async with factory() as session:
            session.add(AutoBetStrategy(
                user_id=10, enabled=True, site="pc28", target_groups_json='["group-a"]',
                history_count=4, confidence_threshold=50, require_confirmation=False, bet_amount=3,
            ))
            session.add_all([
                DrawResult(site="pc28", period="1", result="小单", total=13),
                DrawResult(site="pc28", period="2", result="大双", total=14),
                DrawResult(site="pc28", period="3", result="大双", total=14),
                DrawResult(site="pc28", period="4", result="大单", total=15),
            ])
            await session.commit()

            # 不传 ai_client：纯算法模式，频率达标直接下注
            assert await schedule_frequency_orders(session, site="pc28", period="next-4") == 3
            rows = (await session.scalars(select(BetOrder))).all()
            assert {row.play_type for row in rows} == {"小单", "大双", "大单"}
            event = await session.scalar(select(StrategyEvent))
            assert event.event_type == "ai_execute"
            assert "算法决策下注" in event.message
        await engine.dispose()

    asyncio.run(scenario())
```

在文件末尾**追加**：

```python
def test_frequency_scheduler_algorithm_mode_skips_below_threshold_without_ai():
    from server_api.workers.strategy_scheduler import schedule_frequency_orders

    async def scenario() -> None:
        engine = create_engine("sqlite+aiosqlite:///:memory:")
        await create_schema(engine)
        factory = create_session_factory(engine)
        async with factory() as session:
            session.add(AutoBetStrategy(
                user_id=12, enabled=True, site="pc28", target_groups_json='["group-a"]',
                history_count=4, confidence_threshold=80, require_confirmation=False, bet_amount=3,
            ))
            session.add_all([
                DrawResult(site="pc28", period="1", result="小单", total=13),
                DrawResult(site="pc28", period="2", result="大双", total=14),
                DrawResult(site="pc28", period="3", result="小双", total=12),
                DrawResult(site="pc28", period="4", result="大单", total=15),
            ])
            await session.commit()

            assert await schedule_frequency_orders(session, site="pc28", period="next-5") == 0
            assert (await session.scalars(select(BetOrder))).all() == []
            event = await session.scalar(select(StrategyEvent))
            assert event.event_type == "frequency_skip"
        await engine.dispose()

    asyncio.run(scenario())
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_strategy_scheduler.py::test_frequency_scheduler_places_algorithm_orders_without_ai -v`
Expected: FAIL（旧代码在 `ai_client is None` 分支记 `ai_error` 并跳过，`created == 0` 而非 3）。

---

### Task 2: 实现算法下注（TDD 绿）

**Files:**
- Modify: `backend/server_api/workers/strategy_scheduler.py`（`schedule_frequency_orders` 的 102-153 行区域）

**Interfaces:**
- Consumes: `ai_client` 参数（`None` 或 `SharedAiClient`）；`analysis` 字典（`selected_plays`/`highest_selected_probability`）。
- Produces: `ai_client is None` 时直接创建 `BetOrder` 并写 `ai_execute` 事件；`ai_client` 非 None 时保留原 AI 流程。

- [ ] **Step 3: 修改 `schedule_frequency_orders`**

将函数中 `plays = list(analysis["selected_plays"])` 到 `ai_execute` 事件结束（原 102-153 行）**整体替换**为：

```python
        plays = list(analysis["selected_plays"])
        if ai_client is not None:
            try:
                decision = ai_client.recommend_three_doors(
                    site=site,
                    history=[{"period": row.period, "result": row.result, "total": row.total}
                             for row in await history(session, site, strategy.history_count)],
                    selected_plays=plays,
                )
            except Exception as exc:
                await _add_decision_event_once(
                    session,
                    user_id=strategy.user_id,
                    site=site,
                    period=period,
                    event_type="ai_error",
                    message=f"频率通过：三门 {','.join(plays)}；AI 请求失败，跳过本期：{exc}",
                    group_names=group_names,
                )
                continue
            confidence = int(decision["confidence"])
            reason = str(decision["reason"])
            if decision["action"] != "execute" or confidence < strategy.confidence_threshold:
                await _add_decision_event_once(
                    session,
                    user_id=strategy.user_id,
                    site=site,
                    period=period,
                    event_type="ai_skip",
                    message=(f"频率通过：三门 {','.join(plays)}；AI 跳过（置信度 {confidence}/100）：{reason}"),
                    group_names=group_names,
                )
                continue
            await _add_decision_event_once(
                session,
                user_id=strategy.user_id,
                site=site,
                period=period,
                event_type="ai_execute",
                message=f"频率通过：三门 {','.join(plays)}；AI 执行（置信度 {confidence}/100）：{reason}",
                group_names=group_names,
            )
        else:
            # 纯算法模式：频率达标即下注，不依赖 AI。
            await _add_decision_event_once(
                session,
                user_id=strategy.user_id,
                site=site,
                period=period,
                event_type="ai_execute",
                message=(
                    f"频率达标：三门 {','.join(plays)}；算法决策下注"
                    f"（最高 {analysis['highest_selected_probability']:.1f}%，达到阈值 {strategy.confidence_threshold}%）"
                ),
                group_names=group_names,
            )
```

（其后的 `for group_id in json.loads(strategy.target_groups_json):` BetOrder 创建逻辑保持不变。）

- [ ] **Step 4: 运行测试确认通过**

Run: `cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_strategy_scheduler.py -q`
Expected: PASS（6 passed）。

- [ ] **Step 5: 确认 AI 流程测试仍通过**

Run: `cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_strategy_scheduler.py::test_frequency_scheduler_creates_three_door_orders_for_each_target_group tests/test_strategy_scheduler.py::test_frequency_scheduler_is_idempotent_for_an_existing_period -q`
Expected: PASS（2 passed，AI 分支未受影响）。

- [ ] **Step 6: 提交**

```bash
git add backend/server_api/workers/strategy_scheduler.py backend/tests/test_strategy_scheduler.py
git commit -m "feat: 纯算法下注——频率达标直接下注，AI 未配置不再跳过本期"
```

---

### Task 3: 服务器应用全部改动

**Files:**
- Modify（服务器）: `/opt/startrace/backend/server_api/workers/strategy_scheduler.py`
- Modify（服务器）: `/opt/startrace/backend/server_api/settings.py`
- Modify（服务器）: `/opt/startrace/backend/server_api/worker.py`
- Modify（服务器）: `/opt/startrace/backend/.env`

**Interfaces:**
- Produces: 服务器代码支持 `AI_DECISION_ENABLED`；`ai_client` 仅在开关开启时构造。

- [ ] **Step 7: 同步 `strategy_scheduler.py` 到服务器**

Run: `scp -P 62594 backend/server_api/workers/strategy_scheduler.py root@207.56.2.71:/opt/startrace/backend/server_api/workers/strategy_scheduler.py`

- [ ] **Step 8: 服务器 `settings.py` 加开关**

在 `/opt/startrace/backend/server_api/settings.py` 中，`ai_retry_backoff_seconds` 行后追加：

```python
    ai_decision_enabled: bool = os.getenv("AI_DECISION_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}
```

- [ ] **Step 9: 服务器 `worker.py` 加开关判断**

在 `/opt/startrace/backend/server_api/worker.py` 的 `_run_cycle` 中，将现有的 `saved_ai`/`ai_client` 构造代码（当前紧邻 `for site in site_list():` 之前）**替换**为：

```python
        ai_client = None
        if getattr(settings, "ai_decision_enabled", False):
            from server_api.services.ai_settings import load_ai_configuration
            from server_api.services.ai_client import SharedAiClient

            saved_ai = await load_ai_configuration(session, encryption_secret=settings.credential_encryption_secret)
            ai_client = (
                SharedAiClient(provider=saved_ai.provider, base_url=saved_ai.base_url, model=saved_ai.model, api_key=saved_ai.api_key,
                               timeout_seconds=settings.ai_timeout_seconds, max_retries=settings.ai_max_retries,
                               retry_backoff_seconds=settings.ai_retry_backoff_seconds)
                if saved_ai is not None else _shared_ai_client_from_settings(settings)
            )
```

- [ ] **Step 10: 服务器 `.env` 加开关**

Run: `echo "AI_DECISION_ENABLED=false" >> /opt/startrace/backend/.env`（先 `grep -c AI_DECISION_ENABLED` 确认未重复）。

- [ ] **Step 11: 服务器语法校验**

Run: `ssh -p 62594 root@207.56.2.71 "cd /opt/startrace/backend && python -m py_compile server_api/settings.py server_api/worker.py server_api/workers/strategy_scheduler.py && echo OK"`
Expected: OK

---

### Task 4: 重建容器部署

**Files:**
- 无（部署动作）

- [ ] **Step 12: 重建 api + worker 容器**

Run: `ssh -p 62594 root@207.56.2.71 "cd /opt/startrace/backend && docker compose up --build --force-recreate -d --wait api worker"`
Expected: 容器 Up，等待就绪。

- [ ] **Step 13: 健康检查**

Run: `ssh -p 62594 root@207.56.2.71 "curl -s -w ' HTTP=%{http_code}\n' http://127.0.0.1:8080/health/ready"`
Expected: `{"status":"ok"} HTTP=200`

---

### Task 5: 容器内验证测试与策略事件

**Files:**
- Test: 复制 `backend/tests/test_strategy_scheduler.py` 到容器 `/tmp/`

- [ ] **Step 14: 容器内跑更新后的测试**

Run:
```bash
scp -P 62594 backend/tests/test_strategy_scheduler.py root@207.56.2.71:/tmp/test_strategy_scheduler.py
ssh -p 62594 root@207.56.2.71 "docker cp /tmp/test_strategy_scheduler.py startrace-worker-1:/tmp/test_strategy_scheduler.py && docker exec startrace-worker-1 sh -c 'cd /srv/app && PYTHONPATH=/srv/app python -m pytest /tmp/test_strategy_scheduler.py -q'"
```
Expected: PASS（6 passed）。测试用 sqlite 内存库，不触碰生产 postgres。

- [ ] **Step 15: 确认生产容器加载了新配置**

Run:
```bash
ssh -p 62594 root@207.56.2.71 "docker exec startrace-worker-1 sh -c 'cd /srv/app && PYTHONPATH=/srv/app python -c \"from server_api.settings import settings; print(\"ai_decision_enabled=\", settings.ai_decision_enabled)\"'"
```
Expected: `ai_decision_enabled= False`

- [ ] **Step 16: 观察策略事件（等待下一期触发）**

Run（等待约 2 分钟后）:
```bash
ssh -p 62594 root@207.56.2.71 "docker exec startrace-postgres-1 psql -U startrace -d startrace -c \"SELECT site, period, event_type, message FROM strategy_events ORDER BY created_at DESC LIMIT 5;\""
```
Expected: 最近的 `ai_execute` 事件消息含"算法决策下注"，且不再出现新的 `ai_error`（`ai_error` 历史记录保留）。

---

### Task 6: 本地 git 同步服务器代码并提交

**Files:**
- Modify（本地）: `backend/server_api/`（整目录同步为服务器版本）

- [ ] **Step 17: 同步服务器 `server_api` 到本地**

Run:
```bash
rm -rf backend/server_api
scp -P 62594 -r root@207.56.2.71:/opt/startrace/backend/server_api backend/server_api
find backend/server_api -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null || true
```

- [ ] **Step 18: 本地跑全部测试确认同步无破坏**

Run: `cd backend && ../.venv/Scripts/python.exe -m pytest -q`
Expected: PASS（若出现与旧 worker 签名相关的失败，以服务器版本为准更新对应测试）。

- [ ] **Step 19: 提交**

```bash
git add backend/server_api
git commit -m "chore: 同步服务器端 server_api（含纯算法下注、ai_settings、admin 路由）"
```

- [ ] **Step 20: 收尾确认**

Run: `git log --oneline -3`
Expected: 显示 Task 2 与 Task 6 的两个新提交。
