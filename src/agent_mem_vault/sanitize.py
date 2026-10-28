import math
import re

from agent_mem_vault.records import KINDS

CONTROL_CHARS = re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]")

INPUT_LIMITS = {
    "agent": 100,
    "namespace": 100,
    "kind": 40,
    "status": 100,
    "file": 500,
    "title": 200,
    "content": 200_000,
    "tag": 64,
    "tags": 20,
    "refs": 50,
}

DEFAULT_LIMIT = 10

_SECRET_PATTERNS = (
    (re.compile(r"\b(?:gho|ghp|github_pat)_[A-Za-z0-9_]{20,}\b"), "[REDACTED_TOKEN]"),
    (re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"), "[REDACTED_TOKEN]"),
    (re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"), "[REDACTED_TOKEN]"),
    (re.compile(r"\b(api[_-]?key|token|secret|password)=(\S+)", re.IGNORECASE), r"\1=[REDACTED_SECRET]"),
)


def sanitize_text(value: object, field: str, max_length: int) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field} must be a string")
    sanitized = CONTROL_CHARS.sub("", value).strip()
    if not sanitized:
        raise ValueError(f"{field} is required")
    if len(sanitized) > max_length:
        raise ValueError(f"{field} exceeds {max_length} characters")
    return sanitized


def sanitize_optional_text(value: object, field: str, max_length: int) -> str | None:
    if value is None or value == "":
        return None
    return sanitize_text(value, field, max_length)


def sanitize_tags(tags: list[str] | None) -> list[str]:
    if tags is None:
        return []
    if not isinstance(tags, list):
        raise TypeError("tags must be an array")
    seen: set[str] = set()
    sanitized: list[str] = []
    for tag in tags:
        if not isinstance(tag, str):
            raise TypeError("tags must contain only strings")
        cleaned = CONTROL_CHARS.sub("", tag).strip()
        if not cleaned or cleaned in seen:
            continue
        if len(cleaned) > INPUT_LIMITS["tag"]:
            raise ValueError(f"tag exceeds {INPUT_LIMITS['tag']} characters")
        seen.add(cleaned)
        sanitized.append(cleaned)
        if len(sanitized) >= INPUT_LIMITS["tags"]:
            break
    return sanitized


def sanitize_namespace(namespace: str | None, default: str) -> str:
    if namespace is None or namespace == "":
        namespace = default
    return sanitize_text(namespace, "namespace", INPUT_LIMITS["namespace"])


def sanitize_kind(kind: str) -> str:
    safe_kind = sanitize_text(kind, "kind", INPUT_LIMITS["kind"])
    if safe_kind not in KINDS:
        raise ValueError(f"kind must be one of: {', '.join(KINDS)}")
    return safe_kind


def sanitize_related_files(related_files: list[str] | None) -> list[str]:
    if related_files is None:
        return []
    if not isinstance(related_files, list):
        raise TypeError("relatedFiles must be an array")
    return [sanitize_text(item, "relatedFile", INPUT_LIMITS["file"]) for item in related_files]


def sanitize_refs(refs: list[str] | None) -> list[str]:
    if not isinstance(refs, list):
        raise TypeError("refs must be an array")
    if len(refs) > INPUT_LIMITS["refs"]:
        raise ValueError(f"refs exceeds {INPUT_LIMITS['refs']} entries")
    unique: list[str] = []
    for item in refs:
        ref = sanitize_text(item, "ref", INPUT_LIMITS["file"])
        if "\n" in ref or "`" in ref:
            raise ValueError("ref must not contain newlines or backticks")
        if ref not in unique:
            unique.append(ref)
    return unique


def sanitize_ids(ids: list[str] | None) -> list[str]:
    if ids is None:
        return []
    if not isinstance(ids, list):
        raise TypeError("supersedes must be an array")
    if len(ids) > INPUT_LIMITS["tags"]:
        raise ValueError(f"supersedes exceeds {INPUT_LIMITS['tags']} ids")
    unique: list[str] = []
    for item in ids:
        safe_id = sanitize_text(item, "supersedes id", INPUT_LIMITS["agent"])
        if safe_id not in unique:
            unique.append(safe_id)
    return unique


def normalize_limit(limit: float | None) -> int:
    if limit is None or isinstance(limit, bool) or not math.isfinite(limit) or limit <= 0:
        return DEFAULT_LIMIT
    return int(limit)


def redact_secrets(value: str) -> str:
    for pattern, replacement in _SECRET_PATTERNS:
        value = pattern.sub(replacement, value)
    return value
