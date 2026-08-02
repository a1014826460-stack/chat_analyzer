# 一级模块手风琴与开奖降级 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用状态保持的一级模块手风琴替代子配置折叠，并隔离当前期开奖 API 的单线路失败。

**Architecture:** `CollapsibleSection` 提供视觉化、可动画的永久内容容器；布局将四个一级模块直接作为其消费者并以协调器实现互斥展开。实时加载函数按线路捕获 API 异常并传递已有数据和失败状态。

**Tech Stack:** Python、PySide6、FastAPI client、pytest。

---

### Task 1: 一级模块手风琴组件

**Files:**
- Modify: `app/ui/collapsible_section.py`
- Modify: `tests/test_collapsible_section.py`

- [ ] 写入验证“标题圆角样式、箭头/内容动画、内容对象不重建”的失败测试；运行 `pytest tests/test_collapsible_section.py -q`。
- [ ] 为标题卡片增加主题 QSS、`QPropertyAnimation` 和可选摘要；保留 `content_widget`、`content_layout`、`set_expanded` 契约。
- [ ] 运行测试并提交组件变更。

### Task 2: 四个一级模块布局

**Files:**
- Modify: `app/ui/main_window_layout.py`
- Modify: `app/ui/auto_bet_panel.py`
- Modify: `tests/test_site_selection_ui.py`
- Modify: `tests/test_auto_bet_panel_help.py`

- [ ] 写入失败测试，要求四个 `*_module_section` 互斥展开且无基础/高级/操作区。
- [ ] 将原有控件移动到四个一级容器；连接 `expanded_changed` 关闭其余模块，默认线路选择展开。
- [ ] 运行相关 Qt 测试并提交。

### Task 3: 当前期开奖单线路降级

**Files:**
- Modify: `app/ui/main_window_realtime.py`
- Modify: `tests/test_site_selection_ui.py`

- [ ] 写入失败测试，模拟一条 `current_draw` 抛出 `ServerApiError` 而另一条正常返回。
- [ ] 逐线路捕获失败，返回先前 `DrawInfo` 与错误信息，保留卡片并让成功线路继续显示。
- [ ] 运行测试并提交。

### Task 4: 验证与文档

**Files:**
- Modify: `docs/ui_and_flow.md`

- [ ] 更新 UI 文档为一级模块手风琴和服务端开奖降级行为。
- [ ] 运行 `pytest tests/test_collapsible_section.py tests/test_site_selection_ui.py tests/test_auto_bet_panel_help.py -q`、`python -m compileall -q app` 和完整相关回归。
