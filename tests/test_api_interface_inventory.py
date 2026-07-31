from pathlib import Path


def test_interface_inventory_covers_routes_and_declares_non_tencent_direct_calls_as_legacy():
    inventory = Path("docs/api-interface-inventory.md").read_text(encoding="utf-8")
    for route in (
        "/v1/auth/session",
        "/v1/runtime-logs",
        "/v1/strategies/auto-bet",
        "/v1/bets/pending",
        "/v1/integrations/wss-credentials",
        "/health/ready",
    ):
        assert route in inventory
    for identifier in ("EXCEPTION-TENCENT-IM-001", "EXCEPTION-TENCENT-IM-002", "LEGACY-001", "LEGACY-002"):
        assert identifier in inventory
