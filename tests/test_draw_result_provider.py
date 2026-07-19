from __future__ import annotations

from datetime import datetime
from pathlib import Path

from app.models.auto_bet import DrawResult, StrategyConfig
from app.services.auto_bet_service import AutoBetService
from app.services.draw_result_store import DrawResultStore
from app.services.history_fetchers import HistoryFetcher, normalize_result_label


def test_auto_bet_tick_uses_next_period_as_the_betting_target():
    from types import SimpleNamespace

    from app.models import DrawInfo
    from app.models.auto_bet import AutoBetRuntimeState, StrategyConfig
    from app.ui.main_window_data import MainWindowDataMixin

    calls = []
    service = SimpleNamespace(
        is_running=True,
        runtime_state=AutoBetRuntimeState(),
        config=StrategyConfig(site="pc28"),
        tick=lambda *args, **kwargs: calls.append((args, kwargs)),
    )
    window = SimpleNamespace(
        auto_bet_service=service,
        auto_bet_panel=None,
        _active_site="pc28",
        _draw_infos={
            "pc28": DrawInfo(current_period="3458210", next_period="3458211", next_countdown=120)
        },
    )

    MainWindowDataMixin._on_auto_bet_tick(window)

    assert calls[0][0][2] == "3458211"


class FakeFetcher:
    def __init__(self, results: list[DrawResult] | None = None) -> None:
        self.results = results or []
        self.calls: list[tuple[str, int]] = []

    def fetch(self, site: str, count: int) -> list[DrawResult]:
        self.calls.append((site, count))
        return list(self.results[:count])


def test_normalize_result_label_uses_site_thresholds_and_parity():
    assert normalize_result_label("pc28", 13) == "小单"
    assert normalize_result_label("pc28", 14) == "大双"
    assert normalize_result_label("macao", 24) == "小双"
    assert normalize_result_label("macao", 25) == "大单"
    assert normalize_result_label("australia", 18) == "小双"
    assert normalize_result_label("australia", 19) == "大单"
    assert normalize_result_label("norway", 13) == "小单"
    assert normalize_result_label("norway", 14) == "大双"
    assert normalize_result_label("pc28", "大") == "大"


def test_history_fetcher_converts_normalized_history_records_to_draw_results(monkeypatch):
    def fake_fetch_history_records(site: str, page: int = 1, page_size: int = 20):
        assert site == "pc28"
        assert page == 1
        assert page_size == 3
        return [
            {"site": "pc28", "period": "1001", "open_time": datetime(2026, 7, 4, 1), "sum": 13},
            {"site": "pc28", "period": "1002", "open_time": datetime(2026, 7, 4, 2), "sum": 14},
            {"site": "pc28", "period": "1003", "open_time": None, "sum": None},
        ]

    monkeypatch.setattr("app.services.history_fetchers.fetch_history_records", fake_fetch_history_records)

    results = HistoryFetcher().fetch("pc28", count=3)

    assert results == [
        DrawResult(site="pc28", period="1001", result="小单", open_time=datetime(2026, 7, 4, 1)),
        DrawResult(site="pc28", period="1002", result="大双", open_time=datetime(2026, 7, 4, 2)),
    ]


def test_draw_result_store_persists_and_returns_recent_results_oldest_first(tmp_path: Path):
    store = DrawResultStore(tmp_path / "draw_results.db", fetcher=FakeFetcher([]))
    inserted = store.insert_results(
        "pc28",
        [
            DrawResult(site="pc28", period="2026001", result="大单", open_time=datetime(2026, 7, 4, 1)),
            DrawResult(site="pc28", period="2026002", result="小双", open_time=datetime(2026, 7, 4, 2)),
            DrawResult(site="pc28", period="2026003", result="大双", open_time=datetime(2026, 7, 4, 3)),
        ],
    )

    assert inserted == 3
    recent = store.get_recent_results("pc28", 2)
    assert [item.period for item in recent] == ["2026002", "2026003"]
    assert [item.result for item in recent] == ["小双", "大双"]
    assert recent[0].open_time == datetime(2026, 7, 4, 2)

    one = store.get_result("pc28", "2026001")
    assert one == DrawResult(site="pc28", period="2026001", result="大单", open_time=datetime(2026, 7, 4, 1))
    assert store.get_result("pc28", "missing") is None


def test_draw_result_store_ensure_data_fetches_once_per_site(tmp_path: Path):
    fake = FakeFetcher(
        [DrawResult(site="pc28", period=str(1000 + i), result="大单") for i in range(25)]
    )
    store = DrawResultStore(tmp_path / "draw_results.db", fetcher=fake)

    store.ensure_data("pc28", min_count=20)
    store.ensure_data("pc28", min_count=20)

    assert fake.calls == [("pc28", 20)]
    assert len(store.get_recent_results("pc28", 25)) == 20


def test_draw_result_store_explicit_refresh_fetches_even_when_cache_is_already_ensured(tmp_path: Path):
    fake = FakeFetcher([DrawResult(site="pc28", period="1001", result="大单")])
    store = DrawResultStore(tmp_path / "draw_results.db", fetcher=fake)
    store.ensure_data("pc28", min_count=20)
    fake.results = [DrawResult(site="pc28", period="1002", result="小双")]

    refreshed = store.refresh_recent_results("pc28", count=50)

    assert fake.calls == [("pc28", 20), ("pc28", 50)]
    assert refreshed == 1
    assert store.get_result("pc28", "1002") == DrawResult(site="pc28", period="1002", result="小双")


def test_draw_result_store_refresh_keeps_local_cache_when_remote_fetch_fails(tmp_path: Path):
    class FailingFetcher(FakeFetcher):
        def fetch(self, site: str, count: int) -> list[DrawResult]:
            raise RuntimeError("network down")

    store = DrawResultStore(tmp_path / "draw_results.db", fetcher=FailingFetcher())
    store.insert_results("pc28", [DrawResult(site="pc28", period="1001", result="大单")])

    assert store.refresh_recent_results("pc28", 50) == 0
    assert store.get_result("pc28", "1001") is not None


def test_auto_bet_opposite_play_handles_composite_labels():
    plays = ["大双", "小单", "大单", "小双"]
    assert AutoBetService._opposite_play("大双", plays) == "小单"
    assert AutoBetService._opposite_play("小单", plays) == "大双"
    assert AutoBetService._opposite_play("大单", plays) == "小双"
    assert AutoBetService._opposite_play("小双", plays) == "大单"
    assert AutoBetService._opposite_play("大", ["大", "小"]) == "小"
    assert AutoBetService._opposite_play("小", ["大", "小"]) == "大"
    assert AutoBetService._opposite_play("大双", ["大", "小"]) == "大"


def test_auto_bet_analyze_can_make_decision_from_store_data(tmp_path: Path):
    store = DrawResultStore(tmp_path / "draw_results.db", fetcher=FakeFetcher([]))
    store.insert_results(
        "pc28",
        [
            DrawResult(site="pc28", period="1", result="大双"),
            DrawResult(site="pc28", period="2", result="大双"),
            DrawResult(site="pc28", period="3", result="大双"),
        ],
    )
    cfg = StrategyConfig(
        site="pc28",
        observation_window=3,
        trigger_threshold=3,
        bet_amount=12.5,
        target_groups=["group-1"],
        play_types=["大双", "小单"],
    )

    decision = AutoBetService()._analyze(cfg, store)

    assert decision.should_bet is True
    assert decision.play_type == "小单"
    assert decision.amount == 12.5
    assert decision.group_id == "group-1"


def test_auto_bet_start_creates_and_injects_draw_result_store(monkeypatch, tmp_path: Path):
    import json
    import sys
    import types

    from app.models.auto_bet import StrategyConfig
    if "PySide6" not in sys.modules:
        qtcore = types.ModuleType("PySide6.QtCore")
        qtwidgets = types.ModuleType("PySide6.QtWidgets")

        class FakeQDateTime:
            @classmethod
            def currentDateTime(cls):
                return cls()

            @classmethod
            def fromString(cls, *args, **kwargs):
                return cls()

            def isValid(self):
                return False

            def addDays(self, days):
                return self

        class FakeQt:
            UserRole = 256
            Checked = 2
            ISODate = 1

        qtcore.QDateTime = FakeQDateTime
        qtcore.Qt = FakeQt
        qtwidgets.QFileDialog = object
        qtwidgets.QListWidgetItem = object
        qtwidgets.QMessageBox = object
        pyside = types.ModuleType("PySide6")
        pyside.QtCore = qtcore
        pyside.QtWidgets = qtwidgets
        monkeypatch.setitem(sys.modules, "PySide6", pyside)
        monkeypatch.setitem(sys.modules, "PySide6.QtCore", qtcore)
        monkeypatch.setitem(sys.modules, "PySide6.QtWidgets", qtwidgets)

    from app.ui.main_window_data import MainWindowDataMixin
    import app.services.account_resolver as account_resolver
    import app.services.background_window_sender as background_window_sender
    import app.services.message_injector as message_injector
    import app.services.ws_message_sender as ws_message_sender
    import app.services.draw_result_store as draw_result_store
    import app.services.ai_prediction_store as ai_prediction_store
    import app.services.history_fetchers as history_fetchers
    import app.utils.pathing as pathing

    prefs_path = tmp_path / "shared_preferences.json"
    prefs_path.write_text(
        json.dumps(
            {
                "flutter.AccountManager_AccountList": [
                    json.dumps({"loginResultEntity": {"accid": "acc-1", "token": "sig-1"}})
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(account_resolver, "DEFAULT_SHARED_PREFS", prefs_path)
    monkeypatch.setattr(pathing, "user_data_dir", lambda: tmp_path)

    class ForbiddenInjector:
        def __init__(self, *args, **kwargs):
            raise AssertionError("MessageInjector/TIMLogin must not be used for auto betting")

    class FakeWsSender:
        instances = []

        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs
            self.started = False
            FakeWsSender.instances.append(self)

        def startup(self):
            self.started = True
            return True

        def shutdown(self):
            self.started = False

    class FakeBackgroundSender:
        instances = []

        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.started = False
            FakeBackgroundSender.instances.append(self)

        def startup(self):
            self.started = True
            return True

        def shutdown(self):
            self.started = False

    class FakeFetcher:
        pass

    class FakeStore:
        instances = []

        def __init__(self, db_path, fetcher):
            self.db_path = Path(db_path)
            self.fetcher = fetcher
            self.ensure_calls = []
            FakeStore.instances.append(self)

        def ensure_data(self, site, min_count=20):
            self.ensure_calls.append((site, min_count))

    class FakePredictionStore:
        instances = []

        def __init__(self, db_path):
            self.db_path = Path(db_path)
            FakePredictionStore.instances.append(self)

    monkeypatch.setattr(message_injector, "MessageInjector", ForbiddenInjector)
    monkeypatch.setattr(ws_message_sender, "WsMessageSender", FakeWsSender)
    monkeypatch.setattr(background_window_sender, "BackgroundWindowMessageSender", FakeBackgroundSender)
    monkeypatch.setattr(history_fetchers, "HistoryFetcher", FakeFetcher)
    monkeypatch.setattr(draw_result_store, "DrawResultStore", FakeStore)
    monkeypatch.setattr(ai_prediction_store, "AiPredictionStore", FakePredictionStore)

    class FakeService:
        def __init__(self):
            self.config = StrategyConfig(
                strategy_type="flat",
                site="pc28",
                target_groups=["g1"],
                observation_window=10,
                ai_base_url="https://ai.example",
                ai_model="model",
                ai_api_key="key",
            )
            self.injector = None
            self.provider = None
            self.ai_client = None
            self.prediction_store = None
            self.started = False

        def set_injector(self, injector):
            self.injector = injector

        def set_result_provider(self, provider):
            self.provider = provider

        def set_ai_client(self, client):
            self.ai_client = client

        def set_ai_prediction_store(self, store):
            self.prediction_store = store

        def start(self):
            self.started = True

    class FakePanel:
        def set_running(self, value):
            self.running = value

    class FakeTimer:
        def __init__(self):
            self.started = False

        def start(self):
            self.started = True

    class FakeWindow(MainWindowDataMixin):
        pass

    win = FakeWindow()
    win.auto_bet_service = FakeService()
    win.resolved_db = type("Resolved", (), {
        "accid": "acc-1",
        "im_appid": "123456",
        "msg_db": tmp_path / "msg_0.db",
    })()
    win.auto_bet_panel = FakePanel()
    win._auto_bet_timer = FakeTimer()

    win._on_auto_bet_start()

    assert win.auto_bet_service.started is True
    assert len(FakeWsSender.instances) == 1
    sender = FakeWsSender.instances[0]
    assert sender.started is True
    assert sender.args == ("123456", "acc-1", "sig-1")
    assert win.auto_bet_service.injector is sender
    assert FakeBackgroundSender.instances == []
    assert len(FakeStore.instances) == 1
    store = FakeStore.instances[0]
    assert store.db_path == tmp_path / "draw_results.db"
    assert isinstance(store.fetcher, FakeFetcher)
    assert store.ensure_calls == [("pc28", 50)]
    assert win.auto_bet_service.provider is store
    assert len(FakePredictionStore.instances) == 1
    assert FakePredictionStore.instances[0].db_path == tmp_path / "ai_predictions.db"
    assert win.auto_bet_service.prediction_store is FakePredictionStore.instances[0]
    from app.services.ai_bet_client import AiBetClient
    assert isinstance(win.auto_bet_service.ai_client, AiBetClient)
    assert win._auto_bet_timer.started is True


def test_auto_bet_start_falls_back_to_background_sender_when_wss_startup_fails(monkeypatch, tmp_path: Path):
    import json
    import sys
    import types

    from app.models.auto_bet import StrategyConfig
    if "PySide6" not in sys.modules:
        qtcore = types.ModuleType("PySide6.QtCore")
        qtwidgets = types.ModuleType("PySide6.QtWidgets")

        class FakeQDateTime:
            @classmethod
            def currentDateTime(cls):
                return cls()

            @classmethod
            def fromString(cls, *args, **kwargs):
                return cls()

            def isValid(self):
                return False

            def addDays(self, days):
                return self

        class FakeQt:
            UserRole = 256
            Checked = 2
            ISODate = 1

        qtcore.QDateTime = FakeQDateTime
        qtcore.Qt = FakeQt
        qtwidgets.QFileDialog = object
        qtwidgets.QListWidgetItem = object
        qtwidgets.QMessageBox = object
        pyside = types.ModuleType("PySide6")
        pyside.QtCore = qtcore
        pyside.QtWidgets = qtwidgets
        monkeypatch.setitem(sys.modules, "PySide6", pyside)
        monkeypatch.setitem(sys.modules, "PySide6.QtCore", qtcore)
        monkeypatch.setitem(sys.modules, "PySide6.QtWidgets", qtwidgets)

    from app.ui.main_window_data import MainWindowDataMixin
    import app.services.account_resolver as account_resolver
    import app.services.background_window_sender as background_window_sender
    import app.services.uia_wuquan_sender as uia_wuquan_sender
    import app.services.ws_message_sender as ws_message_sender
    import app.services.draw_result_store as draw_result_store
    import app.services.history_fetchers as history_fetchers
    import app.utils.pathing as pathing

    prefs_path = tmp_path / "shared_preferences.json"
    prefs_path.write_text(
        json.dumps(
            {
                "flutter.AccountManager_AccountList": [
                    json.dumps({"loginResultEntity": {"accid": "acc-1", "token": "sig-1"}})
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(account_resolver, "DEFAULT_SHARED_PREFS", prefs_path)
    monkeypatch.setattr(pathing, "user_data_dir", lambda: tmp_path)

    class FakeWsSender:
        instances = []

        def __init__(self, *args, **kwargs):
            FakeWsSender.instances.append(self)

        def startup(self):
            return False

    class FakeUiaSender:
        def __init__(self, **kwargs):
            pass

        def startup(self):
            return False

    class FakeBackgroundSender:
        instances = []

        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.started = False
            FakeBackgroundSender.instances.append(self)

        def startup(self):
            self.started = True
            return True

    class FakeFetcher:
        pass

    class FakeStore:
        def __init__(self, db_path, fetcher):
            pass

        def ensure_data(self, site, min_count=20):
            pass

    monkeypatch.setattr(ws_message_sender, "WsMessageSender", FakeWsSender)
    monkeypatch.setattr(uia_wuquan_sender, "UiaWuQuanMessageSender", FakeUiaSender)
    monkeypatch.setattr(background_window_sender, "BackgroundWindowMessageSender", FakeBackgroundSender)
    monkeypatch.setattr(history_fetchers, "HistoryFetcher", FakeFetcher)
    monkeypatch.setattr(draw_result_store, "DrawResultStore", FakeStore)

    class FakeService:
        def __init__(self):
            self.config = StrategyConfig(
                site="pc28",
                target_groups=["g1"],
                observation_window=10,
                ai_base_url="https://ai.example",
                ai_model="model",
                ai_api_key="key",
            )
            self.injector = None
            self.started = False

        def set_injector(self, injector):
            self.injector = injector

        def set_result_provider(self, provider):
            self.provider = provider

        def start(self):
            self.started = True

    class FakeWindow(MainWindowDataMixin):
        pass

    win = FakeWindow()
    win.auto_bet_service = FakeService()
    win.resolved_db = type("Resolved", (), {
        "accid": "acc-1",
        "im_appid": "123456",
        "msg_db": tmp_path / "msg_0.db",
    })()
    win.auto_bet_panel = type("Panel", (), {"set_running": lambda self, value: None})()
    win._auto_bet_timer = type("Timer", (), {"start": lambda self: None})()

    win._on_auto_bet_start()

    assert len(FakeWsSender.instances) == 1
    assert len(FakeBackgroundSender.instances) == 1
    assert FakeBackgroundSender.instances[0].started is True
    assert win.auto_bet_service.injector is FakeBackgroundSender.instances[0]
    assert win.auto_bet_service.started is True


def test_auto_bet_start_rejects_missing_ai_configuration_before_creating_a_sender(monkeypatch, tmp_path: Path):
    from app.ui.main_window_data import MainWindowDataMixin
    import app.ui.main_window_data as main_window_data

    monkeypatch.setattr(
        main_window_data,
        "QMessageBox",
        type("MessageBox", (), {"warning": staticmethod(lambda _parent, _title, message: messages.append(message))}),
    )

    class FakeService:
        def __init__(self):
            self.config = StrategyConfig(site="pc28", target_groups=["g1"], ai_base_url="", ai_model="", ai_api_key="")
            self.started = False

        def start(self):
            self.started = True

    class FakePanel:
        def __init__(self):
            self.running = True

        def set_running(self, value):
            self.running = value

    messages: list[str] = []
    window = type("Window", (MainWindowDataMixin,), {})()
    window.auto_bet_service = FakeService()
    window.auto_bet_panel = FakePanel()

    window._on_auto_bet_start()

    assert window.auto_bet_service.started is False
    assert window.auto_bet_panel.running is False
    assert messages == ["Base URL\n模型\nAPI Key"]


def test_auto_bet_start_rejects_missing_target_group_before_creating_a_sender(monkeypatch):
    from app.ui.main_window_data import MainWindowDataMixin
    import app.ui.main_window_data as main_window_data

    class FakeService:
        def __init__(self):
            self.config = StrategyConfig(target_groups=[], ai_api_key="key")
            self.started = False

        def start(self):
            self.started = True

    class FakePanel:
        def __init__(self):
            self.running = True

        def set_running(self, value):
            self.running = value

    messages: list[str] = []
    monkeypatch.setattr(
        main_window_data,
        "QMessageBox",
        type("MessageBox", (), {"warning": staticmethod(lambda _parent, _title, message: messages.append(message))}),
    )
    window = type("Window", (MainWindowDataMixin,), {})()
    window.auto_bet_service = FakeService()
    window.auto_bet_panel = FakePanel()

    window._on_auto_bet_start()

    assert window.auto_bet_service.started is False
    assert window.auto_bet_panel.running is False
    assert messages == ["请至少选择一个目标群组"]


def test_refresh_auto_bet_groups_removes_missing_saved_target_groups():
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QListWidget, QListWidgetItem
    from app.models.auto_bet import StrategyConfig
    from app.services.auto_bet_service import AutoBetService
    from app.ui.auto_bet_panel import AutoBetPanel
    from app.ui.main_window_data import MainWindowDataMixin

    app = QApplication.instance() or QApplication([])
    window = type("Window", (MainWindowDataMixin,), {})()
    window.auto_bet_panel = AutoBetPanel()
    window.auto_bet_panel.load_config(StrategyConfig(target_groups=["gone", "g1"]))
    window.auto_bet_service = AutoBetService()
    window.settings = {}
    window.settings_service = type("Settings", (), {"save": lambda _self, _settings: None})()
    window.group_list = QListWidget()
    item = QListWidgetItem("群一")
    item.setData(Qt.UserRole, "g1")
    window.group_list.addItem(item)

    window._refresh_auto_bet_groups()

    assert window.auto_bet_panel.get_config().target_groups == ["g1"]
    assert window.auto_bet_service.config.target_groups == ["g1"]
    assert window.settings["auto_bet"]["target_groups"] == ["g1"]
