import logging
from typing import Optional

import httpx

from app.core.config import BACKEND_INTERNAL_URL_BASE, AGENT_API_KEY
from app.logger import get_trace_id
from app.shared.api_client import APIClient


log = logging.getLogger(__name__)

TIMEOUT = 10

# One connection pool for all backend calls; httpx.Client is thread-safe. Each
# BackendConversationClient instance keeps its own APIClient (and events) on top,
# so this must never be closed by an instance.
_shared_http: httpx.Client | None = None


def _shared_http_client() -> httpx.Client:
    global _shared_http
    if _shared_http is None:
        _shared_http = httpx.Client(base_url=BACKEND_INTERNAL_URL_BASE, timeout=TIMEOUT)
    return _shared_http


class BackendConversationClient:
    """Backend conversation API wrapper.

    Construct one per request/task: `events` accumulate per instance and are
    drained by the owner, so instances must never be shared across requests.
    """

    def __init__(self):
        self.api_client = APIClient(BACKEND_INTERNAL_URL_BASE, client=_shared_http_client())

    def get_headers(self, user_id):
        headers = {
            "X-Internal-Key": AGENT_API_KEY,
            "X-User-Id": user_id,
            "Content-Type": "application/json",
        }
        trace_id = get_trace_id()
        if trace_id:
            headers["X-Trace-Id"] = trace_id  # propagate the correlation id back to the backend
        return headers

    def get_messages(self, user_id: str, conversation_id: str):
        resp = self.api_client.get(
            f"/{conversation_id}",
            headers=self.get_headers(user_id),
            timeout=TIMEOUT,
        )
        if not resp:
            log.warning("Failed to fetch backend conversation messages", extra={"conversation_id": conversation_id})
            return []
        return (resp.get("data") or {}).get("messages", [])

    def create_conversation(self, user_id: str, title: Optional[str] = None) -> dict:
        resp = self.api_client.post(
            "/",
            {"title": title},
            headers=self.get_headers(user_id),
            timeout=TIMEOUT,
        )
        return self._require_data(resp, "create conversation")

    def create_message(
            self,
            user_id: str,
            conversation_id: str,
            role: str,
            content: str = "",
            status: str = "complete",
            **kwargs,
        ):
        body = {"role": role, "content": content, "status": status, **kwargs}
        resp = self.api_client.post(
            f"/{conversation_id}/messages",
            body,
            headers=self.get_headers(user_id),
            timeout=TIMEOUT,
        )
        return self._require_data(resp, "create message")

    def update_message(
        self,
        user_id: str,
        conversation_id: str,
        message_id: str,
        **fields,
    ) -> dict:
        resp = self.api_client.patch(
            f"/{conversation_id}/messages/{message_id}",
            fields,
            headers=self.get_headers(user_id),
            timeout=TIMEOUT,
        )
        return self._require_data(resp, "update message")

    def drain_events(self) -> list[str]:
        events = list(self.api_client.events)
        self.api_client.events.clear()
        return events

    @staticmethod
    def _require_data(response: Optional[dict], action: str) -> dict:
        if not response:
            raise RuntimeError(f"Backend failed to {action}.")
        data = response.get("data")
        if not isinstance(data, dict):
            raise RuntimeError(f"Backend returned invalid data while trying to {action}.")
        return data
