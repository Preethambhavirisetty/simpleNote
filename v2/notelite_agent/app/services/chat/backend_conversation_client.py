import logging
from typing import Optional

from app.core.config import BACKEND_INTERNAL_URL_BASE, AGENT_API_KEY
from app.shared.api_client import APIClient


log = logging.getLogger(__name__)

TIMEOUT = 10


class BackendConversationClient:
    def __init__(self):
        self.api_client = APIClient(BACKEND_INTERNAL_URL_BASE)

    def get_headers(self, user_id):
        return {
            "X-Internal-Key": AGENT_API_KEY,
            "X-User-Id": user_id,
            "Content-Type": "application/json",
        }

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
        events = self.api_client.events
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
