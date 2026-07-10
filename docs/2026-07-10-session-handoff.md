# 2026-07-10 会话工作总结与下一阶段交接

> 项目路径：`D:\pythonProject\outsource\chat_analyzer`  
> 运行命令：`.\.venv\Scripts\python.exe app\main.py --admin --debug`  
> 本文用于开启新会话后的上下文交接。

## 1. 本会话主要目标

本会话围绕“自动下注”功能与 Web WSS 消息发送链路进行了持续开发、调试和 UI 优化，核心目标包括：

1. 复刻 Web 端 WSS 发送逻辑，避免使用 ImSDK 导致顶号。
2. 将 WSS 发送逻辑嵌入自动下注系统。
3. 增加固定倍投策略及相关 UI。
4. 修复自动下注运行中的多群组、去重、下注格式、日志显示等问题。
5. 优化线路选择与自动下注面板之间的站点同步关系。
6. 为下一阶段继续开发留下明确状态。

## 2. Web WSS 发送能力

### 2.1 实现文件

核心文件：

- `app/services/ws_message_sender.py`
- `tests/test_ws_message_sender.py`
- `tests/test_wss_protocol.py`
- `tests/test_wuquan_account_mapping.py`

### 2.2 已实现内容

`WsMessageSender` 已实现基于 Web WSS 协议的消息发送，不使用 ImSDK。

协议关键点：

- WSS 地址：
  - `wss://wsssgp.im.qcloud.com/binfo`
  - backup：`wss://wsssgp.my-imcloud.com/binfo`
- frame 编码：直接 JSON bytes：

```python
json.dumps({"head": head, "body": body}, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
```

- 支持命令：
  - `im_open_status.wslogin`
  - `heartbeat.alive`
  - `group_open_http_svc.send_group_msg`
  - `openim.sendmsg`

### 2.3 消息加密

Web 端文本消息使用 AES-ECB + Base64：

- key：`666888`
- 函数：
  - `encrypt_text()`
  - `decrypt_text()`

### 2.4 自动重连

已修复运行一段时间后出现“DB 注入失败”的问题。

根因：WSS socket 过期/断线后，原逻辑不自动重连，导致后续 `inject_bet()` 返回 False，UI 误显示为“DB 注入失败”。

现逻辑：

- 如果 WSS 传输层失败；
- 自动关闭旧 socket；
- 重新连接；
- 重新登录；
- 重试一次发送。

业务拒绝，例如权限不足、UserSig 失效，不盲目重试。

## 3. 自动下注策略

### 3.1 核心文件

- `app/services/auto_bet_service.py`
- `app/models/auto_bet.py`
- `tests/test_auto_bet_runtime.py`

### 3.2 策略类型

已支持：

1. `trend_following`：趋势反打
2. `martingale`：固定倍投

### 3.3 固定倍投策略

固定倍投特点：

- 不等待连续阈值；
- 每个可下注窗口按已选玩法下注；
- 金额来自 `martingale_sequence` 当前档位；
- 赢后回到第一档；
- 输后进入下一档；
- 最后一档仍输则暂停。

### 3.4 多群组下注修复

之前问题：多群组下注只会下注第一个目标群组。

现已修复：

- `_analyze_many()` 会为所有 `target_groups` 生成下注决策。
- 同一玩法会分别发送到每个已选群组。

### 3.5 同期去重规则

之前问题：只按期数去重，容易影响多群组或不同站点。

现规则：

```text
site + period + group_id
```

即同一站点、同一期、同一群组只下注一次。

相关内部状态：

```python
self._bet_keys: set[tuple[str, str, str]]
```

## 4. 下注消息格式

### 4.1 当前要求

下注文本格式已改为：

```text
下注种类+金额
```

例如：

```text
大100
小100
```

中间没有空格、冒号、逗号或其他符号。

### 4.2 多玩法组合发送

最新需求：同一群组、同一期、同一站点下多个玩法应连续拼接为一条消息。

例如原来两条：

```text
大100
小100
```

现在一条：

```text
大100小100
```

对应实现：

- `AutoBetService._group_decisions()`
- `AutoBetService._execute_group()`

如果 injector 支持 `inject_text()`，则组合发送；否则回退到逐条 `inject_bet()`。

### 4.3 已同步修改的 sender

以下发送器下注格式均已改为无空格：

- `app/services/ws_message_sender.py`
- `app/services/uia_wuquan_sender.py`
- `app/services/background_window_sender.py`
- `app/services/rest_message_sender.py`
- `app/services/message_injector.py`
- `app/services/remote_im_sender.py`

## 5. 自动下注 UI 改动

### 5.1 核心文件

- `app/ui/auto_bet_panel.py`
- `tests/test_auto_bet_panel_help.py`

### 5.2 策略选择与帮助

自动下注面板新增：

- 策略下拉框：
  - 趋势反打
  - 固定倍投
- `?` 帮助按钮：显示策略说明。

相关函数：

```python
strategy_help_text()
```

### 5.3 投注金额与倍投序列显示规则

已实现：

1. “倍投序列”仅在选择“固定倍投”时显示。
2. 固定倍投模式下，如果倍投序列有有效值，则隐藏“下注金额”。
3. 非固定倍投模式下隐藏“倍投序列”，显示“下注金额”。

相关 UI 控件：

- `_amount_row_widget`
- `_martingale_row_widget`

### 5.4 目标群组运行时锁定

启动自动下注后：

- 目标群组列表禁用；
- 不允许修改目标群组；
- 显示提示：

```text
运行中已锁定目标群组，如需修改请先停止自动下注。
```

停止后：

- 目标群组列表恢复可编辑；
- 提示隐藏。

相关控件：

```python
self._target_group_lock_hint
```

### 5.5 自动下注日志格式

之前日志中的 `?` 是原来的箭头 `→` 在当前环境显示异常导致的乱码。

现已改为稳定中文分隔符：

```text
下注：
```

当前日志格式示例：

```text
23:53:58 ✓ [pc28 3455061] [A吸金A] 下注：大100小100
```

日志内容包括：

- 时间；
- 成功/失败标识；
- 站点；
- 当前期数；
- 群组昵称；
- 实际发送的下注内容。

## 6. 线路选择与站点同步

### 6.1 核心文件

- `app/ui/main_window_realtime.py`
- `app/ui/main_window_data.py`
- `tests/test_site_selection_ui.py`

### 6.2 自动下注站点跟随线路选择

自动下注面板中的“站点”不再允许独立修改。

规则：

- 自动下注站点强制跟随左侧“线路选择”当前 active site；
- `AutoBetPanel.get_config()` 使用 active site；
- 主窗口刷新 active site 时同步到 auto bet panel。

相关方法：

```python
AutoBetPanel.set_active_site(site)
```

### 6.3 线路选择视觉高亮

当前选中站点卡片已增加视觉区分：

- 高亮背景；
- 2px 边框；
- 选中标记。

相关方法：

- `_refresh_site_card_selection()`
- `_apply_site_card_selection_style()`

## 7. 群组昵称映射

下注日志不再显示群组 ID，而是显示群组昵称。

实现：

- `AutoBetPanel.set_available_groups()` 保存 `_group_names`；
- `AutoBetService.set_group_names()` 保存服务层群组映射；
- `MainWindowDataMixin._refresh_auto_bet_groups()` 同步群组映射到服务层。

如果找不到昵称，则回退显示 group_id。

## 8. 模型结构变更

### 8.1 `InjectRecord`

文件：`app/models/auto_bet.py`

新增字段：

```python
site: str = ""
period: str = ""
group_id: str = ""
```

用于日志显示站点、期数和群组映射。

## 9. 重要测试文件

本会话新增或扩展的测试主要包括：

- `tests/test_auto_bet_runtime.py`
- `tests/test_auto_bet_panel_help.py`
- `tests/test_ws_message_sender.py`
- `tests/test_site_selection_ui.py`
- `tests/test_rest_message_sender.py`
- `tests/test_draw_result_provider.py`
- `tests/test_wss_protocol.py`
- `tests/test_wuquan_account_mapping.py`
- `tests/test_uia_wuquan_sender.py`

最后一次相关回归测试命令：

```powershell
.\.venv\Scripts\python.exe -m pytest `
  tests\test_auto_bet_runtime.py `
  tests\test_auto_bet_panel_help.py `
  tests\test_ws_message_sender.py `
  tests\test_wss_protocol.py `
  tests\test_site_selection_ui.py `
  tests\test_wuquan_account_mapping.py `
  tests\test_rest_message_sender.py `
  tests\test_uia_wuquan_sender.py `
  tests\test_draw_result_provider.py::test_auto_bet_start_creates_and_injects_draw_result_store `
  tests\test_draw_result_provider.py::test_auto_bet_start_falls_back_to_background_sender_when_wss_startup_fails `
  tests\test_rest_message_sender.py::test_auto_bet_start_source_does_not_import_message_injector_for_tim_login -q
```

结果：

```text
57 passed in 1.37s
```

## 10. 当前 Git 工作区状态概要

本会话存在未提交修改。

主要修改文件：

- `app/models/auto_bet.py`
- `app/services/auto_bet_service.py`
- `app/services/ws_message_sender.py`
- `app/services/background_window_sender.py`
- `app/services/message_injector.py`
- `app/services/remote_im_sender.py`
- `app/services/rest_message_sender.py`
- `app/services/uia_wuquan_sender.py`
- `app/ui/auto_bet_panel.py`
- `app/ui/main_window_data.py`
- `app/ui/main_window_realtime.py`
- `tests/test_auto_bet_runtime.py`
- `tests/test_draw_result_provider.py`
- `tests/test_rest_message_sender.py`

新增测试文件：

- `tests/test_auto_bet_panel_help.py`
- `tests/test_site_selection_ui.py`
- `tests/test_ws_message_sender.py`

## 11. 下一阶段建议

建议新会话从以下方向继续：

1. **真实运行验证组合下注**
   - 启动程序；
   - 选择两个目标群；
   - 固定倍投选择“大/小”；
   - 确认群内实际收到：

   ```text
   大100小100
   ```

2. **观察 WSS 长时间运行稳定性**
   - 关注是否出现自动重连日志：

   ```text
   Web WSS transport failed; reconnecting and retrying once
   Web WSS reconnected
   ```

3. **进一步优化日志错误原因**
   - 当前失败 UI 仍可能显示通用 `DB 注入失败`；
   - 可以继续改为更准确区分：
     - WSS 登录失败；
     - WSS 发送超时；
     - 群权限失败；
     - 本地 DB 校验失败。

4. **固定倍投结算逻辑实测**
   - 验证胜负结算后档位是否正确推进；
   - 多群组、多玩法组合下注下是否应按“整轮”或“单群”结算。

5. **全量测试现状**
   - 本会话只保证相关测试集通过；
   - 历史全量测试可能仍有旧失败，特别是 `tests/test_source_recovery.py` 相关旧问题。

## 12. 快速启动命令

```powershell
.\.venv\Scripts\python.exe app\main.py --admin --debug
```

## 13. 当前行为速查

自动下注启动后：

- 目标群组锁定；
- 站点跟随左侧线路选择；
- 固定倍投显示倍投序列；
- 多玩法同群组合成一条下注；
- 多群组分别发送；
- 日志显示群昵称、站点、期数和实际下注内容。

示例日志：

```text
23:53:58 ✓ [pc28 3455061] [A吸金A] 下注：大100小100
23:53:58 ✓ [pc28 3455061] [射手座4.6-4.2] 下注：大100小100
```
