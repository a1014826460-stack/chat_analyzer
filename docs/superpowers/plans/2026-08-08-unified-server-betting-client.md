# 统一服务端下注体系——客户端与打包实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 客户端强制服务器模式（本地策略停用），服务器模式策略配置支持多类型，概率分析面板动态高度 + 北京时间，下注历史展示策略快照与结果；更新版本号并重新打包发布（自动更新推送）。

**Architecture:** `auto_bet_panel.py` 移除本地策略/AI 配置入口、自动下注仅服务器模式可用、`策略配置`对话框支持多策略类型并保存到服务端；`_frequency_analysis_label` 动态调整高度、`updated_at` 转北京时间；下注历史从服务端订单事件展示快照与结果。最后 `tools/build.py` 打包 + `release_manifest.py` 生成 latest.json + 上传 CDN 触发自动更新。

**Tech Stack:** Python 3.12 / PySide6 / pytest / PyInstaller（build.py）。

## Global Constraints

- 客户端本地策略引擎 `app/services/auto_bet_service.py` **停用不删**（代码冻结，界面移除入口）。
- 自动下注仅在服务器模式可用；未配置服务器/未登录时按钮禁用并提示。
- 策略类型：`three_doors`/`trend_following`/`flat`/`martingale`，经 `GET/PUT /v1/strategies/auto-bet` 读写。
- 概率面板：`_frequency_analysis_label` 动态高度不截断；`updated_at` 固定显示北京时间（UTC+8）。
- 版本号：更新为 **1.98.0**（执行前与用户确认）。
- 打包：用户版 `tools/build.py --clean`；管理员版 `tools/build.py --admin --clean`；`release_manifest.py` 生成 latest.json（需私钥）；上传 CDN 目录。
- 客户端测试在 `tests/`，命令：`.venv/Scripts/python.exe -m pytest -q`（UI 交互手动验证）。

---

### Task 1: 强制服务器模式 + 移除本地策略配置入口

**Files:**
- Modify: `app/ui/auto_bet_panel.py`
- Test: `tests/test_auto_bet_panel.py`（或新建，验证模式判定逻辑）

**Interfaces:**
- Consumes: 现有 `server_mode_settings.enabled`。
- Produces: 自动下注启动受服务器模式约束；本地 AI/策略配置按钮不再可用。

- [ ] **Step 1: 写失败测试**

若 `tests/test_auto_bet_panel.py` 不存在则新建。测试"自动下注在非服务器模式被禁用"的逻辑（抽取为可测的纯函数）：

```python
def test_auto_bet_requires_server_mode():
    from app.ui.auto_bet_panel import _auto_bet_available

    assert _auto_bet_available(server_mode_enabled=True, logged_in=True) is True
    assert _auto_bet_available(server_mode_enabled=False, logged_in=True) is False
    assert _auto_bet_available(server_mode_enabled=True, logged_in=False) is False
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/Scripts/python.exe -m pytest tests/test_auto_bet_panel.py -q`
Expected: FAIL（`_auto_bet_available` 不存在）。

- [ ] **Step 3: 实现模式判定**

在 `app/ui/auto_bet_panel.py` 顶部加纯函数：

```python
def _auto_bet_available(*, server_mode_enabled: bool, logged_in: bool) -> bool:
    """Auto-betting is only available in server mode with an active session."""
    return bool(server_mode_enabled and logged_in)
```

- [ ] **Step 4: 应用约束到启动逻辑**

找到自动下注"启动/开始"入口（`auto_bet_panel.py` 中连接自动下注服务 start 的槽函数），在启动前检查：

```python
        if not _auto_bet_available(
            server_mode_enabled=bool(getattr(getattr(self, "server_mode_settings", None), "enabled", False)),
            logged_in=bool(getattr(self, "_server_logged_in", False)),
        ):
            self._status_label.setText("自动下注需先进入服务器模式并登录")
            self._status_label.setStyleSheet("color: #c0392b;")
            return
```

- [ ] **Step 5: 移除本地策略配置入口**

在 `auto_bet_panel.py` 中：
- 本地模式专属的 AI 配置按钮（`self._ai_config_button` 当非服务器模式时显示的"AI 配置"）置为不可用或隐藏，提示"请使用服务器模式"。
- 若存在本地策略参数编辑区（趋势/倍投等），置灰并提示由服务器托管。

- [ ] **Step 6: 运行测试 + 手动验证**

Run: `.venv/Scripts/python.exe -m pytest tests/test_auto_bet_panel.py -q`
Expected: PASS。手动运行 `python app/main.py` 验证非服务器模式自动下注按钮被禁用并提示。

- [ ] **Step 7: 提交**

```bash
git add app/ui/auto_bet_panel.py tests/test_auto_bet_panel.py
git commit -m "feat: 客户端强制服务器模式，本地策略配置入口停用"
```

---

### Task 2: 服务器模式策略配置（多类型）

**Files:**
- Modify: `app/ui/auto_bet_panel.py`（`AiConfigDialog` / 服务器模式策略配置对话框）
- Test: `tests/test_auto_bet_panel.py`

**Interfaces:**
- Consumes: Task 1 的服务器模式约束；服务端 API `GET/PUT /v1/strategies/auto-bet`（含 Task 1(服务端计划) 的扩展字段）。
- Produces: 服务器模式"策略配置"对话框支持选择 `strategy_type` 并编辑对应参数，保存到服务端。

- [ ] **Step 1: 写测试（配置载荷构造）**

```python
def test_strategy_payload_multi_type():
    from app.ui.auto_bet_panel import _strategy_payload

    payload = _strategy_payload(
        strategy_type="martingale", play_types=["大", "小"],
        observation_window=10, trigger_threshold=3, martingale_sequence=[10, 20, 40],
    )
    assert payload["strategy_type"] == "martingale"
    assert payload["play_types"] == ["大", "小"]
    assert payload["martingale_sequence"] == [10, 20, 40]
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/Scripts/python.exe -m pytest tests/test_auto_bet_panel.py::test_strategy_payload_multi_type -q`
Expected: FAIL。

- [ ] **Step 3: 实现载荷构造**

```python
def _strategy_payload(*, strategy_type, play_types, observation_window, trigger_threshold, martingale_sequence, **base) -> dict:
    return {
        "strategy_type": str(strategy_type),
        "play_types": [str(p) for p in play_types],
        "observation_window": int(observation_window),
        "trigger_threshold": int(trigger_threshold),
        "martingale_sequence": [float(x) for x in martingale_sequence],
        **base,
    }
```

- [ ] **Step 4: 扩展策略配置对话框**

在服务器模式"策略配置"对话框（`auto_bet_panel.py`）中：
- 新增 `strategy_type` 下拉（三门 / 趋势跟踪 / 平注 / 倍投）。
- 按类型动态显示参数：三门→`history_count`/`confidence_threshold`；趋势→`observation_window`/`trigger_threshold`；平注/倍投→`play_types`（玩法多选）；倍投→`martingale_sequence`（逗号分隔金额）。
- 保存时调用 `server_api_client` 的 `put_auto_bet_strategy` 提交载荷（含基础字段 `site`/`bet_amount`/`target_groups`/`enabled` 等）。

- [ ] **Step 5: 运行测试**

Run: `.venv/Scripts/python.exe -m pytest tests/test_auto_bet_panel.py -q`
Expected: PASS。

- [ ] **Step 6: 提交**

```bash
git add app/ui/auto_bet_panel.py tests/test_auto_bet_panel.py
git commit -m "feat: 服务器模式策略配置支持多策略类型"
```

---

### Task 3: 概率分析面板——动态高度与北京时间

**Files:**
- Modify: `app/ui/auto_bet_panel.py`
- Test: `tests/test_auto_bet_panel.py`（时间转换纯函数）

**Interfaces:**
- Consumes: 现有 `_update_frequency_analysis`（`auto_bet_panel.py` 418、432-453 行）。
- Produces: `updated_at` 显示北京时间；长文本动态撑高 `_frequency_analysis_label`。

- [ ] **Step 1: 写测试（北京时间转换）**

```python
def test_beijing_time_conversion():
    from datetime import datetime
    from app.ui.auto_bet_panel import _beijing_time

    utc = datetime(2026, 8, 8, 6, 30, 0)  # 服务器 UTC
    assert _beijing_time(utc) == datetime(2026, 8, 8, 14, 30, 0)
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/Scripts/python.exe -m pytest tests/test_auto_bet_panel.py::test_beijing_time_conversion -q`
Expected: FAIL。

- [ ] **Step 3: 实现北京时间转换**

```python
def _beijing_time(utc_dt):
    from datetime import timedelta
    if utc_dt is None:
        return None
    if utc_dt.tzinfo is not None:
        utc_dt = utc_dt.astimezone(timezone.utc).replace(tzinfo=None)
    return utc_dt + timedelta(hours=8)
```

- [ ] **Step 4: 应用到面板**

`auto_bet_panel.py` 418 行改为：

```python
        updated_at = _beijing_time(analyzed_at).strftime("%H:%M:%S") if isinstance(analyzed_at, datetime) else str(field("updated_at", "-") or "-")
```

`auto_bet_panel.py` 432-453 行 `setText` 之后追加动态高度：

```python
        label = self._frequency_analysis_label
        label.adjustSize()
        if label.width() > 0:
            needed = label.heightForWidth(label.width())
            if needed > label.minimumHeight():
                label.setMinimumHeight(needed)
```

并在初始化处（944-948 行）确认 `_frequency_analysis_label` 的 sizePolicy 允许垂直扩展：

```python
        self._frequency_analysis_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
```

（若 `QSizePolicy` 已导入则直接使用；否则在文件顶部 `from PySide6.QtWidgets import QSizePolicy` 或从 `QtWidgets` 引入。）

- [ ] **Step 5: 运行测试**

Run: `.venv/Scripts/python.exe -m pytest tests/test_auto_bet_panel.py -q`
Expected: PASS。手动运行验证长文本不截断、时间显示北京时间（服务器 UTC +8）。

- [ ] **Step 6: 提交**

```bash
git add app/ui/auto_bet_panel.py tests/test_auto_bet_panel.py
git commit -m "feat: 概率分析面板动态高度与北京时间显示"
```

---

### Task 4: 下注历史展示策略快照与结果

**Files:**
- Modify: `app/ui/auto_bet_panel.py`（下注历史/运行日志区域）
- Test: `tests/test_auto_bet_panel.py`

**Interfaces:**
- Consumes: 服务端订单事件（`/v1/bets/events/latest`）或运行日志事件；Task 3(服务端计划) 的 `bet_orders.strategy_type`/`strategy_snapshot`/`result`/`result_detail`。
- Produces: 客户端展示每笔订单的策略类型、快照、结果。

- [ ] **Step 1: 写测试（订单事件格式化）**

```python
def test_format_order_event_with_result():
    from app.ui.auto_bet_panel import _format_order_event

    line = _format_order_event({
        "period": "3467000", "play_type": "小单", "amount": 10,
        "strategy_type": "three_doors", "result": "win", "result_detail": "exact_hit",
    })
    assert "小单" in line and "three_doors" in line and "exact_hit" in line
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/Scripts/python.exe -m pytest tests/test_auto_bet_panel.py::test_format_order_event_with_result -q`
Expected: FAIL。

- [ ] **Step 3: 实现格式化**

```python
def _format_order_event(item: dict) -> str:
    strategy = str(item.get("strategy_type", "") or "-")
    snapshot = item.get("strategy_snapshot")
    detail = ""
    if isinstance(snapshot, dict):
        selected = snapshot.get("selected_plays")
        if selected:
            detail = f" 选中:{'、'.join(selected)}"
    result = str(item.get("result", "") or "pending")
    result_text = {"win": "中", "lose": "不中", "pending": "待定", "failed": "发送失败", "expired": "过期"}.get(result, result)
    return f"{item.get('period', '')} {item.get('play_type', '')}@{item.get('amount', 0)} [{strategy}]{detail} → {result_text}"
```

- [ ] **Step 4: 接入面板**

在自动下注面板的下注历史/运行日志显示处，遍历服务端订单事件数据，用 `_format_order_event` 生成行追加到日志视图。若 `/v1/bets/events/latest` 返回条目缺少 `strategy_type`/`strategy_snapshot`/`result`，在服务端该端点序列化中补全（见服务端计划 Task 3 的字段；此处仅消费）。

- [ ] **Step 5: 运行测试**

Run: `.venv/Scripts/python.exe -m pytest tests/test_auto_bet_panel.py -q`
Expected: PASS。

- [ ] **Step 6: 提交**

```bash
git add app/ui/auto_bet_panel.py tests/test_auto_bet_panel.py
git commit -m "feat: 下注历史展示策略快照与结果"
```

---

### Task 5: 客户端全量测试

**Files:**
- 无（验证）

- [ ] **Step 1: 运行完整测试**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: 全部通过（既有 + 新增）。

- [ ] **Step 2: 编译检查**

Run: `.venv/Scripts/python.exe -m compileall -q app tools`
Expected: 无错误。

---

### Task 6: 更新版本号 + 打包 + 发布

**Files:**
- Modify: `app/build_config.py`（版本号，或由 `STARTRACE_VERSION` 注入）
- 生成: `dist/StarTrace-1.98.0.exe`、`dist/StarTrace-Admin-1.98.0.exe`、`dist/latest.json`、`dist/latest-admin.json`

**Interfaces:**
- Consumes: Task 1-4 的客户端改动；发布密钥与 CDN 配置。
- Produces: 新版本 exe + 更新清单，上传 CDN 触发客户端自动更新弹窗。

- [ ] **Step 1: 确认版本号**

与用户确认目标版本号（示例 **1.98.0**）。设置环境变量：

```powershell
$env:STARTRACE_VERSION = "1.98.0"
```

- [ ] **Step 2: 打包用户版**

```powershell
.\.venv\Scripts\python.exe tools\build.py --clean
```
Expected: `dist/StarTrace-1.98.0.exe` 生成。

- [ ] **Step 3: 打包管理员版**

```powershell
.\.venv\Scripts\python.exe tools\build.py --admin --clean
```
Expected: `dist/StarTrace-Admin-1.98.0.exe` 生成。

- [ ] **Step 4: 生成更新清单（latest.json）**

```powershell
.\.venv\Scripts\python.exe tools\release_manifest.py `
  --artifact dist\StarTrace-1.98.0.exe `
  --channel user `
  --version 1.98.0 `
  --base-url https://www.twsaimahui.com/startrace/user `
  --private-key C:\keys\update_private.pem `
  --notes "统一服务端下注：策略多类型、下注策略与结果记录、概率面板优化" `
  --output dist\latest.json

.\.venv\Scripts\python.exe tools\release_manifest.py `
  --artifact dist\StarTrace-Admin-1.98.0.exe `
  --channel admin `
  --version 1.98.0 `
  --base-url https://www.twsaimahui.com/startrace/admin `
  --private-key C:\keys\update_private.pem `
  --notes "管理员版：统一服务端下注" `
  --output dist\latest-admin.json
```
（若私钥路径不同，以 `release_user_config.bat`/`build_env.bat` 实际配置为准。）

- [ ] **Step 5: 上传 CDN**

按 `docs/release-packaging.md` 第 6 节目录结构上传：
- `StarTrace-1.98.0.exe` → `https://www.twsaimahui.com/startrace/user/`
- `latest.json` → `https://www.twsaimahui.com/startrace/user/`
- 管理员版同理到 `startrace/admin/`

- [ ] **Step 6: 验证自动更新**

用已安装的旧版 exe 启动，确认弹出更新提醒并自动下载安装（无需手动重新安装）。确认版本号更新为 1.98.0。

- [ ] **Step 7: 提交版本与配置**

```bash
git add app/build_config.py
git commit -m "release: 1.98.0 统一服务端下注"
git push origin main
```
（`dist/` 与密钥不入库。）
