"""Conversion of a shared-memory-mcp JSON store into vault records."""

import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agent_mem_vault.records import KINDS, utc_timestamp
from agent_mem_vault.sanitize import (
    INPUT_LIMITS,
    sanitize_optional_text,
    sanitize_related_files,
    sanitize_tags,
    sanitize_text,
)

DEFAULT_NAMESPACE = "default"
TIMESTAMP_MAX_LENGTH = 64
_SUPERSEDES = re.compile(r"Supersedes\s+([0-9a-fA-F]{8})\b")
_SUMMARY_HEADING = "## Summary"


@dataclass(frozen=True)
class PreparedRecord:
    meta: dict[str, Any]
    content: str
    timestamp_ns: int


@dataclass
class ImportReport:
    imported: int = 0
    skipped: int = 0
    superseded_marked: int = 0
    errors: list[str] = field(default_factory=list)


def parse_store(source: Path, namespace_map: dict[str, str]) -> tuple[list[PreparedRecord], list[str]]:
    """Records of a legacy store, oldest first, and one message per entry that cannot be imported.

    The legacy store lists entries newest first. Oldest first keeps the original order for entries
    that share a timestamp, because the writer gives each file a later modification time.
    """
    try:
        data = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ValueError(f"cannot read {source}: {error}") from error
    entries = data.get("contexts") if isinstance(data, dict) else None
    if not isinstance(entries, list):
        raise ValueError(f"{source} is not a shared-memory-mcp store: expected an object with a contexts array")
    prepared: list[PreparedRecord] = []
    errors: list[str] = []
    for index, entry in reversed(list(enumerate(entries))):
        try:
            prepared.append(prepare_entry(entry, namespace_map))
        except (ValueError, TypeError) as error:
            errors.append(f"entry {index}: {error}")
    return prepared, errors[::-1]


def prepare_entry(entry: Any, namespace_map: dict[str, str]) -> PreparedRecord:
    if not isinstance(entry, dict):
        raise TypeError("entry must be an object")
    kind = entry.get("kind")
    entry_type = entry.get("type") or ("handoff" if kind == "handoff" else "context")
    if entry_type not in ("context", "handoff"):
        raise ValueError("type must be one of: context, handoff")
    if entry_type == "handoff":
        kind = "handoff"
    elif kind is None:
        kind = "note"
    elif kind not in KINDS or kind == "handoff":
        raise ValueError(f"unknown kind: {kind}")
    namespace = _namespace(entry.get("namespace"), namespace_map)
    created, timestamp_ns = _timestamp(entry.get("timestamp"), "timestamp")
    meta: dict[str, Any] = {
        "id": sanitize_text(entry.get("id"), "id", INPUT_LIMITS["content"]),
        "kind": kind,
        "namespace": namespace,
        "agent": sanitize_text(
            entry.get("agent") or ("handoff" if entry_type == "handoff" else None), "agent", INPUT_LIMITS["agent"]
        ),
        "title": sanitize_text(entry.get("title"), "title", INPUT_LIMITS["title"]),
        "created": created,
        "updated": created,
        "revision": 1,
        "visibility": "internal",
        "validity": "valid",
    }
    tags = sanitize_tags(entry.get("tags"))
    if tags:
        meta["tags"] = tags
    if entry_type == "handoff":
        _add_handoff_fields(meta, entry)
    else:
        _add_context_fields(meta, entry)
    meta["agent-written"] = True
    content = sanitize_text(entry.get("content"), "content", INPUT_LIMITS["content"])
    return PreparedRecord(meta, content, timestamp_ns)


def superseded_prefix(handoff_content: str) -> str | None:
    """The id8 named by a summary line that starts with `Supersedes <id8>`, lowercased."""
    lines = handoff_content.splitlines()
    for position, line in enumerate(lines):
        if line.strip() == _SUMMARY_HEADING:
            summary = next((text.strip() for text in lines[position + 1 :] if text.strip()), "")
            match = _SUPERSEDES.match(summary)
            return match.group(1).lower() if match else None
    return None


def _namespace(value: Any, namespace_map: dict[str, str]) -> str:
    namespace = (
        DEFAULT_NAMESPACE
        if value is None or value == ""
        else sanitize_text(value, "namespace", INPUT_LIMITS["namespace"])
    )
    return sanitize_text(namespace_map.get(namespace, namespace), "namespace", INPUT_LIMITS["namespace"])


def _timestamp(value: Any, field_name: str) -> tuple[str, int]:
    text = sanitize_text(value, field_name, TIMESTAMP_MAX_LENGTH)
    try:
        moment = datetime.fromisoformat(text)
    except ValueError:
        raise ValueError(f"{field_name} must be a valid ISO 8601 date") from None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return utc_timestamp(moment), int(moment.timestamp() * 1_000_000) * 1000


def _add_context_fields(meta: dict[str, Any], entry: dict[str, Any]) -> None:
    status = sanitize_optional_text(entry.get("status"), "status", INPUT_LIMITS["status"])
    related_files = sanitize_related_files(entry.get("relatedFiles"))
    next_action = sanitize_optional_text(entry.get("nextAction"), "nextAction", INPUT_LIMITS["title"])
    branch = sanitize_optional_text(entry.get("branch"), "branch", INPUT_LIMITS["file"])
    commit = sanitize_optional_text(entry.get("commit"), "commit", INPUT_LIMITS["file"])
    for key, value in (
        ("status", status),
        ("related_files", related_files),
        ("next_action", next_action),
        ("branch", branch),
        ("commit", commit),
    ):
        if value:
            meta[key] = value


def _add_handoff_fields(meta: dict[str, Any], entry: dict[str, Any]) -> None:
    meta["to"] = sanitize_text(entry.get("to"), "to", INPUT_LIMITS["agent"])
    meta["read"] = entry.get("read") is True
    if entry.get("readAt") not in (None, ""):
        meta["read_at"], _ = _timestamp(entry["readAt"], "readAt")
        meta["updated"] = meta["read_at"]
