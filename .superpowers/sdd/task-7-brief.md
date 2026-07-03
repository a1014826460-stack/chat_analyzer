# Task 7: Wire Auto Bet Panel into Main Window

**Goal:** Integrate the auto_bet panel, service, and timer into the existing StarTrace main window.

**Files to modify:**
- `app/ui/main_window.py` — add imports, service init, QTimer, signal wiring
- `app/ui/main_window_layout.py` — add panel to left sidebar
- `app/ui/main_window_data.py` — add handler methods, DB resolution hook

**Dependencies:** All previous tasks complete. Current HEAD: `74df3c2`.

## Step-by-step changes

### 1. main_window.py — Add imports (after line 16, before line 17)

After `from app.build_config import ...`, add:
```python
from app.services.auto_bet_service import AutoBetService
from app.ui.auto_bet_panel import AutoBetPanel
```

### 2. main_window.py — Init service (after line 64, `self.summary_check_report_service = ...`)

After `self.summary_check_report_service = SummaryCheckReportService(...)`, add:
```python
        self.auto_bet_service = AutoBetService()
```

### 3. main_window.py — Init QTimer (after line 128, `self._update_download_ready.connect(...)`)

After the update download signal connection, add:
```python
        self._auto_bet_timer = QTimer(self)
        self._auto_bet_timer.setInterval(2000)
        self._auto_bet_timer.timeout.connect(self._on_auto_bet_tick)
```

### 4. main_window_layout.py — Add panel (after line 247, before line 249)

After `self._configure_left_section(block_box)` and before `action_box = QGroupBox("状态")`, insert:
```python

        # --- Auto Bet Panel ---
        self.auto_bet_panel = AutoBetPanel()
        self.auto_bet_panel.setVisible(False)  # hidden until DB is resolved
        left.addWidget(self.auto_bet_panel)
        self._configure_left_section(self.auto_bet_panel)
```

### 5. main_window_data.py — Add import at top of file

The file already imports what's needed. No additional import needed — methods reference `self` attributes set elsewhere.

### 6. main_window_data.py — Add handler methods (at end of MainWindowDataMixin class, line ~737)

Add before the last line of the class:

```python
    # ------------------------------------------------------------------
    # Auto Bet Integration
    # ------------------------------------------------------------------

    def _on_auto_bet_tick(self) -> None:
        """Called by auto_bet timer to evaluate betting strategy."""
        service = getattr(self, "auto_bet_service", None)
        if service is None or not service.is_running:
            return
        active_site = getattr(self, "_active_site", "")
        draw_infos = getattr(self, "_draw_infos", {})
        info = draw_infos.get(active_site) if isinstance(draw_infos, dict) else None
        if info is None:
            return
        current_period = info.current_period or ""
        countdown = info.next_countdown or 0
        service.tick(active_site, countdown, current_period)

    def _on_auto_bet_config_changed(self, config: object) -> None:
        """Save auto bet config to settings."""
        service = getattr(self, "auto_bet_service", None)
        if service is None:
            return
        from app.models.auto_bet import StrategyConfig
        if isinstance(config, StrategyConfig):
            service.apply_config(config)
            self.settings["auto_bet"] = config.to_dict()
            self.settings_service.save(self.settings)

    def _on_auto_bet_start(self) -> None:
        """Start the auto bet engine."""
        service = getattr(self, "auto_bet_service", None)
        if service is None:
            return
        resolved_db = getattr(self, "resolved_db", None)
        if resolved_db is None:
            return
        from app.services.message_injector import MessageInjector
        injector = MessageInjector(resolved_db.msg_db, resolved_db.accid)
        service.set_injector(injector)
        service.start()
        timer = getattr(self, "_auto_bet_timer", None)
        if timer is not None:
            timer.start()

    def _on_auto_bet_stop(self) -> None:
        """Stop the auto bet engine."""
        service = getattr(self, "auto_bet_service", None)
        if service is not None:
            service.stop()
        timer = getattr(self, "_auto_bet_timer", None)
        if timer is not None:
            timer.stop()

    def _connect_auto_bet_panel(self) -> None:
        """Wire auto bet panel signals and load saved config.
        Called after panel is created in layout and DB is resolved."""
        panel = getattr(self, "auto_bet_panel", None)
        if panel is None:
            return

        # Wire signals
        panel.config_changed.connect(self._on_auto_bet_config_changed)
        panel.start_clicked.connect(self._on_auto_bet_start)
        panel.stop_clicked.connect(self._on_auto_bet_stop)
        self.auto_bet_service.set_log_callback(panel.append_log)

        # Populate groups
        groups = []
        if hasattr(self, "group_list"):
            for i in range(self.group_list.count()):
                item = self.group_list.item(i)
                gid = str(item.data(Qt.UserRole) or item.data(32) or "")
                gname = item.text()
                if gname:
                    groups.append((gid or gname, gname))
        panel.set_available_groups(groups)

        # Load saved config
        saved = self.settings.get("auto_bet", {})
        if saved:
            from app.models.auto_bet import StrategyConfig
            cfg = StrategyConfig.from_dict(saved)
            panel.load_config(cfg)
            self.auto_bet_service.apply_config(cfg)

        # Show panel now that DB is resolved
        panel.setVisible(True)
```

### 7. main_window_data.py — Call _connect_auto_bet_panel after DB resolution

In the `_resolve_database` method (around line 165 where `self.resolved_db = resolved`), add after successful resolution:

```python
        # After self.resolved_db = resolved (line ~165):
        self._connect_auto_bet_panel()
```

### 8. main_window.py — Call _connect_auto_bet_panel in __init__ after layout

At the end of `__init__` in main_window.py (around line 178, after `set_proxy_settings(self.settings)`), add:

```python
        # Wire auto bet panel signals (panel created during layout build)
        self._connect_auto_bet_panel()
```

## Testing

After making all changes, verify the module imports:

```bash
.\.venv\Scripts\python.exe -c "
import sys
sys.path.insert(0, '.')
# Just verify imports work — full GUI test requires display
from app.services.auto_bet_service import AutoBetService
from app.ui.auto_bet_panel import AutoBetPanel
from app.services.message_injector import MessageInjector
from app.models.auto_bet import StrategyConfig
print('All imports OK')
"
```

Then launch the app to verify visually:
```bash
.\.venv\Scripts\python.exe app\main.py --admin --debug
```

Checklist:
- [ ] "自动下注" panel appears in left sidebar below "屏蔽名单"
- [ ] Panel starts hidden
- [ ] After resolving DB, panel shows with groups populated
- [ ] Config changes persist across restart
- [ ] Start/Stop buttons toggle correctly
