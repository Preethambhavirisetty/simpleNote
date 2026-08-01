from __future__ import annotations

import logging
from threading import Lock
from typing import Any

import httpx

from config import DOMAIN_API_BASE, DOMAIN_TIMEOUT
from schemas.catalog import Catalog
from schemas.playbook import PlaybookCandidates, PlaybookMatch


log = logging.getLogger(__name__)

# One connection pool for all domain calls (httpx.Client is thread-safe);
# per-call timeouts are passed on each request.
_http: httpx.Client | None = None

_catalog: Catalog | None = None
_catalog_lock = Lock()


class DomainUnavailableError(RuntimeError):
    """The domain service could not be reached or returned an unusable answer."""


def _http_client() -> httpx.Client:
    global _http
    if _http is None:
        _http = httpx.Client(timeout=DOMAIN_TIMEOUT)
    return _http


def _get(path: str) -> Any:
    return _request("GET", path)


def _post(path: str, payload: dict[str, Any]) -> Any:
    return _request("POST", path, payload)


def _request(method: str, path: str, payload: dict[str, Any] | None = None) -> Any:
    url = f"{DOMAIN_API_BASE.rstrip('/')}{path}"
    try:
        response = _http_client().request(method, url, json=payload)
        response.raise_for_status()
        return response.json()
    except httpx.HTTPStatusError as exc:
        raise DomainUnavailableError(
            f"{method} {url} returned {exc.response.status_code}: "
            f"{exc.response.text[:200]}"
        ) from exc
    except httpx.HTTPError as exc:
        # Name the URL: the usual cause is DOMAIN_API_BASE still pointing at the
        # compose hostname while running outside compose.
        raise DomainUnavailableError(
            f"{method} {url} failed ({exc}). Is agent-domain running, and is "
            f"DOMAIN_API_BASE correct? Currently {DOMAIN_API_BASE!r}."
        ) from exc


def load_catalog(*, refresh: bool = False) -> Catalog:
    """The whole domain in one call, held for the life of the process.

    The catalog is declarative and changes only on deploy, so it is fetched
    once at startup rather than per run. `refresh=True` re-fetches — call it
    from an admin path if the domain is redeployed underneath a live runtime.
    """
    global _catalog

    if _catalog is not None and not refresh:
        return _catalog

    with _catalog_lock:
        if _catalog is None or refresh:
            payload = _get("/api/domain/catalog")
            catalog = Catalog.model_validate(payload)
            log.info(
                "domain catalog loaded",
                extra={
                    "playbooks": len(catalog.playbooks),
                    "operations": len(catalog.operations),
                    "mappings": len(catalog.mappings),
                    "steps": len(catalog.steps),
                },
            )
            _catalog = catalog
        return _catalog


def fetch_candidates(question: str) -> PlaybookCandidates:
    """The playbooks the selector should choose between for this question.

    The domain decides whether that is the whole catalog or a semantic
    shortlist; the runtime does not need to know which.
    """
    payload = _post("/api/domain/playbooks/candidates", {"query": question})
    return PlaybookCandidates.model_validate(payload)


def search_playbooks(question: str, limit: int = 5) -> list[PlaybookMatch]:
    """Raw semantic ranking. Recall-oriented — prefer `fetch_candidates`."""
    payload = _post(
        "/api/domain/playbooks/search", {"query": question, "limit": limit}
    )
    return [PlaybookMatch.model_validate(match) for match in payload]


def close() -> None:
    global _http
    if _http is not None:
        _http.close()
        _http = None
