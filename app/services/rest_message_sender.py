from __future__ import annotations

import json
import logging
import random
import time
import urllib.parse
import urllib.request
from pathlib import Path

from app.services.local_message_verifier import capture_message_cursor, local_message_exists


logger = logging.getLogger(__name__)


def _random() -> int:
    return random.randint(1, 2_147_483_647)


class RestGroupMessageSender:
    """Send Tencent Cloud IM group messages via REST API without SDK login."""

    def __init__(
        self,
        sdk_app_id: int | str,
        identifier: str,
        user_sig: str,
        *,
        from_account: str = "",
        endpoint: str = "https://adminapisgp.im.qcloud.com",
        timeout: int = 10,
        msg_db_path: str | Path | None = None,
        verify_timeout_sec: float = 3.0,
        verify_poll_interval_sec: float = 0.2,
    ) -> None:
        self._sdk_app_id = int(sdk_app_id)
        self._identifier = str(identifier).strip()
        self._user_sig = str(user_sig).strip()
        self._from_account = str(from_account or "").strip()
        self._endpoint = endpoint.rstrip("/")
        self._timeout = timeout
        self._msg_db_path = Path(msg_db_path) if msg_db_path is not None else None
        self._verify_timeout_sec = max(float(verify_timeout_sec), 0.0)
        self._verify_poll_interval_sec = max(float(verify_poll_interval_sec), 0.01)
        self._running = bool(self._sdk_app_id and self._identifier and self._user_sig)

    def startup(self) -> bool:
        return self._running

    def shutdown(self) -> None:
        self._running = False

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def endpoint(self) -> str:
        return self._endpoint

    def inject_bet(self, group_id: str, play_type: str, amount: float) -> bool:
        return self.inject_text(group_id, f"{play_type} {self._fmt_amount(amount)}")

    def inject_text(self, target_id: str, text: str, *, is_group: bool = True) -> bool:
        if not is_group:
            logger.error("REST sender currently supports group messages only")
            return False
        if not self._running:
            logger.error("REST sender is not configured")
            return False
        cursor = capture_message_cursor(self._msg_db_path, target_id)
        random_value = _random()
        body: dict[str, object] = {
            "GroupId": str(target_id),
            "Random": random_value,
            "MsgBody": [
                {"MsgType": "TIMTextElem", "MsgContent": {"Text": str(text)}}
            ],
        }
        if self._from_account:
            body["From_Account"] = self._from_account
        url = self._build_url(random_value)
        request = urllib.request.Request(
            url,
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                payload = json.loads(response.read().decode("utf-8", errors="replace"))
        except Exception as exc:
            logger.error("REST group message send failed: %s", exc)
            return False
        if not isinstance(payload, dict) or int(payload.get("ErrorCode", -1)) != 0:
            logger.error("REST group message rejected: %s", payload)
            return False
        return self.verify_local_message(target_id, text, after_cursor=cursor)

    def verify_local_message(
        self,
        target_id: str,
        text: str,
        *,
        after_cursor: tuple[int, int, int] | None = None,
    ) -> bool:
        """Verify that the sent group text appears in local msg_0.db."""
        if self._msg_db_path is None:
            return True

        deadline = time.monotonic() + self._verify_timeout_sec
        while True:
            if self._message_exists(target_id, text, after_cursor=after_cursor):
                return True
            if time.monotonic() >= deadline:
                logger.error(
                    "REST sent but local msg_0.db verification failed: group=%s text=%s",
                    target_id,
                    text,
                )
                return False
            time.sleep(self._verify_poll_interval_sec)

    def _message_exists(
        self,
        target_id: str,
        text: str,
        *,
        after_cursor: tuple[int, int, int] | None = None,
    ) -> bool:
        return local_message_exists(self._msg_db_path, target_id, text, after_cursor=after_cursor)

    def _build_url(self, random_value: int) -> str:
        query = urllib.parse.urlencode(
            {
                "sdkappid": str(self._sdk_app_id),
                "identifier": self._identifier,
                "usersig": self._user_sig,
                "random": str(random_value),
                "contenttype": "json",
            }
        )
        return f"{self._endpoint}/v4/group_open_http_svc/send_group_msg?{query}"

    @staticmethod
    def _fmt_amount(value: float) -> str:
        if value == int(value):
            return str(int(value))
        return f"{value:.2f}"
