from __future__ import annotations

import logging


logger = logging.getLogger(__name__)


def build_proxies(settings: dict) -> dict[str, str] | None:
    if not settings.get("proxy_enabled"):
        return None

    http_proxy = str(settings.get("proxy_http", "")).strip()
    https_proxy = str(settings.get("proxy_https", "")).strip()
    proxies: dict[str, str] = {}
    if http_proxy:
        proxies["http"] = http_proxy
    if https_proxy:
        proxies["https"] = https_proxy
    elif http_proxy:
        proxies["https"] = http_proxy

    if not proxies:
        logger.debug("Proxy is enabled but no address is configured.")
        return None
    return proxies


def proxy_status_text(settings: dict) -> str:
    if not settings.get("proxy_enabled"):
        return "Direct connection"
    proxies = build_proxies(settings)
    if not proxies:
        return "Proxy enabled, but no address configured"
    return " | ".join(f"{name.upper()}: {value}" for name, value in proxies.items())
