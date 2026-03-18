"""Search logic for the Agent Skills UI, ported from the MCP path.

Provides smart field detection, semantic/hybrid search, agentic search,
structured queries, suggestions, autocomplete, and preview text generation.
"""

import re
from opensearchpy import OpenSearch

from .client import normalize_text

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_NUMERIC_FIELD_TYPES = {
    "byte", "short", "integer", "long", "float",
    "half_float", "double", "scaled_float",
}
_KEYWORD_FIELD_TYPES = {"keyword", "constant_keyword"}
_EXACT_TERM_FIELD_TYPES = _KEYWORD_FIELD_TYPES | _NUMERIC_FIELD_TYPES | {
    "boolean", "date", "date_nanos", "ip", "version", "unsigned_long",
}
_STRUCTURED_QUERY_PAIR_PATTERN = re.compile(
    r"""
    (?P<field>[A-Za-z0-9_.-]+)\s*:\s*
    (?P<value>"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*'|.*?)
    (?:(?:\s+and\s+)(?=[A-Za-z0-9_.-]+\s*:)|$)
    """,
    re.IGNORECASE | re.VERBOSE,
)


# ---------------------------------------------------------------------------
# Value analysis helpers
# ---------------------------------------------------------------------------
def _value_shape(text: str) -> dict[str, object]:
    compact = normalize_text(text)
    tokens = re.findall(r"[A-Za-z0-9_]+", compact)
    alpha_count = sum(1 for ch in compact if ch.isalpha())
    digit_count = sum(1 for ch in compact if ch.isdigit())
    length = len(compact)
    alpha_ratio = (alpha_count / length) if length else 0.0
    digit_ratio = (digit_count / length) if length else 0.0
    return {
        "text": compact,
        "length": length,
        "tokens": tokens,
        "token_count": len(tokens),
        "alpha_ratio": alpha_ratio,
        "digit_ratio": digit_ratio,
        "looks_numeric": bool(re.fullmatch(r"[+-]?\d+(\.\d+)?", compact)),
        "looks_date": bool(re.fullmatch(r"\d{4}([-/]\d{1,2}([-/]\d{1,2})?)?", compact)),
    }


def _text_richness_score(value: str) -> float:
    shape = _value_shape(value)
    length = int(shape["length"])
    if length < 2:
        return 0.0
    alpha_ratio = float(shape["alpha_ratio"])
    token_count = int(shape["token_count"])
    return (
        alpha_ratio * 20.0
        + token_count * 10.0
        + min(length, 100) / 100.0 * 5.0
    )


# ---------------------------------------------------------------------------
# Index introspection
# ---------------------------------------------------------------------------
def extract_index_field_specs(client: OpenSearch, index_name: str) -> dict[str, dict[str, str]]:
    field_specs: dict[str, dict[str, str]] = {}
    try:
        mapping_response = client.indices.get_mapping(index=index_name)
    except Exception:
        return field_specs

    index_mapping = {}
    if isinstance(mapping_response, dict):
        index_mapping = next(iter(mapping_response.values()), {})
    mappings = index_mapping.get("mappings", {})

    def _walk(properties: dict, prefix: str = "") -> None:
        if not isinstance(properties, dict):
            return
        for field_name, config in properties.items():
            if not isinstance(config, dict):
                continue
            full_name = f"{prefix}.{field_name}" if prefix else field_name
            field_type = config.get("type")
            if isinstance(field_type, str):
                field_specs[full_name] = {
                    "type": field_type,
                    "normalizer": str(config.get("normalizer", "")).strip(),
                }
            sub_fields = config.get("fields")
            if isinstance(sub_fields, dict):
                for sub_name, sub_config in sub_fields.items():
                    if not isinstance(sub_config, dict):
                        continue
                    sub_type = sub_config.get("type")
                    if not isinstance(sub_type, str):
                        continue
                    field_specs[f"{full_name}.{sub_name}"] = {
                        "type": sub_type,
                        "normalizer": str(sub_config.get("normalizer", "")).strip(),
                    }
            nested_props = config.get("properties")
            if isinstance(nested_props, dict):
                _walk(nested_props, full_name)

    _walk(mappings.get("properties", {}))
    return field_specs


def _resolve_text_query_fields(field_specs: dict[str, dict[str, str]], limit: int = 6) -> list[str]:
    text_fields = [
        field for field, spec in field_specs.items()
        if spec.get("type") == "text" and not field.endswith(".keyword")
    ]
    keyword_fields = [
        field for field, spec in field_specs.items()
        if spec.get("type") in _KEYWORD_FIELD_TYPES and not field.endswith(".keyword")
    ]

    def _score(field_name: str) -> tuple[int, int]:
        return field_name.count("."), len(field_name)

    ranked = sorted(text_fields, key=_score)
    if not ranked:
        ranked = sorted(keyword_fields, key=_score)
    selected = ranked[:max(1, limit)]
    return selected if selected else ["*"]


def _resolve_field_spec_for_doc_key(
    field_name: str, field_specs: dict[str, dict[str, str]]
) -> tuple[str, dict[str, str]]:
    if field_name in field_specs:
        return field_name, field_specs[field_name]
    lowered = field_name.lower()
    for candidate_name, candidate_spec in field_specs.items():
        if candidate_name.lower() == lowered:
            return candidate_name, candidate_spec
    for candidate_name, candidate_spec in field_specs.items():
        if candidate_name.split(".")[-1].lower() == lowered:
            return candidate_name, candidate_spec
    return "", {}


# ---------------------------------------------------------------------------
# Semantic / agentic runtime detection
# ---------------------------------------------------------------------------
def _resolve_semantic_runtime_hints(
    client: OpenSearch, index_name: str, field_specs: dict[str, dict[str, str]]
) -> dict[str, str]:
    vector_fields = [
        field for field, spec in field_specs.items()
        if spec.get("type") == "knn_vector"
    ]
    vector_field = ""
    if vector_fields:
        preferred = sorted(
            vector_fields,
            key=lambda item: (
                0 if ("embedding" in item.lower() or "vector" in item.lower()) else 1,
                len(item), item,
            ),
        )
        vector_field = preferred[0]

    default_pipeline = ""
    search_pipeline = ""
    model_id = ""
    has_agentic_pipeline = False

    try:
        settings_response = client.indices.get_settings(index=index_name)
        index_settings = next(iter(settings_response.values()), {})
        default_pipeline = normalize_text(
            index_settings.get("settings", {}).get("index", {}).get("default_pipeline", "")
        )
        search_pipeline = normalize_text(
            index_settings.get("settings", {}).get("index", {}).get("search", {}).get("default_pipeline", "")
        )
    except Exception:
        pass

    if search_pipeline:
        try:
            pipeline_response = client.transport.perform_request("GET", f"/_search/pipeline/{search_pipeline}")
            pipeline = pipeline_response.get(search_pipeline, {})
            for processor in pipeline.get("request_processors", []):
                if isinstance(processor, dict) and "agentic_query_translator" in processor:
                    has_agentic_pipeline = True
                    break
        except Exception:
            pass

    if default_pipeline:
        try:
            pipeline_response = client.ingest.get_pipeline(id=default_pipeline)
            pipeline = pipeline_response.get(default_pipeline, {})
            for processor in pipeline.get("processors", []):
                if not isinstance(processor, dict):
                    continue
                embedding = processor.get("text_embedding")
                if not isinstance(embedding, dict):
                    continue
                candidate_model = normalize_text(embedding.get("model_id", ""))
                field_map = embedding.get("field_map", {})
                if not candidate_model:
                    continue
                if isinstance(field_map, dict) and field_map:
                    if vector_field:
                        for source, target in field_map.items():
                            if normalize_text(target) == vector_field:
                                model_id = candidate_model
                                break
                        if model_id:
                            break
                    if not model_id:
                        first_source, first_target = next(iter(field_map.items()))
                        model_id = candidate_model
                        if not vector_field:
                            vector_field = normalize_text(first_target)
                else:
                    model_id = candidate_model
                    break
        except Exception:
            pass

    return {
        "vector_field": vector_field,
        "model_id": model_id,
        "default_pipeline": default_pipeline,
        "search_pipeline": search_pipeline,
        "has_agentic_pipeline": str(has_agentic_pipeline).lower(),
    }


# ---------------------------------------------------------------------------
# Query builders
# ---------------------------------------------------------------------------
def _build_default_lexical_query(query: str, fields: list[str]) -> dict:
    body: dict[str, object] = {"query": query, "fields": fields or ["*"]}
    if any(field != "*" for field in fields):
        body["fuzziness"] = "AUTO"
    return {"multi_match": body}


def _build_default_lexical_body(query: str, size: int, fields: list[str]) -> dict:
    return {"size": size, "query": _build_default_lexical_query(query=query, fields=fields)}


def _build_neural_clause(query: str, vector_field: str, model_id: str, size: int) -> dict:
    return {
        "neural": {
            vector_field: {
                "query_text": query,
                "model_id": model_id,
                "k": max(size, 10),
            }
        }
    }


# ---------------------------------------------------------------------------
# Structured query parsing
# ---------------------------------------------------------------------------
def _strip_wrapping_quotes(value_text: str) -> str:
    normalized = normalize_text(value_text)
    if len(normalized) >= 2 and (
        (normalized[0] == normalized[-1] == '"')
        or (normalized[0] == normalized[-1] == "'")
    ):
        return normalize_text(normalized[1:-1])
    return normalized


def _parse_structured_pairs(query_text: str) -> list[tuple[str, str]]:
    normalized_query = normalize_text(query_text)
    if ":" not in normalized_query:
        return []
    pairs: list[tuple[str, str]] = []
    cursor = 0
    for match in _STRUCTURED_QUERY_PAIR_PATTERN.finditer(normalized_query):
        gap = normalized_query[cursor:match.start()].strip()
        if gap:
            return []
        field_name = normalize_text(match.group("field"))
        value_text = _strip_wrapping_quotes(match.group("value"))
        if not field_name or not value_text:
            return []
        pairs.append((field_name, value_text))
        cursor = match.end()
    if not pairs:
        return []
    if normalized_query[cursor:].strip():
        return []
    return pairs


def _coerce_structured_value(raw_value: str, field_type: str) -> object:
    normalized = normalize_text(raw_value)
    lowered = normalized.lower()
    if field_type in _NUMERIC_FIELD_TYPES:
        if field_type in {"byte", "short", "integer", "long"}:
            try:
                return int(float(normalized))
            except Exception:
                return normalized
        try:
            return float(normalized)
        except Exception:
            return normalized
    if field_type == "boolean":
        if lowered in {"true", "1", "yes"}:
            return True
        if lowered in {"false", "0", "no"}:
            return False
    return normalized


def _split_structured_clauses(
    clauses: list[dict[str, object]],
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    text_clauses: list[dict[str, object]] = []
    filter_clauses: list[dict[str, object]] = []
    for clause in clauses:
        if "match_phrase" in clause:
            text_clauses.append(clause)
        else:
            filter_clauses.append(clause)
    return text_clauses, filter_clauses


def _parse_structured_clauses(
    query_text: str,
    field_specs: dict[str, dict[str, str]],
) -> tuple[list[dict[str, object]] | None, str]:
    parsed_pairs = _parse_structured_pairs(query_text)
    if not parsed_pairs:
        return None, "structured query missing field/value"
    clauses: list[dict[str, object]] = []
    for field_name, value_text in parsed_pairs:
        resolved_field, resolved_spec = _resolve_field_spec_for_doc_key(field_name, field_specs)
        target_field = resolved_field or field_name
        field_type = str(resolved_spec.get("type", "")).strip()
        if field_type == "text":
            clauses.append({"match_phrase": {target_field: value_text}})
            continue
        coerced_value = _coerce_structured_value(value_text, field_type)
        clauses.append({"term": {target_field: {"value": coerced_value}}})
    return clauses, ""


# ---------------------------------------------------------------------------
# Preview & suggestions
# ---------------------------------------------------------------------------
def _suggestion_candidates_from_doc(source: dict) -> list[str]:
    if not isinstance(source, dict):
        return []
    scored: list[tuple[float, str]] = []
    for value in source.values():
        if value is None or isinstance(value, (dict, list)):
            continue
        shape = _value_shape(str(value))
        compact = str(shape["text"])
        length = int(shape["length"])
        if length < 4 or length > 80:
            continue
        if shape["looks_numeric"] or shape["looks_date"]:
            continue
        score = _text_richness_score(str(value))
        scored.append((score, compact))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [text for _, text in scored]


def preview_text(source: dict) -> str:
    candidates = _suggestion_candidates_from_doc(source)
    if candidates:
        return candidates[0]
    if source:
        for value in source.values():
            if value is None or isinstance(value, (dict, list)):
                continue
            text = " ".join(str(value).split())
            if text:
                return text[:180]
    return "(No preview text)"


def generate_suggestions(client: OpenSearch, index_name: str, max_count: int = 6) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()

    def _append(text_value: object) -> None:
        text = normalize_text(text_value)
        if not text:
            return
        key = text.lower()
        if key in seen:
            return
        seen.add(key)
        deduped.append(text)

    if index_name:
        try:
            response = client.search(
                index=index_name,
                body={"size": max_count * 4, "query": {"match_all": {}}},
            )
            for hit in response.get("hits", {}).get("hits", []):
                source = hit.get("_source", {})
                for suggestion in _suggestion_candidates_from_doc(source):
                    _append(suggestion)
                    if len(deduped) >= max_count:
                        return deduped
        except Exception:
            pass
    return deduped[:max_count]


# ---------------------------------------------------------------------------
# Autocomplete
# ---------------------------------------------------------------------------
def _resolve_autocomplete_fields(
    field_specs: dict[str, dict[str, str]],
    preferred_field: str = "",
    limit: int = 4,
) -> list[str]:
    selected: list[str] = []
    seen: set[str] = set()

    def _append(field_name: str) -> None:
        normalized = normalize_text(field_name)
        if not normalized or normalized in seen:
            return
        seen.add(normalized)
        selected.append(normalized)

    preferred = normalize_text(preferred_field)
    if preferred:
        resolved_field, resolved_spec = _resolve_field_spec_for_doc_key(preferred, field_specs)
        candidate = resolved_field or preferred
        candidate_type = str(resolved_spec.get("type", "")).strip().lower()
        if candidate_type in {"keyword", "constant_keyword", "text"}:
            _append(candidate)

    keyword_fields = [
        name for name, spec in field_specs.items()
        if str(spec.get("type", "")).strip().lower() in {"keyword", "constant_keyword"}
    ]
    text_fields = [
        name for name, spec in field_specs.items()
        if str(spec.get("type", "")).strip().lower() == "text"
    ]

    def _rank(field_name: str) -> tuple[int, int, str]:
        return (field_name.count("."), len(field_name), field_name)

    for field_name in sorted(keyword_fields, key=_rank):
        _append(field_name)
        if len(selected) >= max(1, limit):
            return selected
    for field_name in sorted(text_fields, key=_rank):
        _append(field_name)
        if len(selected) >= max(1, limit):
            return selected
    return selected


def _source_field_variants(field_name: str) -> list[str]:
    normalized = normalize_text(field_name)
    if not normalized:
        return []
    variants = [normalized]
    if normalized.endswith(".keyword"):
        base_field = normalized[:-8]
        if base_field:
            variants.insert(0, base_field)
    return variants


def _extract_values_from_source_by_path(source: object, field_path: str) -> list[object]:
    path = normalize_text(field_path)
    if not path:
        return []
    segments = [segment for segment in path.split(".") if segment]
    if not segments:
        return []
    values: list[object] = []

    def _walk(node: object, idx: int) -> None:
        if idx >= len(segments):
            if isinstance(node, list):
                for item in node:
                    _walk(item, idx)
                return
            if isinstance(node, dict) or node is None:
                return
            values.append(node)
            return
        if isinstance(node, list):
            for item in node:
                _walk(item, idx)
            return
        if isinstance(node, dict):
            child = node.get(segments[idx])
            if child is not None:
                _walk(child, idx + 1)

    _walk(source, 0)
    return values


def autocomplete(
    client: OpenSearch, index_name: str, prefix_text: str,
    size: int = 8, preferred_field: str = "",
) -> dict[str, object]:
    target_index = normalize_text(index_name)
    prefix = normalize_text(prefix_text)
    effective_size = max(1, min(size, 20))
    if not target_index or not prefix:
        return {"index": target_index, "prefix": prefix, "field": "", "options": [], "error": ""}

    try:
        field_specs = extract_index_field_specs(client, target_index)
        fields = _resolve_autocomplete_fields(field_specs, preferred_field, limit=4)
        if not fields:
            return {"index": target_index, "prefix": prefix, "field": "", "options": [],
                    "error": "No suitable autocomplete fields found."}

        should_clauses = [{"prefix": {f: {"value": prefix}}} for f in fields]
        body = {
            "size": max(effective_size * 8, 24),
            "query": {"bool": {"should": should_clauses, "minimum_should_match": 1}},
        }
        response = client.search(index=target_index, body=body)

        options: list[str] = []
        seen: set[str] = set()
        prefix_lower = prefix.lower()

        for hit in response.get("hits", {}).get("hits", []):
            source = hit.get("_source", {})
            if not isinstance(source, dict):
                continue
            for field_name in fields:
                for variant in _source_field_variants(field_name):
                    raw_values = _extract_values_from_source_by_path(source, variant)
                    for raw_value in raw_values:
                        candidate = normalize_text(raw_value)
                        if not candidate or not candidate.lower().startswith(prefix_lower):
                            continue
                        key = candidate.lower()
                        if key in seen:
                            continue
                        seen.add(key)
                        options.append(candidate[:120])
                        if len(options) >= effective_size:
                            return {"index": target_index, "prefix": prefix,
                                    "field": fields[0], "options": options, "error": ""}

        return {"index": target_index, "prefix": prefix, "field": fields[0] if fields else "",
                "options": options, "error": ""}
    except Exception as e:
        return {"index": target_index, "prefix": prefix, "field": "", "options": [], "error": str(e)}


# ---------------------------------------------------------------------------
# Main search
# ---------------------------------------------------------------------------
_AGENTIC_INDICATORS = [
    " and ", " or ", "why", "how", "what are", "show me",
    "find", "compare", "top", "best", "under", "over", "between", "?",
]


def search_ui_search(
    client: OpenSearch,
    index_name: str,
    query_text: str,
    size: int = 20,
    debug: bool = False,
    search_intent: str = "",
    field_hint: str = "",
) -> dict:
    empty_response = {
        "error": "", "hits": [], "total": 0, "took_ms": 0,
        "query_mode": "", "capability": "",
        "used_semantic": False, "fallback_reason": "",
    }

    if not index_name:
        empty_response["error"] = "Missing index name."
        return empty_response

    query = query_text.strip()
    query_mode = "match_all"
    used_semantic = False
    fallback_reason = ""
    executed_body: dict[str, object] = {"size": size, "query": {"match_all": {}}}

    field_specs = extract_index_field_specs(client, index_name)
    lexical_fields = _resolve_text_query_fields(field_specs)

    if query:
        runtime_hints = _resolve_semantic_runtime_hints(client, index_name, field_specs)
        vector_field = runtime_hints.get("vector_field", "")
        model_id = runtime_hints.get("model_id", "")
        has_agentic_pipeline = runtime_hints.get("has_agentic_pipeline", "false") == "true"
        semantic_ready = bool(vector_field and model_id)
        lexical_query = _build_default_lexical_query(query=query, fields=lexical_fields)

        # Agentic search for complex queries
        if has_agentic_pipeline:
            query_lower = query.lower()
            if any(indicator in query_lower for indicator in _AGENTIC_INDICATORS):
                executed_body = {
                    "size": size,
                    "query": {"agentic": {"query_text": query}},
                }
                query_mode = "agentic_search"
                used_semantic = True

                try:
                    response = client.search(index=index_name, body=executed_body)
                    return _format_search_response(
                        response, query_mode, "agentic", used_semantic,
                        fallback_reason, executed_body if debug else None,
                    )
                except Exception as e:
                    fallback_reason = f"agentic search failed: {e}"

        # Structured query detection (field:value pairs)
        structured_clauses, _ = _parse_structured_clauses(query, field_specs)
        if structured_clauses is not None:
            text_clauses, filter_clauses = _split_structured_clauses(structured_clauses)
            bool_query: dict[str, object] = {}
            if text_clauses:
                bool_query["must"] = text_clauses
            if filter_clauses:
                bool_query["filter"] = filter_clauses
            executed_body = {
                "size": size,
                "query": {"bool": bool_query} if bool_query else {"match_all": {}},
            }
            query_mode = "structured_filter"
        elif semantic_ready:
            # Hybrid search: combine BM25 + neural
            neural_query = _build_neural_clause(query, vector_field, model_id, size)
            executed_body = {
                "size": size,
                "query": {
                    "hybrid": {
                        "queries": [lexical_query, neural_query],
                    }
                },
            }
            query_mode = "hybrid_default"
            used_semantic = True
        else:
            # BM25 with smart field targeting
            executed_body = _build_default_lexical_body(query=query, size=size, fields=lexical_fields)
            query_mode = "bm25_default"
    else:
        executed_body = {"size": size, "query": {"match_all": {}}}

    try:
        response = client.search(index=index_name, body=executed_body)
    except Exception as query_error:
        if query:
            fallback_reason = (
                f"{fallback_reason}; primary query failed: {query_error}"
                if fallback_reason else f"primary query failed: {query_error}"
            )
            executed_body = _build_default_lexical_body(query=query, size=size, fields=lexical_fields)
            try:
                response = client.search(index=index_name, body=executed_body)
            except Exception as fallback_error:
                # Last resort: simple multi_match on all fields
                executed_body = {
                    "size": size,
                    "query": {"multi_match": {"query": query, "fields": ["*"]}},
                }
                response = client.search(index=index_name, body=executed_body)
            used_semantic = False
            query_mode = f"{query_mode}_fallback_bm25"
        else:
            raise

    capability = "manual"
    if used_semantic:
        capability = "agentic" if query_mode == "agentic_search" else "semantic"
    elif query_mode == "structured_filter":
        capability = "structured"

    return _format_search_response(
        response, query_mode, capability, used_semantic,
        fallback_reason, executed_body if debug else None,
    )


def _format_search_response(
    response: dict,
    query_mode: str,
    capability: str,
    used_semantic: bool,
    fallback_reason: str,
    query_body: dict | None = None,
) -> dict:
    hits_out: list[dict] = []
    for hit in response.get("hits", {}).get("hits", []):
        source = hit.get("_source", {})
        hits_out.append({
            "id": hit.get("_id"),
            "score": hit.get("_score"),
            "preview": preview_text(source),
            "source": source,
        })
    result = {
        "error": "",
        "hits": hits_out,
        "total": response.get("hits", {}).get("total", {}).get("value", len(hits_out)),
        "took_ms": response.get("took", 0),
        "query_mode": query_mode,
        "capability": capability,
        "used_semantic": used_semantic,
        "fallback_reason": fallback_reason,
    }
    if query_body is not None:
        result["query_body"] = query_body
    return result
