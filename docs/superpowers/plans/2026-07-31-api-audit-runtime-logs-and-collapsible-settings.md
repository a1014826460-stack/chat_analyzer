# API 审计、运行日志与折叠配置 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ensure all non-Tencent external client APIs are mediated by the authenticated server, provide secure pageable runtime logs in the auto-bet panel, and make the four configuration modules state-preserving collapsible groups.

**Architecture:** The FastAPI service owns structured runtime events and exposes a user-scoped cursor API. The desktop calls it through `ServerApiClient`; its auto-bet panel replaces the unbounded text display with a filtered, bounded, refreshable view. A reusable Qt collapse widget retains already-created controls while the layout wraps existing controls into Basic, Advanced, and Actions groups.

**Tech Stack:** Python 3, FastAPI, SQLAlchemy/Alembic, pytest, PySide6, urllib.

---

### Task 1: Publish the API inventory and prevent new direct production traffic

**Files:**
- Create: `docs/api-interface-inventory.md`
- Create: `tests/test_api_interface_inventory.py`
- Modify: `app/utils/fetch_date.py`
- Modify: `app/utils/history_records.py`
- Modify: `app/services/ai_bet_client.py`
- Modify: `app/services/update_service.py`

- [ ] **Step 1: Write the failing inventory/allowlist test**

```python
def test_production_client_network_calls_are_centralized_except_tencent_im():
    violations = find_production_network_violations(PRODUCTION_FILES)
    assert violations == []


def test_inventory_covers_discovered_routes_and_network_entrypoints():
    inventory = Path("docs/api-interface-inventory.md").read_text(encoding="utf-8")
    for identifier in DISCOVERED_IDENTIFIERS:
        assert identifier in inventory
```

- [ ] **Step 2: Run the new test and verify it fails because direct client network modules remain**

Run: `pytest tests/test_api_interface_inventory.py -q`

Expected: FAIL listing non-Tencent `urlopen` production paths.

- [ ] **Step 3: Write a complete interface inventory**

Document every FastAPI route, each worker outbound source, each desktop entrypoint and each diagnostic tool; include protocol, source location, caller-to-target chain, authentication, validation, sensitivity, mandatory-proxy status, and verification. Register only `app/services/ws_message_sender.py` and `app/services/rest_message_sender.py` as Tencent IM exceptions.

- [ ] **Step 4: Move or disable production direct network fallbacks**

Make the desktop's active paths obtain draws/history/AI/update data through `ServerApiClient`. Keep legacy parsers only as pure conversion helpers where needed, and reject direct execution from production classes. Do not alter Tencent IM REST/WSS senders.

- [ ] **Step 5: Run the audit test**

Run: `pytest tests/test_api_interface_inventory.py -q`

Expected: PASS.

### Task 2: Persist and query sanitized runtime log events

**Files:**
- Modify: `backend/server_api/db.py`
- Create: `backend/alembic/versions/20260731_08_runtime_log_events.py`
- Create: `backend/server_api/services/runtime_logs.py`
- Create: `backend/server_api/api/routes/runtime_logs.py`
- Modify: `backend/server_api/main.py`
- Create: `backend/tests/test_runtime_logs.py`

- [ ] **Step 1: Write failing runtime-log service and endpoint tests**

```python
def test_runtime_logs_filter_by_level_time_keyword_and_cursor(client, token):
    page = client.get("/v1/runtime-logs?level=ERROR&keyword=timeout&limit=1", headers=token)
    assert page.status_code == 200
    assert page.json()["has_more"] is True
    assert page.json()["items"][0]["level"] == "ERROR"


def test_runtime_logs_hide_another_users_events_and_sensitive_values(client, token):
    response = client.get("/v1/runtime-logs", headers=token)
    assert "server-secret" not in response.text
    assert all(item["user_id"] != 2 for item in response.json()["items"])
```

- [ ] **Step 2: Run the tests and verify endpoint absence**

Run: `pytest backend/tests/test_runtime_logs.py -q`

Expected: FAIL with 404 or missing import.

- [ ] **Step 3: Add model, migration, sanitizer, writer, and cursor query service**

Define `RuntimeLogEvent` with nullable user owner and indexed `(user_id, id)` / `(category, id)` access paths. `RuntimeLogService` must normalize levels/categories, remove secret values and URL query strings, serialize details safely, and write user actions, exceptions, system events, and proxied third-party results.

- [ ] **Step 4: Add authenticated `/v1/runtime-logs`**

Validate enums, ISO timestamps, keyword length, `before_id`, page bounds and date order. Return newest-first `items`, `next_before_id`, and `has_more`; scope records to the caller plus safe global service observations.

- [ ] **Step 5: Re-run the runtime-log backend tests**

Run: `pytest backend/tests/test_runtime_logs.py -q`

Expected: PASS.

### Task 3: Instrument server behavior and third-party calls

**Files:**
- Modify: `backend/server_api/api/routes/auth.py`
- Modify: `backend/server_api/api/routes/bets.py`
- Modify: `backend/server_api/api/routes/strategies.py`
- Modify: `backend/server_api/worker.py`
- Modify: `backend/server_api/workers/current_period.py`
- Modify: `backend/server_api/workers/history_sources.py`
- Modify: `backend/server_api/services/ai_client.py`
- Create: `backend/server_api/services/system_metrics.py`
- Modify: `backend/server_api/settings.py`
- Modify: `backend/tests/test_runtime_logs.py`

- [ ] **Step 1: Add failing instrumentation tests**

```python
def test_login_setting_and_bet_actions_write_user_visible_log_events(...):
    assert actions == {"login", "strategy_saved", "bet_created", "bet_confirmed", "bet_skipped"}


def test_third_party_wrapper_records_sanitized_url_duration_status_and_failure(...):
    assert event["request_url"] == "https://source.example/path"
    assert event["status_code"] == 502
    assert event["duration_ms"] >= 0
```

- [ ] **Step 2: Run the instrumentation tests and verify failure**

Run: `pytest backend/tests/test_runtime_logs.py -q`

Expected: FAIL because event writers are not invoked.

- [ ] **Step 3: Implement action/lifecycle/third-party instrumentation**

Wrap registered outbound calls with timing and exception logging. Record API and worker startup/shutdown plus configurable five-second CPU/memory samples without exposing process secrets. Call the common writer after successful login, strategy writes, and all bet state transitions.

- [ ] **Step 4: Re-run backend runtime-log and existing route tests**

Run: `pytest backend/tests/test_runtime_logs.py backend/tests/test_auth.py backend/tests/test_bets.py backend/tests/test_strategies.py -q`

Expected: PASS.

### Task 4: Fetch runtime logs safely in the client and render them in AutoBetPanel

**Files:**
- Modify: `app/services/server_api_client.py`
- Modify: `app/ui/auto_bet_panel.py`
- Modify: `app/ui/main_window_data.py`
- Modify: `tests/test_server_api_client.py`
- Modify: `tests/test_auto_bet_panel_help.py`

- [ ] **Step 1: Write failing client/panel tests**

```python
def test_server_api_client_fetches_runtime_logs_with_filters_and_cursor():
    assert client.runtime_logs(level="ERROR", before_id=20)["items"] == [{"id": 19}]


def test_auto_bet_log_defaults_to_five_seconds_and_appends_one_page_at_a_time(qtbot):
    assert panel.log_refresh_interval_seconds() == 5
    panel.apply_runtime_log_page(page_one, replace=True)
    panel.apply_runtime_log_page(page_two, replace=False)
    assert panel.runtime_log_row_count() == 100
```

- [ ] **Step 2: Run tests and verify the missing API/UI behavior**

Run: `pytest tests/test_server_api_client.py tests/test_auto_bet_panel_help.py -q`

Expected: FAIL for undefined runtime-log API or controls.

- [ ] **Step 3: Add client protocol and bounded panel controls**

Add `ServerApiClient.runtime_logs`. Replace the run-log text area with level, time, keyword, interval controls, a bounded `QListWidget`, status label, and Load More. Provide panel methods to build filters, replace/append pages, preserve pages after errors, and avoid fetching while hidden, unauthenticated, or already in progress.

- [ ] **Step 4: Integrate a single Qt-owned refresh scheduler**

In `MainWindowDataMixin`, use the configured five-second default to request `runtime_logs` asynchronously, pass fresh first pages or cursor pages to the panel, retain prior content on failure, and reset pagination when filters change.

- [ ] **Step 5: Run client and Qt tests**

Run: `pytest tests/test_server_api_client.py tests/test_auto_bet_panel_help.py -q`

Expected: PASS.

### Task 5: Add persistent, reusable collapsible sections

**Files:**
- Create: `app/ui/collapsible_section.py`
- Create: `tests/test_collapsible_section.py`
- Modify: `app/ui/main_window_layout.py`
- Modify: `app/ui/auto_bet_panel.py`
- Modify: `tests/test_site_selection_ui.py`
- Modify: `tests/test_auto_bet_panel_help.py`

- [ ] **Step 1: Write failing widget and integration tests**

```python
def test_collapsible_section_keeps_the_same_content_widget_and_value(qtbot):
    field.setText("preserved")
    section.set_expanded(False)
    section.set_expanded(True)
    assert section.content_widget() is content
    assert field.text() == "preserved"


def test_four_primary_modules_default_to_only_basic_group_expanded(qtbot):
    assert all(not group.is_expanded() for group in advanced_and_actions)
```

- [ ] **Step 2: Run the tests and verify the widget does not exist**

Run: `pytest tests/test_collapsible_section.py tests/test_site_selection_ui.py tests/test_auto_bet_panel_help.py -q`

Expected: FAIL with missing module or group attributes.

- [ ] **Step 3: Implement the persistent collapse widget**

Use a checkable title button and one permanent content container. Toggle only visibility and maximum height; never reconstruct children or reconnect signals. Expose `is_expanded`, `set_expanded`, and the content container.

- [ ] **Step 4: Group the four modules without renaming existing control attributes**

Create Basic/Advanced/Actions containers for site selection, account/data source, block list, and auto bet. Put all existing controls in exactly one container, with Basic expanded and other groups collapsed. Keep AutoBetPanel's log and confirmation actions in its Actions group.

- [ ] **Step 5: Run all collapse/UI tests**

Run: `pytest tests/test_collapsible_section.py tests/test_site_selection_ui.py tests/test_auto_bet_panel_help.py -q`

Expected: PASS.

### Task 6: Run migrations, documentation checks, and full regression verification

**Files:**
- Modify: `docs/server-deployment.md`
- Modify: `backend/.env.example`
- Modify: `backend/deploy/server.env.example`
- Modify: `docs/api-interface-inventory.md`

- [ ] **Step 1: Add deployment configuration and ingress restrictions**

Document `SYSTEM_METRICS_INTERVAL_SECONDS`, runtime-log migration, route authentication, `/health/ready` reverse-proxy restriction, retention operations, and the Tencent IM client exception. Ensure examples have no actual secrets.

- [ ] **Step 2: Run formatting/import and migration checks**

Run: `python -m compileall app backend/server_api && python -m alembic -c backend/alembic.ini heads`

Expected: compilation succeeds and Alembic reports one head.

- [ ] **Step 3: Run full regression suites**

Run: `pytest -q && pytest backend/tests -q`

Expected: all tests PASS.

- [ ] **Step 4: Commit implementation**

```bash
git add app backend tests docs
git commit -m "feat: centralize runtime logs and collapsible settings"
```
