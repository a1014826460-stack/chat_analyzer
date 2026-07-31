from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_interface_inventory_covers_routes_and_declares_non_tencent_direct_calls_as_legacy():
    inventory = Path("docs/api-interface-inventory.md").read_text(encoding="utf-8")
    for route in (
        "/v1/auth/session",
        "/v1/runtime-logs",
        "/v1/strategies/auto-bet",
        "/v1/bets/pending",
        "/v1/integrations/wss-credentials",
        "/v1/updates/manifest",
        "/v1/updates/files/{file_name}",
        "/health/ready",
    ):
        assert route in inventory
    for identifier in ("EXCEPTION-TENCENT-IM-001", "EXCEPTION-TENCENT-IM-002", "MIGRATED-001", "MIGRATED-002"):
        assert identifier in inventory


def test_production_client_network_calls_are_centralized_except_tencent_im():
    allowed = {
        Path("app/services/server_api_client.py"),
        Path("app/services/rest_message_sender.py"),
        Path("app/services/ws_message_sender.py"),
    }
    violations = []
    for path in (ROOT / "app").rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        if "urlopen" in source and path.relative_to(ROOT) not in allowed:
            violations.append(path.relative_to(ROOT).as_posix())
    assert violations == []


def test_auto_bet_start_only_delegates_to_the_server_runtime():
    source = (ROOT / "app/ui/main_window_data.py").read_text(encoding="utf-8")
    start = source.index("    def _on_auto_bet_start")
    stop = source.index("    def _on_auto_bet_stop", start)
    body = source[start:stop]

    assert "self._start_server_auto_bet()" in body
    assert "AiBetClient" not in body
    assert "HistoryFetcher" not in body
    assert "service.start()" not in body

    stop_start = source.index("    def _on_auto_bet_stop", stop)
    stop_end = source.index("    def _on_auto_bet_risk_halted", stop_start)
    stop_body = source[stop_start:stop_end]
    assert "service.stop()" not in stop_body
    assert "injector.shutdown()" not in stop_body

    tick_start = source.index("    def _on_auto_bet_tick")
    tick_end = source.index("    def _handle_auto_bet_log_ready", tick_start)
    tick_body = source[tick_start:tick_end]
    assert "service.tick(" not in tick_body


def test_desktop_update_flow_has_no_direct_release_source_fallback():
    main_window = (ROOT / "app/ui/main_window.py").read_text(encoding="utf-8")
    update_service = (ROOT / "app/services/update_service.py").read_text(encoding="utf-8")

    assert "update_manifest_url" not in main_window
    assert "fetch_manifest" not in main_window
    assert "download_and_verify" not in main_window
    assert "urlopen" not in update_service
    assert "update_manifest_url" not in (ROOT / "app/build_config.py").read_text(encoding="utf-8")


def test_local_ai_network_client_is_removed():
    assert not (ROOT / "app/services/ai_bet_client.py").exists()


def test_desktop_strategy_ui_does_not_store_local_ai_credentials():
    panel_source = (ROOT / "app/ui/auto_bet_panel.py").read_text(encoding="utf-8")
    model_source = (ROOT / "app/models/auto_bet.py").read_text(encoding="utf-8")

    for identifier in ("_provider_combo", "_base_url_edit", "_model_edit", "_api_key_edit"):
        assert identifier not in panel_source
    for field_name in ("ai_provider:", "ai_base_url:", "ai_model:", "ai_api_key:"):
        assert field_name not in model_source
