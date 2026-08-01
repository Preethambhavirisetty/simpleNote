import httpx
import logging
from typing import Any, Dict, TypeVar, Optional

from app.shared.http import TransientHTTPError, is_transient_http_error

# Define type variable for dynamic response types
T = TypeVar('T')

class APIClient:
    def __init__(self, base_url: str, timeout: float = 10.0, client: Optional[httpx.Client] = None):
        self.base_url = base_url
        self.timeout = timeout
        # A shared httpx.Client may be injected for connection pooling across
        # instances; `events` is always per-instance so concurrent requests never
        # read or drain each other's telemetry.
        self._owns_client = client is None
        self.client = client if client is not None else httpx.Client(base_url=base_url, timeout=timeout)
        self.events = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._owns_client:
            self.client.close()
            self.events.append(f"API client connection closed")

    def _handle_error(self, method: str, endpoint: str, exc: httpx.HTTPError, timeout: int) -> None:
        if isinstance(exc, httpx.HTTPStatusError):
            status_code = exc.response.status_code
            self.events.append(f"{method} {endpoint} failed with status {status_code}")
            if is_transient_http_error(exc):
                raise TransientHTTPError(f"{method} {endpoint} failed with transient status {status_code}") from exc
            return

        if isinstance(exc, httpx.TimeoutException):
            self.events.append(f"{method} {endpoint} timed out after {timeout}s.")
        else:
            self.events.append(f"Network error during {method} {endpoint}: {exc}")

        if is_transient_http_error(exc):
            raise TransientHTTPError(f"{method} {endpoint} failed with transient transport error") from exc

    def get(self, endpoint: str, headers: Optional[Dict[str, str]] = None, params: Optional[Dict[str, Any]] = None, timeout: int=10) -> Optional[Any]:
        """A generic GET method that handles errors and returns parsed JSON data."""
        try:
            response = self.client.get(endpoint, headers=headers, params=params, timeout=timeout)
            response.raise_for_status()
            self.events.append(f"GET API call success")
            return response.json()
            
        except httpx.HTTPStatusError as exc:
            self._handle_error("GET", endpoint, exc, timeout)
            return None
        except httpx.TimeoutException as exc:
            self._handle_error("GET", endpoint, exc, timeout)
            return None
        except httpx.RequestError as exc:
            self._handle_error("GET", endpoint, exc, timeout)
            return None

    def post(self, endpoint: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None, timeout: int=10) -> Optional[Any]:
        """A generic POST method that sends a JSON body, handles errors, and returns response JSON."""
        try:
            response = self.client.post(endpoint, json=payload, headers=headers, timeout=timeout)
            response.raise_for_status()
            self.events.append(f"POST API call success")
            return response.json()
            
        except httpx.HTTPStatusError as exc:
            self._handle_error("POST", endpoint, exc, timeout)
            return None
        except httpx.TimeoutException as exc:
            self._handle_error("POST", endpoint, exc, timeout)
            return None
        except httpx.RequestError as exc:
            self._handle_error("POST", endpoint, exc, timeout)
            return None

    def patch(self, endpoint: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None, timeout: int = 10) -> Optional[Any]:
        try:
            response = self.client.patch(endpoint, json=payload, headers=headers, timeout=timeout)
            response.raise_for_status()
            self.events.append("PATCH API call success")
            return response.json()
        except httpx.HTTPStatusError as exc:
            self._handle_error("PATCH", endpoint, exc, timeout)
            return None
        except httpx.TimeoutException as exc:
            self._handle_error("PATCH", endpoint, exc, timeout)
            return None
        except httpx.RequestError as exc:
            self._handle_error("PATCH", endpoint, exc, timeout)
            return None
