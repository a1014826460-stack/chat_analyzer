from __future__ import annotations

import logging


def test_debug_mode_suppresses_noisy_group_realtime_loggers():
    from app.utils.logging_config import configure

    configure(debug=True)

    assert logging.getLogger("app.services.chat_service").getEffectiveLevel() >= logging.INFO
    assert logging.getLogger("app.services.ws_message_sender").getEffectiveLevel() >= logging.INFO
    assert logging.getLogger("app.ui.main_window_data").getEffectiveLevel() <= logging.DEBUG


def test_debug_mode_suppresses_additional_ui_noise_loggers():
    from app.utils.logging_config import configure

    configure(debug=True)

    assert logging.getLogger("app.ui.chart_window").getEffectiveLevel() >= logging.INFO
    assert logging.getLogger("app.ui.main_window_realtime").getEffectiveLevel() >= logging.ERROR
    assert logging.getLogger("app.services.settings_service").getEffectiveLevel() >= logging.INFO
    assert logging.getLogger("app.services.storage_service").getEffectiveLevel() >= logging.INFO


def test_rate_limit_filter_suppresses_duplicate_messages_within_window():
    from app.utils.logging_config import RateLimitFilter

    filter_ = RateLimitFilter(interval_seconds=30, key_prefixes=("Skip auto message refresh",))
    record1 = logging.LogRecord("app.ui.main_window_data", logging.DEBUG, __file__, 1, "Skip auto message refresh; site=%s", ("pc28",), None)
    record2 = logging.LogRecord("app.ui.main_window_data", logging.DEBUG, __file__, 1, "Skip auto message refresh; site=%s", ("pc28",), None)

    assert filter_.filter(record1) is True
    assert filter_.filter(record2) is False
