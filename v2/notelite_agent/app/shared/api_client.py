import httpx
import logging
from typing import Any, Dict, TypeVar, Optional

# Define type variable for dynamic response types
T = TypeVar('T')

class APIClient:
    def __init__(self, base_url: str, timeout: float = 10.0):
        self.base_url = base_url
        self.timeout = timeout
        # Using a client instance handles connection pooling automatically
        self.client = httpx.Client(base_url=base_url, timeout=timeout)
        self.events = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.client.close()
        self.events.append(f"API client connection closed")

    def get(self, endpoint: str, headers: Optional[Dict[str, str]] = None, params: Optional[Dict[str, Any]] = None, timeout: int=10) -> Optional[Any]:
        """A generic GET method that handles errors and returns parsed JSON data."""
        try:
            response = self.client.get(endpoint, headers=headers, params=params, timeout=timeout)
            response.raise_for_status()
            self.events.append(f"GET API call success")
            return response.json()
            
        except httpx.HTTPStatusError as exc:
            self.events.append(f"GET {endpoint} failed with status")
            return None
        except httpx.TimeoutException:
            self.events.append(f"GET {endpoint} timed out after {self.timeout}s.")
            return None
        except httpx.RequestError as exc:
            self.events.append(f"Network error during GET {endpoint}: {exc}")
            return None

    def post(self, endpoint: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None, timeout: int=10) -> Optional[Any]:
        """A generic POST method that sends a JSON body, handles errors, and returns response JSON."""
        try:
            response = self.client.post(endpoint, json=payload, headers=headers, timeout=timeout)
            response.raise_for_status()
            self.events.append(f"POST API call success")
            return response.json()
            
        except httpx.HTTPStatusError as exc:
            self.events.append(f"POST {endpoint} failed with status")
            return None
        except httpx.TimeoutException:
            self.events.append(f"POST {endpoint} timed out after {self.timeout}s.")
            return None
        except httpx.RequestError as exc:
            self.events.append(f"Network error during POST {endpoint}: {exc}")
            return None

    def patch(self, endpoint: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None, timeout: int = 10) -> Optional[Any]:
        try:
            response = self.client.patch(endpoint, json=payload, headers=headers, timeout=timeout)
            response.raise_for_status()
            self.events.append("PATCH API call success")
            return response.json()
        except httpx.HTTPStatusError as exc:
            self.events.append(f"PATCH {endpoint} failed with status {exc.response.status_code}")
            return None
        except httpx.TimeoutException:
            self.events.append(f"PATCH {endpoint} timed out after {timeout}s.")
            return None
        except httpx.RequestError as exc:
            self.events.append(f"Network error during PATCH {endpoint}: {exc}")
            return None
