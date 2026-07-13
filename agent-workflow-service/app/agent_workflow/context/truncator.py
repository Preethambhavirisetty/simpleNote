from __future__ import annotations

import json
from typing import Any

from app.agent_workflow.config import TruncationPolicy
from app.agent_workflow.context.scorer import content_fingerprint


def truncate_tool_result(
    tool_result: Any,
    *,
    step_query: str,
    policy: TruncationPolicy,
) -> tuple[str, Any, bool]:
    """Return summary text, raw_ref, truncated flag."""
    if isinstance(tool_result, str):
        truncated = len(tool_result) > policy.max_artifact_chars
        return (
            _truncate_text(tool_result, policy.max_artifact_chars),
            _compact_raw_ref(tool_result, truncated=truncated),
            truncated,
        )

    if isinstance(tool_result, dict):
        summary_obj, truncated = _truncate_dict(tool_result, step_query, policy)
        summary = json.dumps(summary_obj, ensure_ascii=False, indent=2)
        if len(summary) > policy.max_artifact_chars:
            summary = _truncate_text(summary, policy.max_artifact_chars)
            truncated = True
        return summary, _compact_raw_ref(tool_result, truncated=truncated), truncated

    if isinstance(tool_result, list):
        summary_obj, truncated = _truncate_list(tool_result, policy)
        if tool_result and isinstance(tool_result[0], dict):
            lines = []
            visible = min(len(tool_result), policy.max_list_rows_visible)
            for item in tool_result[:visible]:
                if isinstance(item, dict):
                    parts = [f"{k}={v}" for k, v in item.items() if v is not None][:4]
                    lines.append("- " + ", ".join(parts))
            if lines:
                # The line summary is what the model sees; it is only truncated
                # when rows were actually hidden, regardless of the JSON-payload
                # heuristic above.
                truncated = len(tool_result) > visible
                summary = "\n".join(lines)
                if len(tool_result) > visible:
                    summary += f"\n... and {len(tool_result) - visible} more"
                if len(summary) > policy.max_artifact_chars:
                    summary = _truncate_text(summary, policy.max_artifact_chars)
                    truncated = True
                return summary, _compact_raw_ref(tool_result, truncated=truncated), truncated
        summary = json.dumps(summary_obj, ensure_ascii=False, indent=2)
        # A single oversized item survives item-fitting as visible_items[:1];
        # clamp the rendered summary so it can never exceed the artifact budget.
        if len(summary) > policy.max_artifact_chars:
            summary = _truncate_text(summary, policy.max_artifact_chars)
            truncated = True
        return summary, _compact_raw_ref(tool_result, truncated=truncated), truncated

    text = str(tool_result)
    truncated = len(text) > policy.max_artifact_chars
    return _truncate_text(text, policy.max_artifact_chars), _compact_raw_ref(text, truncated=truncated), truncated


# Structured fact/collection fields that fact_extractor reads directly from
# raw_ref. Compaction normally reduces list/dict values to counts/keys, which
# would drop these before fact extraction sees them, so they are preserved
# verbatim within a small budget. Keep these in sync with the fact contract in
# nodes/fact_extractor.py (_FACT_PATHS / _COLLECTION_PATHS).
_STRUCTURED_LIST_KEYS = ("facts", "items", "results", "rows", "panels", "tables")
_STRUCTURED_CONTAINER_KEYS = ("data", "display", "metadata")
_STRUCTURED_SUBKEYS = ("facts", "items", "results", "rows", "panels", "tables")
_MAX_STRUCTURED_ITEMS = 50
_MAX_STRUCTURED_REF_CHARS = 8000


def _fit_structured_value(value: Any, *, budget: int) -> Any | None:
    """Return a size-bounded copy of a structured value, or None when too big."""
    if budget <= 0:
        return None
    if isinstance(value, list):
        value = value[:_MAX_STRUCTURED_ITEMS]
    try:
        if len(json.dumps(value, ensure_ascii=False, default=str)) <= budget:
            return value
    except (TypeError, ValueError):
        return None
    if isinstance(value, list):
        # Keep the longest prefix that fits. Break as soon as an item overflows —
        # including the first one, so a single oversized row cannot exceed budget.
        kept: list[Any] = []
        for item in value:
            candidate = kept + [item]
            if len(json.dumps(candidate, ensure_ascii=False, default=str)) > budget:
                break
            kept = candidate
        return kept or None
    return None


def _preserve_structured_fields(tool_result: dict[str, Any], ref: dict[str, Any]) -> None:
    """Copy small structured fact/collection fields into the compact raw_ref."""
    budget = _MAX_STRUCTURED_REF_CHARS
    for key, value in tool_result.items():
        if budget <= 0:
            break
        if key in _STRUCTURED_LIST_KEYS and isinstance(value, list) and value:
            kept = _fit_structured_value(value, budget=budget)
            if kept:
                ref[key] = kept
                budget -= len(json.dumps(kept, ensure_ascii=False, default=str))
        elif key in _STRUCTURED_CONTAINER_KEYS and isinstance(value, dict):
            preserved: dict[str, Any] = {}
            for sub in _STRUCTURED_SUBKEYS:
                sub_val = value.get(sub)
                if isinstance(sub_val, list) and sub_val:
                    kept = _fit_structured_value(sub_val, budget=budget)
                    if kept:
                        preserved[sub] = kept
                        budget -= len(json.dumps(kept, ensure_ascii=False, default=str))
            if preserved:
                ref[key] = preserved


def _compact_raw_ref(tool_result: Any, *, truncated: bool) -> dict[str, Any]:
    """Helper for compact raw ref."""
    if isinstance(tool_result, dict):
        ref: dict[str, Any] = {"type": "dict", "truncated": truncated, "keys": list(tool_result.keys())[:30]}
        for key in ("ok", "query", "user_id", "doc_id", "document_id", "note_id", "chunk_id", "page", "uri", "url", "path", "message"):
            if key in tool_result and tool_result[key] is not None:
                ref[key] = tool_result[key]
        for key, value in tool_result.items():
            if isinstance(value, list):
                ref[f"{key}_count"] = len(value)
            elif isinstance(value, dict):
                ref[f"{key}_keys"] = list(value.keys())[:20]
        _preserve_structured_fields(tool_result, ref)
        return ref
    if isinstance(tool_result, list):
        # A top-level list's visible rows are already line-formatted into the
        # summary, which holds MORE rows than a budget-bounded structured copy
        # would. Since fact_extractor prefers a structured collection over the
        # summary, adding a partial `items` here would REDUCE fidelity, so the
        # ref stays compact and summary line-splitting is the intended path.
        # Known limitation: a long/truncated top-level list only exposes its
        # visible summary rows to fact extraction. Apps that need every row of a
        # large collection should return it as {items:[...]}/{rows:[...]} etc.,
        # or emit a structured `facts` field, both of which ARE preserved above.
        return {"type": "list", "total": len(tool_result), "truncated": truncated}
    text = str(tool_result)
    ref: dict[str, Any] = {"type": "text", "chars": len(text), "truncated": truncated}
    if len(text) <= 500:
        ref["preview"] = text
    return ref


def extract_source_ref(tool_result: Any) -> dict[str, Any]:
    """Extract source ref from a larger payload."""
    if not isinstance(tool_result, dict):
        return {}
    ref: dict[str, Any] = {}
    for key in ("doc_id", "document_id", "chunk_id", "page", "uri", "url", "path"):
        if key in tool_result and tool_result[key] is not None:
            ref[key] = tool_result[key]
    metadata = tool_result.get("metadata")
    if isinstance(metadata, dict):
        for key in ("doc_id", "chunk_id", "page", "uri"):
            if key in metadata and key not in ref:
                ref[key] = metadata[key]
    return ref


def _truncate_text(text: str, max_chars: int) -> str:
    """Truncate text to fit configured context limits."""
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 20] + "\n...[truncated]..."


def _truncate_dict(data: dict[str, Any], step_query: str, policy: TruncationPolicy) -> tuple[dict[str, Any], bool]:
    """Truncate dict to fit configured context limits.

    String fields are kept verbatim and only clipped if the whole payload
    actually exceeds ``max_artifact_chars`` — so a small result is never
    truncated just because one field happens to be longer than
    ``max_string_field_chars``. When over budget, the largest string fields are
    trimmed first (down to ``max_string_field_chars``), then, if still too big,
    the payload is narrowed to query-relevant keys.
    """
    max_chars = policy.max_artifact_chars
    truncated = False
    output: dict[str, Any] = {}
    list_fields: list[tuple[str, list[dict[str, Any]]]] = []
    string_keys: list[str] = []
    query_terms = set(step_query.lower().split())

    for key, value in data.items():
        if isinstance(value, list) and value and isinstance(value[0], dict):
            list_fields.append((key, value))
            continue
        output[key] = value
        if isinstance(value, str):
            string_keys.append(key)

    base_text = json.dumps(output, ensure_ascii=False, indent=2)
    remaining = max(
        policy.dict_list_min_budget,
        max_chars - len(base_text) - policy.dict_list_budget_reserve,
    )

    for key, value in list_fields:
        visible, list_truncated = _fit_dict_list_items(value, max_chars=remaining)
        output[key] = visible
        if list_truncated:
            output[f"{key}_truncated"] = True
            output[f"{key}_total"] = len(value)
            truncated = True
        chunk = json.dumps({key: visible}, ensure_ascii=False, indent=2)
        remaining = max(policy.dict_list_min_budget, remaining - len(chunk))

    # Only now, if the payload is genuinely over budget, clip string fields —
    # largest first — rather than pre-clipping every field regardless of size.
    if len(json.dumps(output, ensure_ascii=False, indent=2)) > max_chars:
        for key in sorted(string_keys, key=lambda k: len(str(output.get(k) or "")), reverse=True):
            if len(json.dumps(output, ensure_ascii=False, indent=2)) <= max_chars:
                break
            value = str(output.get(key) or "")
            if len(value) > policy.max_string_field_chars:
                output[key] = _truncate_text(value, policy.max_string_field_chars)
                truncated = True

    text = json.dumps(output, ensure_ascii=False, indent=2)
    if len(text) > max_chars:
        truncated = True
        prioritized: dict[str, Any] = {}
        for key, value in output.items():
            if any(term in key.lower() for term in query_terms):
                prioritized[key] = value
        if prioritized:
            output = prioritized
    return output, truncated


def _fit_dict_list_items(
    items: list[dict[str, Any]],
    *,
    max_chars: int,
) -> tuple[list[dict[str, Any]], bool]:
    """Keep as many dict rows as fit within the remaining character budget."""
    if not items:
        return [], False
    visible: list[dict[str, Any]] = []
    for item in items:
        candidate = visible + [item]
        candidate_text = json.dumps(candidate, ensure_ascii=False, indent=2)
        if len(candidate_text) > max_chars and visible:
            return visible, True
        visible = candidate
    return visible, len(visible) < len(items)


def _truncate_list(items: list[Any], policy: TruncationPolicy) -> tuple[dict[str, Any], bool]:
    """Truncate list to fit configured context limits."""
    max_chars = policy.max_artifact_chars
    visible_limit = policy.max_list_rows_visible
    truncated = len(items) > visible_limit
    visible_items = items[:visible_limit]
    payload = {
        "items": visible_items,
        "total": len(items),
    }
    if truncated:
        payload["truncated"] = True
    text = json.dumps(payload)
    if len(text) > max_chars:
        reduced: list[Any] = []
        for item in visible_items:
            candidate = reduced + [item]
            if len(json.dumps({"items": candidate, "total": len(items)}, default=str)) > max_chars and reduced:
                break
            reduced = candidate
        payload["items"] = reduced or visible_items[:1]
        payload["truncated"] = True
        # Reduction dropped rows to fit the budget, so report truncation even
        # when the original row count was within max_list_rows_visible.
        truncated = True
    return payload, truncated


def make_artifact_id(tool: str, summary: str) -> str:
    """Make artifact id."""
    return f"{tool}:{content_fingerprint(summary)}"
