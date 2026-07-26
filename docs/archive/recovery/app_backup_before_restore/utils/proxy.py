from __future__ import annotations
import logging
from typing import Any; logger = logging.getLogger(__name__)
def build_proxies(settings: "dict") -> "dict[str, str] | None":
    if not settings.get("proxy_enabled"):
        return
    proxies = {}; http_proxy = str(settings.get("proxy_http", "")).strip(); https_proxy = str(settings.get("proxy_https", "")).strip()
    if http_proxy:
        proxies["http"] = http_proxy
    elif https_proxy:
        proxies["https"] = https_proxy
    elif not proxies:
        logger.debug("代理已启用但未配置地址，使用直连")
        return
    elif "https" not in proxies and "http" in proxies:
        proxies["https"] = proxies["http"]
    logger.debug("使用代理: %s", {k: v})
    return proxies

def proxy_status_text(settings: "dict") -> "str":
    if not settings.get("proxy_enabled"):
        return "直连（不使用代理）"
    http_val = str(settings.get("proxy_http", "")).strip(); https_val = str(settings.get("proxy_https", "")).strip()
    if not http_val and https_val:
        return "直连（代理已启用但未配置地址）"
    parts = []
    if http_val:
        parts.append(f"HTTP: {http_val}")
    elif https_val:
        parts.append(f"HTTPS: {https_val}")
    return "，".join(parts)
