"""Small synchronous client used by the desktop server-mode integration."""
from __future__ import annotations

import json
from collections.abc import Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class ServerApiError(RuntimeError):
    pass


RequestCallable = Callable[[str, str, dict | None, dict[str, str]], dict]


class ServerApiClient:
    def __init__(self, base_url: str, *, request: RequestCallable | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self._request = request or self._http_request
        self._access_token = ""

    @property
    def is_authenticated(self) -> bool:
        return bool(self._access_token)

    def login_with_local_license(self, machine_code: str, license_token: str) -> None:
        result = self._call("POST", "/v1/auth/session", {
            "machine_code": machine_code,
            "license_token": license_token,
        })
        token = str(result.get("access_token") or "")
        if not token:
            raise ServerApiError("服务器未返回访问令牌")
        self._access_token = token

    def logout(self) -> None:
        if self._access_token:
            self._call("DELETE", "/v1/auth/session", authenticated=True)
        self._access_token = ""

    def get_strategy(self) -> dict:
        return self._call("GET", "/v1/strategies/auto-bet", authenticated=True)

    def save_strategy(self, payload: dict) -> dict:
        return self._call("PUT", "/v1/strategies/auto-bet", payload, authenticated=True)

    def save_wss_credentials(self, appid: str, accid: str, user_sig: str) -> dict:
        return self._call("PUT", "/v1/integrations/wss-credentials", {
            "appid": appid,
            "accid": accid,
            "user_sig": user_sig,
        }, authenticated=True)

    def wss_credentials(self) -> dict:
        return self._call("GET", "/v1/integrations/wss-credentials", authenticated=True)

    def frequency_analysis(self, site: str, *, history_count: int, confidence_threshold: int) -> dict:
        from urllib.parse import urlencode

        query = urlencode({
            "site": site,
            "history_count": int(history_count),
            "confidence_threshold": int(confidence_threshold),
        })
        return self._call("GET", f"/v1/analysis/frequency?{query}", authenticated=True)

    def current_draw(self, site: str) -> dict:
        return self._call("GET", f"/v1/draws/{site}/current", authenticated=True)

    def draw_history(self, site: str, *, limit: int = 50) -> list[dict]:
        safe_limit = min(max(1, int(limit)), 500)
        return list(self._call("GET", f"/v1/draws/{site}/history?limit={safe_limit}", authenticated=True).get("items", []))

    def pending_bets(self) -> list[dict]:
        return list(self._call("GET", "/v1/bets/pending", authenticated=True).get("items", []))

    def betting_statistics(self, site: str, *, ai_window: int = 20, since=None) -> dict:
        from urllib.parse import urlencode

        query_args: dict[str, object] = {"site": str(site), "ai_window": int(ai_window)}
        if since is not None:
            if hasattr(since, "isoformat"):
                query_args["since"] = since.isoformat()
            else:
                query_args["since"] = str(since)
        query = urlencode(query_args)
        return self._call("GET", f"/v1/bets/statistics?{query}", authenticated=True)

    def betting_events(self, *, after_id: int = 0, limit: int = 100, site: str | None = None, since=None) -> list[dict]:
        from urllib.parse import urlencode

        query_args: dict[str, object] = {"after_id": max(0, int(after_id)), "limit": min(max(1, int(limit)), 100)}
        if site:
            query_args["site"] = str(site)
        if since is not None:
            if hasattr(since, "isoformat"):
                query_args["since"] = since.isoformat()
            else:
                query_args["since"] = str(since)
        query = urlencode(query_args)
        return list(self._call("GET", f"/v1/bets/events?{query}", authenticated=True).get("items", []))

    def latest_betting_event_id(self, *, site: str | None = None) -> int:
        from urllib.parse import urlencode

        path = "/v1/bets/events/latest"
        if site:
            path = f"{path}?{urlencode({'site': str(site)})}"
        return int(self._call("GET", path, authenticated=True).get("latest_id", 0) or 0)

    def runtime_logs(
        self,
        *,
        level: str | None = None,
        category: str | None = None,
        keyword: str | None = None,
        start_at=None,
        end_at=None,
        before_id: int | None = None,
        limit: int = 50,
    ) -> dict:
        from urllib.parse import urlencode

        query_args: dict[str, object] = {"limit": min(max(1, int(limit)), 100)}
        for name, value in (("level", level), ("category", category), ("keyword", keyword), ("before_id", before_id)):
            if value not in (None, ""):
                query_args[name] = value
        for name, value in (("start_at", start_at), ("end_at", end_at)):
            if value is not None:
                query_args[name] = value.isoformat() if hasattr(value, "isoformat") else str(value)
        return self._call("GET", f"/v1/runtime-logs?{urlencode(query_args)}", authenticated=True)

    def confirm_bet(self, bet_id: int) -> dict:
        return self._call("POST", f"/v1/bets/{int(bet_id)}/confirm", authenticated=True)

    def skip_bet(self, bet_id: int) -> dict:
        return self._call("POST", f"/v1/bets/{int(bet_id)}/skip", authenticated=True)

    def _call(self, method: str, path: str, payload: dict | None = None, *, authenticated: bool = False) -> dict:
        if authenticated and not self._access_token:
            raise ServerApiError("服务器模式未登录")
        headers = {"Accept": "application/json"}
        if authenticated:
            headers["Authorization"] = f"Bearer {self._access_token}"
        try:
            return self._request(method, path, payload, headers)
        except HTTPError as exc:
            if exc.code == 401:
                self._access_token = ""
            try:
                detail = json.loads(exc.read().decode("utf-8")).get("detail", "")
            except Exception:
                detail = ""
            raise ServerApiError(f"服务器请求失败 ({exc.code}): {detail}") from exc
        except URLError as exc:
            raise ServerApiError(f"无法连接服务器: {exc.reason}") from exc

    def _http_request(self, method: str, path: str, payload: dict | None, headers: dict[str, str]) -> dict:
        body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request_headers = dict(headers)
        if body is not None:
            request_headers["Content-Type"] = "application/json"
        request = Request(f"{self.base_url}{path}", data=body, headers=request_headers, method=method)
        with urlopen(request, timeout=10) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw) if raw else {}

