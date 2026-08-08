# 统一服务端下注体系——服务端实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 服务端扩展多策略类型（三门/趋势/平注/倍投）统一执行，`bet_orders` 记录每次下注的策略快照与结果，客户端本地策略不再参与计算。

**Architecture:** 扩展 `AutoBetStrategy` 模型与 `strategies` API 支持 `strategy_type` 及参数；`strategy_scheduler.schedule_frequency_orders` 按策略类型分派判定；`BetOrder` 增加策略快照字段并在创建时写入；`bet_settlements` 开奖后按玩法回写 `result`/`result_detail`。纯算法模式保持（`AI_DECISION_ENABLED=false`）。

**Tech Stack:** Python 3.12 / FastAPI / SQLAlchemy 2.0 async / alembic / pytest / docker compose。

## Global Constraints

- 改动基准：本地 `backend/`（与服务器源码一致后同步部署）。
- 服务端策略类型：`three_doors` / `trend_following` / `flat` / `martingale`，每用户一条（`user_id` 唯一不变）。
- `bet_orders` 新字段：`strategy_type`、`strategy_snapshot`(JSON)、`result`(`pending`/`win`/`lose`/`expired`/`failed`)、`result_detail`(`exact_hit`/`direction_hit`/空)。
- 结果判定：压"小单"，开"小单"→`exact_hit`；开含"小"或"单"→`direction_hit`；否则 `lose`。
- 纯算法模式保持：`AI_DECISION_ENABLED=false`，AI 不干涉。
- 历史订单不回填，仅新订单记录快照与结果。
- 服务端测试在 `backend/tests/`（sqlite 内存），命令：`cd backend && ../.venv/Scripts/python.exe -m pytest -q`。
- 部署：改动同步到服务器 `/opt/startrace/backend` 后 `docker compose up --build --force-recreate -d --wait api worker`（project 名 `startrace`，勿改）。

---

### Task 1: AutoBetStrategy 模型扩展 + 迁移 + API

**Files:**
- Modify: `backend/server_api/db.py`（`AutoBetStrategy` 类）
- Modify: `backend/server_api/api/routes/strategies.py`
- Create: `backend/alembic/versions/20260808_10_strategy_types.py`
- Test: `backend/tests/test_strategy_api.py`

**Interfaces:**
- Produces: `AutoBetStrategy` 新增字段 `strategy_type`/`play_types_json`/`observation_window`/`trigger_threshold`/`martingale_sequence_json`；`GET/PUT /v1/strategies/auto-bet` 支持读写这些字段。

- [ ] **Step 1: 写失败测试**

在 `backend/tests/test_strategy_api.py` 新增：

```python
import asyncio
from sqlalchemy import select
from server_api.db import AutoBetStrategy, create_engine, create_schema, create_session_factory


def test_strategy_api_round_trips_extended_fields():
    from server_api.api.routes.strategies import serialize

    async def scenario() -> None:
        engine = create_engine("sqlite+aiosqlite:///:memory:")
        await create_schema(engine)
        factory = create_session_factory(engine)
        async with factory() as session:
            row = AutoBetStrategy(
                user_id=1, enabled=True, site="pc28",
                target_groups_json='["g1"]', target_group_names_json='{"g1":"群1"}',
                strategy_type="martingale", play_types_json='["大","小"]',
                observation_window=12, trigger_threshold=4, martingale_sequence_json='[10,20,40]',
            )
            session.add(row)
            await session.commit()
            data = serialize(await session.scalar(select(AutoBetStrategy).where(AutoBetStrategy.user_id == 1)))
            assert data["strategy_type"] == "martingale"
            assert data["play_types"] == ["大", "小"]
            assert data["observation_window"] == 12
            assert data["trigger_threshold"] == 4
            assert data["martingale_sequence"] == [10, 20, 40]
        await engine.dispose()

    asyncio.run(scenario())
```

- [ ] **Step 2: 运行确认失败**

Run: `cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_strategy_api.py -q`
Expected: FAIL（`AutoBetStrategy` 无 `strategy_type` 属性）。

- [ ] **Step 3: 扩展模型**

在 `backend/server_api/db.py` 的 `AutoBetStrategy` 类中 `bet_amount` 后追加：

```python
    strategy_type: Mapped[str] = mapped_column(String(32), default="three_doors")
    play_types_json: Mapped[str] = mapped_column(String, default="[]")
    observation_window: Mapped[int] = mapped_column(Integer, default=10)
    trigger_threshold: Mapped[int] = mapped_column(Integer, default=3)
    martingale_sequence_json: Mapped[str] = mapped_column(String, default="[]")
```

- [ ] **Step 4: 扩展 API**

`backend/server_api/api/routes/strategies.py`：
- `AutoBetStrategyRequest` 追加字段：

```python
    strategy_type: str = Field(default="three_doors", pattern="^(three_doors|trend_following|flat|martingale)$")
    play_types: list[str] = Field(default_factory=list, max_length=8)
    observation_window: int = Field(default=10, ge=3, le=100)
    trigger_threshold: int = Field(default=3, ge=1, le=20)
    martingale_sequence: list[float] = Field(default_factory=list, max_length=20)
```

- `serialize` 返回值追加：

```python
        "strategy_type": row.strategy_type,
        "play_types": json.loads(row.play_types_json or "[]"),
        "observation_window": row.observation_window,
        "trigger_threshold": row.trigger_threshold,
        "martingale_sequence": json.loads(row.martingale_sequence_json or "[]"),
```

- `put_auto_bet_strategy` 中，在 `values = payload.model_dump()` 后追加 JSON 字段转换（放在 `target_groups` 处理旁）：

```python
    values["play_types_json"] = json.dumps(values.pop("play_types", []), ensure_ascii=False, separators=(",", ":"))
    values["martingale_sequence_json"] = json.dumps(values.pop("martingale_sequence", []), ensure_ascii=False, separators=(",", ":"))
```

（`values` 中剩余 `strategy_type`/`observation_window`/`trigger_threshold` 直接落库。）

- [ ] **Step 5: 创建 alembic 迁移**

创建 `backend/alembic/versions/20260808_10_strategy_types.py`：

```python
"""add strategy type columns to auto_bet_strategies"""
from alembic import op
import sqlalchemy as sa

revision = "20260808_10"
down_revision = "20260804_09"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("auto_bet_strategies", sa.Column("strategy_type", sa.String(32), nullable=False, server_default="three_doors"))
    op.add_column("auto_bet_strategies", sa.Column("play_types_json", sa.Text(), nullable=False, server_default="[]"))
    op.add_column("auto_bet_strategies", sa.Column("observation_window", sa.Integer(), nullable=False, server_default="10"))
    op.add_column("auto_bet_strategies", sa.Column("trigger_threshold", sa.Integer(), nullable=False, server_default="3"))
    op.add_column("auto_bet_strategies", sa.Column("martingale_sequence_json", sa.Text(), nullable=False, server_default="[]"))


def downgrade() -> None:
    for column in ("strategy_type", "play_types_json", "observation_window", "trigger_threshold", "martingale_sequence_json"):
        op.drop_column("auto_bet_strategies", column)
```

确认 `down_revision` 与 `backend/alembic/versions/` 最新迁移一致（当前 `20260804_09`）。

- [ ] **Step 6: 运行测试确认通过**

Run: `cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_strategy_api.py -q`
Expected: PASS。

- [ ] **Step 7: 提交**

```bash
git add backend/server_api/db.py backend/server_api/api/routes/strategies.py backend/alembic/versions/20260808_10_strategy_types.py backend/tests/test_strategy_api.py
git commit -m "feat: 服务端策略模型扩展——多策略类型字段与 API"
```

---

### Task 2: 策略引擎多类型分派

**Files:**
- Modify: `backend/server_api/workers/strategy_scheduler.py`
- Test: `backend/tests/test_strategy_scheduler.py`

**Interfaces:**
- Consumes: Task 1 的 `AutoBetStrategy.strategy_type` 等字段；现有 `analyze`/`history`。
- Produces: `schedule_frequency_orders` 按 `strategy_type` 分派；辅助函数 `_trend_following_plays(site, rows, window, threshold)` 返回玩法列表或 None；`_martingale_amount(session, user_id, site, play_type, sequence, default)` 返回金额。

- [ ] **Step 1: 写失败测试**

在 `backend/tests/test_strategy_scheduler.py` 追加：

```python
def test_frequency_scheduler_trend_following_reverse_bet():
    from server_api.workers.strategy_scheduler import schedule_frequency_orders, _trend_following_plays
    from server_api.db import DrawResult

    rows = [DrawResult(site="pc28", period=str(i), result="小单", total=13) for i in range(1, 6)]
    assert _trend_following_plays("pc28", rows, window=5, threshold=3) == ["大"]

    rows_break = [DrawResult(site="pc28", period=str(i), result="小单" if i < 5 else "大单", total=13 + (i == 5)) for i in range(1, 6)]
    assert _trend_following_plays("pc28", rows_break, window=5, threshold=3) is None
```

- [ ] **Step 2: 运行确认失败**

Run: `cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_strategy_scheduler.py::test_frequency_scheduler_trend_following_reverse_bet -q`
Expected: FAIL（`_trend_following_plays` 不存在）。

- [ ] **Step 3: 实现辅助函数**

在 `backend/server_api/workers/strategy_scheduler.py` 顶部（`_DECISION_EVENT_TYPES` 后）追加：

```python
def _trend_following_plays(site: str, rows, window: int, threshold: int) -> list[str] | None:
    """Return the reverse play when the latest run of same size reaches threshold."""
    ordered = list(rows)[-max(1, window):]
    if not ordered:
        return None
    tail_base = "大" if str(ordered[-1].result).startswith("大") else "小"
    consecutive = 0
    for row in reversed(ordered):
        base = "大" if str(row.result).startswith("大") else "小"
        if base == tail_base:
            consecutive += 1
        else:
            break
    if consecutive < max(1, threshold):
        return None
    return ["小"] if tail_base == "大" else ["大"]


def _martingale_amount(sequence: list[float], consecutive_losses: int, default: float) -> float:
    steps = [float(value) for value in sequence if float(value) > 0] or [float(default)]
    return steps[min(max(consecutive_losses, 0), len(steps) - 1)]


async def _consecutive_losses(session, *, user_id: int, site: str, play_type: str, limit: int = 10) -> int:
    rows = (await session.scalars(
        select(BetOrder).where(
            BetOrder.user_id == user_id,
            BetOrder.site == site,
            BetOrder.play_type == play_type,
        ).order_by(BetOrder.id.desc()).limit(limit)
    )).all()
    count = 0
    for row in rows:
        if row.result == "lose":
            count += 1
        else:
            break
    return count
```

- [ ] **Step 4: 分派逻辑**

`schedule_frequency_orders` 中，在 `analysis = analyze(...)` 之前按 `strategy_type` 分派。将现有 `analysis`/`should_bet` 判定段（`if not analysis["should_bet"]: ... continue`）改为：

```python
        rows = await history(session, site, strategy.history_count)
        plays: list[str] = []
        reason: str = ""
        if strategy.strategy_type == "three_doors":
            analysis = analyze(site, rows, strategy.history_count, strategy.confidence_threshold)
            if not analysis["should_bet"]:
                await _add_decision_event_once(
                    session, user_id=strategy.user_id, site=site, period=period,
                    event_type="frequency_skip",
                    message=(
                        f"频率未达阈值：三门 {','.join(analysis['selected_plays'])}，"
                        f"最高 {analysis['highest_selected_probability']:.1f}% < 阈值 {strategy.confidence_threshold}%"
                    ),
                    group_names=group_names,
                )
                continue
            plays = list(analysis["selected_plays"])
            reason = analysis["reason"]
        elif strategy.strategy_type == "trend_following":
            trend_plays = _trend_following_plays(
                site, rows, strategy.observation_window, strategy.trigger_threshold
            )
            if trend_plays is None:
                await _add_decision_event_once(
                    session, user_id=strategy.user_id, site=site, period=period,
                    event_type="frequency_skip",
                    message=(
                        f"趋势未触发：观察 {strategy.observation_window} 期，"
                        f"连续 {strategy.trigger_threshold} 期同结果才反向下注"
                    ),
                    group_names=group_names,
                )
                continue
            plays = trend_plays
            reason = f"连续 {strategy.trigger_threshold} 期同向，反向押 {'、'.join(plays)}"
        else:  # flat / martingale
            plays = [str(play).strip() for play in json.loads(strategy.play_types_json or "[]") if str(play).strip()]
            if not plays:
                await _add_decision_event_once(
                    session, user_id=strategy.user_id, site=site, period=period,
                    event_type="frequency_skip",
                    message="未配置押注玩法（play_types 为空）",
                    group_names=group_names,
                )
                continue
            reason = f"策略 {strategy.strategy_type}：押 {'、'.join(plays)}"
        plays = list(dict.fromkeys(plays))
```

（保留原有 `if ai_client is not None:` AI 分支，其 `selected_plays=plays` 改用上述 `plays`；纯算法 `else` 分支的 `ai_execute` 事件消息保持，但 `highest_selected_probability` 引用改为 `reason`。）

纯算法 `else` 分支消息改为：

```python
        else:
            await _add_decision_event_once(
                session, user_id=strategy.user_id, site=site, period=period,
                event_type="ai_execute",
                message=(
                    f"频率达标：{reason}；算法决策下注（{strategy.strategy_type}）"
                ),
                group_names=group_names,
            )
```

- [ ] **Step 5: 运行测试**

Run: `cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_strategy_scheduler.py -q`
Expected: 既有 6 个 + 新增 1 个 = 7 passed。若既有测试因 `reason` 字段改动失败，按新消息格式更新断言。

- [ ] **Step 6: 提交**

```bash
git add backend/server_api/workers/strategy_scheduler.py backend/tests/test_strategy_scheduler.py
git commit -m "feat: 服务端策略引擎多类型分派——趋势/平注/倍投"
```

---

### Task 3: BetOrder 策略快照字段 + 创建时写入

**Files:**
- Modify: `backend/server_api/db.py`（`BetOrder` 类）
- Modify: `backend/server_api/workers/strategy_scheduler.py`
- Create: `backend/alembic/versions/20260808_11_bet_order_snapshot.py`
- Test: `backend/tests/test_strategy_scheduler.py`

**Interfaces:**
- Consumes: Task 2 的 `plays`/`reason`/`strategy` 上下文。
- Produces: `BetOrder` 新增 `strategy_type`/`strategy_snapshot`/`result`/`result_detail`，创建订单时写入快照。

- [ ] **Step 1: 写失败测试**

在 `backend/tests/test_strategy_scheduler.py` 追加：

```python
def test_frequency_scheduler_writes_strategy_snapshot():
    from server_api.workers.strategy_scheduler import schedule_frequency_orders

    async def scenario() -> None:
        engine = create_engine("sqlite+aiosqlite:///:memory:")
        await create_schema(engine)
        factory = create_session_factory(engine)
        async with factory() as session:
            session.add(AutoBetStrategy(
                user_id=20, enabled=True, site="pc28", target_groups_json='["group-a"]',
                history_count=4, confidence_threshold=50, require_confirmation=False,
                bet_amount=3, strategy_type="three_doors",
            ))
            session.add_all([
                DrawResult(site="pc28", period="1", result="小单", total=13),
                DrawResult(site="pc28", period="2", result="大双", total=14),
                DrawResult(site="pc28", period="3", result="大双", total=14),
                DrawResult(site="pc28", period="4", result="大单", total=15),
            ])
            await session.commit()
            assert await schedule_frequency_orders(session, site="pc28", period="next-snap") == 3
            order = await session.scalar(select(BetOrder))
            assert order.strategy_type == "three_doors"
            import json
            snapshot = json.loads(order.strategy_snapshot)
            assert snapshot["history_count"] == 4
            assert snapshot["confidence_threshold"] == 50
            assert order.result == "pending"
        await engine.dispose()

    asyncio.run(scenario())
```

- [ ] **Step 2: 运行确认失败**

Run: `cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_strategy_scheduler.py::test_frequency_scheduler_writes_strategy_snapshot -q`
Expected: FAIL（`BetOrder` 无 `strategy_type` 属性）。

- [ ] **Step 3: 扩展 BetOrder 模型**

`backend/server_api/db.py` 的 `BetOrder` 类 `betting_deadline_at` 后追加：

```python
    strategy_type: Mapped[str] = mapped_column(String(32), default="three_doors")
    strategy_snapshot: Mapped[str] = mapped_column(String, default="{}")
    result: Mapped[str] = mapped_column(String(16), default="pending")
    result_detail: Mapped[str] = mapped_column(String(32), default="")
```

- [ ] **Step 4: 创建 alembic 迁移**

创建 `backend/alembic/versions/20260808_11_bet_order_snapshot.py`（revision `"20260808_11"`，down_revision `"20260808_10"`）：

```python
"""add strategy snapshot columns to bet_orders"""
from alembic import op
import sqlalchemy as sa

revision = "20260808_11"
down_revision = "20260808_10"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("bet_orders", sa.Column("strategy_type", sa.String(32), nullable=False, server_default="three_doors"))
    op.add_column("bet_orders", sa.Column("strategy_snapshot", sa.Text(), nullable=False, server_default="{}"))
    op.add_column("bet_orders", sa.Column("result", sa.String(16), nullable=False, server_default="pending"))
    op.add_column("bet_orders", sa.Column("result_detail", sa.String(32), nullable=False, server_default=""))


def downgrade() -> None:
    for column in ("strategy_type", "strategy_snapshot", "result", "result_detail"):
        op.drop_column("bet_orders", column)
```

- [ ] **Step 5: 创建订单时写入快照**

`schedule_frequency_orders` 的 BetOrder 创建循环中，`session.add(BetOrder(...))` 追加字段：

```python
                session.add(BetOrder(
                    user_id=strategy.user_id,
                    site=site,
                    period=period,
                    group_id=group_id,
                    group_name=str(group_name_map.get(str(group_id), "未命名群组")).strip() or "未命名群组",
                    play_type=play_type,
                    amount=strategy.bet_amount,
                    status="pending_confirmation" if strategy.require_confirmation else "confirmed",
                    confirmation_deadline_at=deadline,
                    betting_deadline_at=betting_deadline_at,
                    strategy_type=strategy.strategy_type,
                    strategy_snapshot=json.dumps({
                        "history_count": strategy.history_count,
                        "confidence_threshold": strategy.confidence_threshold,
                        "strategy_type": strategy.strategy_type,
                        "selected_plays": plays,
                        "reason": reason,
                    }, ensure_ascii=False, separators=(",", ":")),
                    result="pending",
                ))
```

（`martingale` 策略的金额：将 `amount=strategy.bet_amount` 改为 `amount=_martingale_amount(json.loads(strategy.martingale_sequence_json or "[]"), await _consecutive_losses(session, user_id=strategy.user_id, site=site, play_type=play_type), strategy.bet_amount) if strategy.strategy_type == "martingale" else strategy.bet_amount`。注意 `json` 已在文件顶部导入。）

- [ ] **Step 6: 运行测试**

Run: `cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_strategy_scheduler.py -q`
Expected: PASS（快照测试通过，其余不受影响）。

- [ ] **Step 7: 提交**

```bash
git add backend/server_api/db.py backend/server_api/workers/strategy_scheduler.py backend/alembic/versions/20260808_11_bet_order_snapshot.py backend/tests/test_strategy_scheduler.py
git commit -m "feat: bet_orders 记录策略快照字段"
```

---

### Task 4: 结算结果回写

**Files:**
- Modify: `backend/server_api/services/bet_settlements.py`
- Test: `backend/tests/test_bet_settlements.py`

**Interfaces:**
- Consumes: Task 3 的 `BetOrder.result`/`result_detail`。
- Produces: 结算时回写每笔订单 `result`（`win`/`lose`）与 `result_detail`（`exact_hit`/`direction_hit`）。

- [ ] **Step 1: 写失败测试**

在 `backend/tests/test_bet_settlements.py` 追加（或新建，若文件不存在）:

```python
def test_result_writeback_per_play():
    from server_api.services.bet_statistics import DEFAULT_ODDS, _bet_wins

    assert _bet_wins("小单", "小单") is True
    assert _bet_wins("小单", "小双") is True
    assert _bet_wins("小单", "大单") is True
    assert _bet_wins("小单", "大双") is False
```

（若 `_bet_wins` 已存在且通过，则追加 `result_detail` 判定辅助函数的测试，见 Step 3。）

- [ ] **Step 2: 运行确认**

Run: `cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_bet_settlements.py -q`
Expected: 若 `_bet_wins` 已实现则 PASS；无该函数则 FAIL 后进入 Step 3 一起实现。

- [ ] **Step 3: 实现回写**

在 `backend/server_api/services/bet_settlements.py` 中，`settle_new_draws` 遍历订单时（现有 `_bet_wins(order.play_type, draw.result)` 判定处），为每笔订单回写：

```python
        for order in orders:
            wins = _bet_wins(order.play_type, draw.result)
            result = "win" if wins else "lose"
            detail = ""
            if wins:
                if order.play_type == draw.result:
                    detail = "exact_hit"
                else:
                    detail = "direction_hit"
            order.result = result
            order.result_detail = detail
```

在 `_bet_wins` 之后新增辅助（若尚无精确/方向区分）：

```python
def _result_detail(play_type: str, result: str) -> str:
    if play_type == result:
        return "exact_hit"
    if _bet_wins(play_type, result):
        return "direction_hit"
    return ""
```

- [ ] **Step 4: 运行测试**

Run: `cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_bet_settlements.py -q`
Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add backend/server_api/services/bet_settlements.py backend/tests/test_bet_settlements.py
git commit -m "feat: 结算回写每笔订单结果与命中明细"
```

---

### Task 5: 部署到服务器

**Files:**
- Modify（服务器）: `/opt/startrace/backend/server_api/`（同步上述改动）
- 无本地 commit

- [ ] **Step 1: 同步服务端代码到服务器**

```bash
scp -P 62594 -r backend/server_api/db.py backend/server_api/api/routes/strategies.py backend/server_api/workers/strategy_scheduler.py backend/server_api/services/bet_settlements.py root@207.56.2.71:/opt/startrace/backend/server_api/
```

- [ ] **Step 2: 同步 alembic 迁移**

```bash
scp -P 62594 backend/alembic/versions/20260808_10_strategy_types.py backend/alembic/versions/20260808_11_bet_order_snapshot.py root@207.56.2.71:/opt/startrace/backend/alembic/versions/
```

- [ ] **Step 3: 重建容器（自动跑迁移）**

```bash
ssh -p 62594 root@207.56.2.71 "cd /opt/startrace/backend && docker compose up --build --force-recreate -d --wait api worker"
```

- [ ] **Step 4: 验证**

```bash
ssh -p 62594 root@207.56.2.71 "curl -s -w ' HTTP=%{http_code}\n' http://127.0.0.1:8080/health/ready"
ssh -p 62594 root@207.56.2.71 "docker exec startrace-postgres-1 psql -U startrace -d startrace -c '\\d auto_bet_strategies' | grep -E 'strategy_type|play_types|observation|trigger|martingale'"
ssh -p 62594 root@207.56.2.71 "docker exec startrace-postgres-1 psql -U startrace -d startrace -c '\\d bet_orders' | grep -E 'strategy_type|strategy_snapshot|result'"
```
Expected: 新列存在、健康检查 200。

- [ ] **Step 5: 确认现有策略不回归**

查询 `strategy_events` 最近事件仍为 `frequency_skip`（策略1 默认 `three_doors`，行为不变）：
```bash
ssh -p 62594 root@207.56.2.71 "docker exec startrace-postgres-1 psql -U startrace -d startrace -c \"SELECT site, period, event_type FROM strategy_events ORDER BY id DESC LIMIT 3;\""
```
Expected: 仍为 `frequency_skip`。
