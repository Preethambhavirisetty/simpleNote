from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from json import JSONDecodeError
from typing import Callable, Sequence

import tiktoken

from app.core.config import LLM_SUMMARIZER_MODEL

from app.shared.llm import llm_call_general
from app.shared.utils import build_llm_messages, count_tokens


log = logging.getLogger(__name__)

_token_encoder = tiktoken.get_encoding("cl100k_base")


@dataclass(frozen=True)
class KeywordBatchItem:
    chunk_id: str
    chunk_type: str
    text: str
    truncated: bool = False


@dataclass(frozen=True)
class KeywordBatchResult:
    keywords_by_chunk: dict[str, list[str]]
    api_calls: int
    retries: int
    events: list[str] = field(default_factory=list)


def build_keyword_batches(
    items: Sequence[KeywordBatchItem],
    *,
    max_chunks: int,
    max_tokens: int,
) -> list[list[KeywordBatchItem]]:
    """Group prepared items under both chunk-count and input-token limits."""
    max_chunks = max(1, max_chunks)
    max_tokens = max(1, max_tokens)
    batches: list[list[KeywordBatchItem]] = []
    current: list[KeywordBatchItem] = []
    current_tokens = 0

    for item in items:
        prepared = _truncate_item(item, max_tokens)
        item_tokens = count_tokens(prepared.text)
        if current and (len(current) >= max_chunks or current_tokens + item_tokens > max_tokens):
            batches.append(current)
            current = []
            current_tokens = 0
        current.append(prepared)
        current_tokens += item_tokens

    if current:
        batches.append(current)
    return batches


def extract_keywords_batched(
    items: Sequence[KeywordBatchItem],
    *,
    system_prompt: str,
    max_chunks: int,
    max_tokens: int,
    concurrency: int,
    keywords_per_chunk: int,
    llm_call: Callable = llm_call_general,
) -> KeywordBatchResult:
    """Extract per-chunk keywords with token-budgeted, retryable LLM batches."""
    batches = build_keyword_batches(items, max_chunks=max_chunks, max_tokens=max_tokens)
    events = [f"keyword extraction batches prepared: {len(batches)}"]
    for item in (item for batch in batches for item in batch if item.truncated):
        events.append(f"keyword extraction truncated: chunk={item.chunk_id}")

    results: dict[str, list[str]] = {item.chunk_id: [] for item in items}
    api_calls = 0
    retries = 0

    def run(index: int, batch: list[KeywordBatchItem]):
        return _extract_batch(
            index,
            batch,
            system_prompt=system_prompt,
            keywords_per_chunk=keywords_per_chunk,
            llm_call=llm_call,
        )

    if concurrency <= 1 or len(batches) <= 1:
        completed = [run(index, batch) for index, batch in enumerate(batches, start=1)]
    else:
        completed = []
        with ThreadPoolExecutor(max_workers=min(concurrency, 3)) as executor:
            futures = {
                executor.submit(run, index, batch): index
                for index, batch in enumerate(batches, start=1)
            }
            for future in as_completed(futures):
                completed.append(future.result())

    for batch_keywords, batch_calls, batch_retries, batch_events in sorted(
        completed, key=lambda result: result[0][0]
    ):
        batch_index, keywords = batch_keywords
        results.update(keywords)
        api_calls += batch_calls
        retries += batch_retries
        events.extend(batch_events)

    return KeywordBatchResult(results, api_calls, retries, events)


def parse_keyword_batch_response(
    response: str,
    *,
    allowed_chunk_ids: set[str],
    keywords_per_chunk: int,
) -> dict[str, list[str]]:
    """Recover valid chunk keyword objects even when neighboring objects are malformed."""
    parsed: dict[str, list[str]] = {}
    decoder = json.JSONDecoder()
    position = 0

    while position < len(response):
        object_start = response.find("{", position)
        if object_start < 0:
            break
        try:
            value, end = decoder.raw_decode(response[object_start:])
        except JSONDecodeError:
            position = object_start + 1
            continue
        position = object_start + end
        if not isinstance(value, dict):
            continue

        chunk_id = str(value.get("chunk_id", ""))
        raw_keywords = value.get("keywords")
        if chunk_id not in allowed_chunk_ids or not isinstance(raw_keywords, list):
            continue

        keywords = []
        seen = set()
        for keyword in raw_keywords:
            if not isinstance(keyword, str):
                continue
            clean = " ".join(keyword.split()).strip()
            key = clean.lower()
            if clean and key not in seen:
                seen.add(key)
                keywords.append(clean)
            if len(keywords) >= keywords_per_chunk:
                break
        parsed.setdefault(chunk_id, keywords)

    return parsed


def _extract_batch(
    index: int,
    batch: list[KeywordBatchItem],
    *,
    system_prompt: str,
    keywords_per_chunk: int,
    llm_call: Callable,
) -> tuple[tuple[int, dict[str, list[str]]], int, int, list[str]]:
    payload = [
        {
            "chunk_id": item.chunk_id,
            "type": item.chunk_type,
            "text": item.text,
            "truncated": item.truncated,
        }
        for item in batch
    ]
    allowed_ids = {item.chunk_id for item in batch}
    max_output_tokens = min(len(batch) * 80, 1200)
    input_tokens = sum(count_tokens(item.text) for item in batch)
    events = []

    for attempt in range(2):
        try:
            events.append(
                f"keyword extraction batch api call: batch={index} attempt={attempt + 1} "
                f"chunks={len(batch)} input_tokens={input_tokens} output_tokens={max_output_tokens}"
            )
            response = llm_call(
                build_llm_messages(
                    system_prompt,
                    f"Chunks:\n{json.dumps(payload, ensure_ascii=False)}",
                ),
                model=LLM_SUMMARIZER_MODEL,
                max_tokens=max_output_tokens,
                temperature=0,
            )
            parsed = parse_keyword_batch_response(
                response,
                allowed_chunk_ids=allowed_ids,
                keywords_per_chunk=keywords_per_chunk,
            )
            if parsed:
                missing_ids = allowed_ids - parsed.keys()
                events.append(
                    f"keyword extraction batch completed: batch={index} "
                    f"chunks={len(batch)} missing={len(missing_ids)}"
                )
                if missing_ids:
                    recovery_batch = [item for item in batch if item.chunk_id in missing_ids]
                    recovery_payload = [item for item in payload if item["chunk_id"] in missing_ids]
                    recovery_output_tokens = min(len(recovery_batch) * 80, 1200)
                    events.append(
                        f"keyword extraction missing recovery api call: batch={index} "
                        f"chunks={len(recovery_batch)} output_tokens={recovery_output_tokens}"
                    )
                    try:
                        recovery_response = llm_call(
                            build_llm_messages(
                                system_prompt,
                                f"Chunks:\n{json.dumps(recovery_payload, ensure_ascii=False)}",
                            ),
                            model=LLM_SUMMARIZER_MODEL,
                            max_tokens=recovery_output_tokens,
                            temperature=0,
                        )
                        recovered = parse_keyword_batch_response(
                            recovery_response,
                            allowed_chunk_ids=missing_ids,
                            keywords_per_chunk=keywords_per_chunk,
                        )
                        parsed.update(recovered)
                        events.append(
                            f"keyword extraction missing recovery completed: batch={index} "
                            f"recovered={len(recovered)} missing={len(missing_ids - recovered.keys())}"
                        )
                    except Exception as recovery_exc:
                        log.warning("keyword extraction missing recovery failed", exc_info=True)
                        events.append(
                            f"keyword extraction missing recovery failed: batch={index} "
                            f"reason={type(recovery_exc).__name__}"
                        )
                    return (index, parsed), attempt + 2, attempt + 1, events
                return (index, parsed), attempt + 1, attempt, events
            raise ValueError("no valid chunk keyword objects")
        except Exception as exc:
            if attempt == 0:
                events.append(f"keyword extraction batch retry: batch={index}")
                continue
            log.warning("keyword extraction batch failed", exc_info=True)
            events.append(
                f"keyword extraction batch failed: batch={index} chunks={len(batch)} "
                f"reason={type(exc).__name__}"
            )

    return (index, {}), 2, 1, events


def _truncate_item(item: KeywordBatchItem, max_tokens: int) -> KeywordBatchItem:
    tokens = _token_encoder.encode(item.text)
    if len(tokens) <= max_tokens:
        return item
    return KeywordBatchItem(
        chunk_id=item.chunk_id,
        chunk_type=item.chunk_type,
        text=_token_encoder.decode(tokens[:max_tokens]),
        truncated=True,
    )
