import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from agent_vault_memory.records import (
    Record,
    build_body,
    parse_record,
    record_relpath,
    render_record,
    replace_related,
    utc_timestamp,
    wikilink,
)
from agent_vault_memory.sanitize import (
    INPUT_LIMITS,
    normalize_limit,
    redact_secrets,
    sanitize_ids,
    sanitize_kind,
    sanitize_namespace,
    sanitize_optional_text,
    sanitize_related_files,
    sanitize_tags,
    sanitize_text,
)
from agent_vault_memory.search import query_stems, score
from agent_vault_memory.vault import Vault, VaultError


@dataclass(frozen=True)
class Brief:
    title: str
    namespace: str
    created: str
    content: str


def _now() -> datetime:
    return datetime.now(UTC)


class Store:
    def __init__(
        self,
        vault: Vault,
        default_namespace: str = "default",
        redact: bool = True,
        clock: Callable[[], datetime] = _now,
    ) -> None:
        self.vault = vault
        self.default_namespace = default_namespace
        self.redact = redact
        self.clock = clock

    # Writes

    def save_context(
        self, agent: str, title: str, content: str, namespace: str | None = None, tags: list[str] | None = None
    ) -> Record:
        return self._create(
            kind="note",
            agent=sanitize_text(agent, "agent", INPUT_LIMITS["agent"]),
            namespace=self._namespace(namespace),
            title=sanitize_text(title, "title", INPUT_LIMITS["title"]),
            content=sanitize_text(content, "content", INPUT_LIMITS["content"]),
            tags=sanitize_tags(tags),
        )

    def save_memory(
        self,
        agent: str,
        kind: str,
        title: str,
        content: str,
        namespace: str | None = None,
        status: str | None = None,
        related_files: list[str] | None = None,
        branch: str | None = None,
        commit: str | None = None,
        next_action: str | None = None,
        tags: list[str] | None = None,
        supersedes: list[str] | None = None,
    ) -> Record:
        safe_kind = sanitize_kind(kind)
        if safe_kind == "handoff":
            raise ValueError("kind handoff is created with create_handoff")
        fields = {
            "status": sanitize_optional_text(status, "status", INPUT_LIMITS["status"]),
            "related_files": sanitize_related_files(related_files),
            "branch": sanitize_optional_text(branch, "branch", INPUT_LIMITS["file"]),
            "commit": sanitize_optional_text(commit, "commit", INPUT_LIMITS["file"]),
            "next_action": sanitize_optional_text(next_action, "nextAction", INPUT_LIMITS["title"]),
        }
        return self._create(
            kind=safe_kind,
            agent=sanitize_text(agent, "agent", INPUT_LIMITS["agent"]),
            namespace=self._namespace(namespace),
            title=sanitize_text(title, "title", INPUT_LIMITS["title"]),
            content=sanitize_text(content, "content", INPUT_LIMITS["content"]),
            tags=sanitize_tags(tags),
            fields=fields,
            supersedes_ids=sanitize_ids(supersedes),
        )

    def create_snapshot(self, agent: str, title: str, content: str, namespace: str | None = None) -> Record:
        return self._create(
            kind="snapshot",
            agent=sanitize_text(agent, "agent", INPUT_LIMITS["agent"]),
            namespace=self._namespace(namespace),
            title=sanitize_text(title, "title", INPUT_LIMITS["title"]),
            content=sanitize_text(content, "content", INPUT_LIMITS["content"]),
            tags=["snapshot"],
        )

    def create_handoff(
        self,
        to: str,
        summary: str,
        context: str,
        namespace: str | None = None,
        supersedes: list[str] | None = None,
    ) -> Record:
        safe_to = sanitize_text(to, "to", INPUT_LIMITS["agent"])
        safe_summary = sanitize_text(summary, "summary", INPUT_LIMITS["title"])
        safe_context = sanitize_text(context, "context", INPUT_LIMITS["content"])
        return self._create(
            kind="handoff",
            agent="handoff",
            namespace=self._namespace(namespace),
            title=f"Handoff to {safe_to}",
            content=f"## Summary\n{safe_summary}\n\n## Full Context\n{safe_context}",
            tags=["handoff"],
            fields={"to": safe_to, "read": False},
            supersedes_ids=sanitize_ids(supersedes),
        )

    def read_handoff(self, agent: str, namespace: str | None = None) -> Record | None:
        safe_agent = sanitize_text(agent, "agent", INPUT_LIMITS["agent"])
        safe_namespace = self._namespace(namespace)
        with self.vault.lock():
            pending = self._pending_handoffs(safe_namespace, safe_agent)
            return self._set_read(pending[0], True) if pending else None

    def ack_handoff(self, id: str, namespace: str | None = None) -> Record | None:
        return self._change_handoff_state(id, namespace, read=True)

    def reopen_handoff(self, id: str, namespace: str | None = None) -> Record | None:
        return self._change_handoff_state(id, namespace, read=False)

    # Reads

    def peek_handoff(self, agent: str, namespace: str | None = None) -> Record | None:
        pending = self._pending_handoffs(
            self._namespace(namespace), sanitize_text(agent, "agent", INPUT_LIMITS["agent"])
        )
        return pending[0] if pending else None

    def list_handoffs(
        self,
        namespace: str | None = None,
        agent: str | None = None,
        status: str = "all",
        limit: float | None = None,
    ) -> list[Record]:
        destination = sanitize_text(agent, "agent", INPUT_LIMITS["agent"]) if agent else None
        records = self._select(namespace, type="handoff", handoff_status=status)
        return [record for record in records if destination is None or record.to == destination][
            : normalize_limit(limit)
        ]

    def get_last_context(self, namespace: str | None = None, agent: str | None = None) -> Record | None:
        records = self._select(namespace, agent=agent, type="context")
        return records[0] if records else None

    def list_contexts(
        self,
        namespace: str | None = None,
        agent: str | None = None,
        tags: list[str] | None = None,
        type: str | None = None,
        kind: str | None = None,
        limit: float | None = None,
    ) -> list[Record]:
        records = self._select(namespace, agent=agent, tags=tags, type=type, kind=kind)
        return records[: normalize_limit(limit)]

    def search_memory(
        self,
        namespace: str | None = None,
        query: str | None = None,
        agent: str | None = None,
        tags: list[str] | None = None,
        type: str | None = None,
        kind: str | None = None,
        handoff_status: str = "all",
        limit: float | None = None,
    ) -> list[Record]:
        records = self._select(namespace, agent=agent, tags=tags, type=type, kind=kind, handoff_status=handoff_status)
        if query:
            wanted = query_stems(sanitize_text(query, "query", INPUT_LIMITS["content"]))
            scored = [(score(record, wanted), record) for record in records]
            ranked = sorted((pair for pair in scored if pair[0] is not None), key=lambda pair: -pair[0])
            records = [record for _, record in ranked]
        return records[: normalize_limit(limit)]

    def get_project_brief(self, namespace: str | None = None, limit: float | None = None) -> Brief:
        safe_namespace = self._namespace(namespace)
        records = [
            record
            for record in self._select(safe_namespace, type="context")
            if record.meta.get("visibility") != "private" and record.meta.get("validity") != "rejected"
        ]
        snapshot = next((record for record in records if record.kind == "snapshot"), None)
        if snapshot is not None:
            return Brief(snapshot.title, snapshot.namespace, snapshot.created, snapshot.content)
        recent = records[: normalize_limit(limit)]
        content = (
            "\n".join(f"- [{record.kind}] {record.title} ({record.agent}): {record.content}" for record in recent)
            if recent
            else f"No saved memory found for namespace: {safe_namespace}"
        )
        return Brief(f"Project brief for {safe_namespace}", safe_namespace, utc_timestamp(self.clock()), content)

    # Internals

    def _namespace(self, namespace: str | None) -> str:
        return sanitize_namespace(namespace, self.default_namespace)

    def _redacted(self, value: Any) -> Any:
        if not self.redact:
            return value
        if isinstance(value, str):
            return redact_secrets(value)
        if isinstance(value, list):
            return [self._redacted(item) for item in value]
        return value

    def _newest_first(self) -> list[Record]:
        return sorted(self.vault.scan().records, key=lambda record: record.sort_key, reverse=True)

    def _select(
        self,
        namespace: str | None,
        agent: str | None = None,
        tags: list[str] | None = None,
        type: str | None = None,
        kind: str | None = None,
        handoff_status: str = "all",
    ) -> list[Record]:
        safe_namespace = self._namespace(namespace)
        safe_agent = sanitize_text(agent, "agent", INPUT_LIMITS["agent"]) if agent else None
        safe_tags = sanitize_tags(tags)
        return [
            record
            for record in self._newest_first()
            if record.namespace == safe_namespace
            and (safe_agent is None or record.agent == safe_agent)
            and (type is None or record.type == type)
            and (kind is None or record.kind == kind)
            and set(safe_tags) <= set(record.tags)
            and (record.type != "handoff" or _matches_handoff_status(record, handoff_status))
        ]

    def _pending_handoffs(self, namespace: str, agent: str) -> list[Record]:
        return [
            record
            for record in self._newest_first()
            if record.kind == "handoff" and record.namespace == namespace and record.to == agent and record.pending
        ]

    def _change_handoff_state(self, id: str, namespace: str | None, read: bool) -> Record | None:
        safe_id = sanitize_text(id, "id", INPUT_LIMITS["content"])
        safe_namespace = self._namespace(namespace)
        with self.vault.lock():
            handoff = next(
                (
                    record
                    for record in self.vault.scan().records
                    if record.kind == "handoff" and record.namespace == safe_namespace and record.id == safe_id
                ),
                None,
            )
            if handoff is None:
                return None
            return self._set_read(handoff, read) if handoff.pending == read else handoff

    def _set_read(self, handoff: Record, read: bool) -> Record:
        def rebuild(current: Record) -> str:
            meta = dict(current.meta)
            meta["read"] = read
            if read:
                meta["read_at"] = utc_timestamp(self.clock())
            else:
                meta.pop("read_at", None)
            return self._revised(current, meta)

        return self.vault.update_file(handoff.path, rebuild)

    def _revised(self, current: Record, meta: dict[str, Any], body: str | None = None) -> str:
        meta["revision"] = current.revision + 1
        meta["updated"] = utc_timestamp(self.clock())
        return render_record(meta, current.body if body is None else body)

    def _create(
        self,
        *,
        kind: str,
        agent: str,
        namespace: str,
        title: str,
        content: str,
        tags: list[str],
        fields: dict[str, Any] | None = None,
        supersedes_ids: list[str] | None = None,
    ) -> Record:
        with self.vault.lock():
            targets = self._supersede_targets(supersedes_ids or [], namespace, kind)
            created = utc_timestamp(self.clock())
            clean_title = self._redacted(title)
            record_id, relpath = self._unused_identity(namespace, kind, created, clean_title)
            meta: dict[str, Any] = {
                "id": record_id,
                "kind": kind,
                "namespace": namespace,
                "agent": self._redacted(agent),
                "title": clean_title,
                "created": created,
                "updated": created,
                "revision": 1,
                "visibility": "internal",
                "validity": "valid",
            }
            if tags:
                meta["tags"] = self._redacted(tags)
            for key, value in (fields or {}).items():
                if value is not None and value != []:
                    meta[key] = self._redacted(value)
            if targets:
                meta["supersedes"] = [wikilink(target.path) for target in targets]
            meta["agent-written"] = True
            related = [f"- Supersedes {wikilink(target.path, target.title)}" for target in targets]
            text = render_record(meta, build_body(self._redacted(content), related))
            self.vault.write_new(relpath, text)
            record = parse_record(relpath, text, (self.vault.root / relpath).stat().st_mtime_ns)
            for target in targets:
                self._mark_superseded(target, record)
            return record

    def _unused_identity(self, namespace: str, kind: str, created: str, title: str) -> tuple[str, str]:
        while True:
            record_id = str(uuid.uuid4())
            relpath = record_relpath(namespace, kind, created, title, record_id)
            if not (self.vault.root / relpath).exists():
                return record_id, relpath

    def _supersede_targets(self, ids: list[str], namespace: str, kind: str) -> list[Record]:
        if not ids:
            return []
        by_id = {record.id: record for record in self.vault.scan().records if record.namespace == namespace}
        targets = []
        for target_id in ids:
            target = by_id.get(target_id)
            if target is None:
                raise VaultError(f"Record not found in namespace {namespace}: {target_id}")
            if kind == "handoff" and target.kind != "handoff":
                raise VaultError(f"Record is not a handoff: {target_id}")
            if target.meta.get("superseded_by"):
                raise VaultError(f"Record is already superseded: {target_id}")
            targets.append(target)
        return targets

    def _mark_superseded(self, target: Record, replacement: Record) -> None:
        def rebuild(current: Record) -> str:
            meta = dict(current.meta)
            meta["superseded_by"] = wikilink(replacement.path)
            if current.pending:
                meta["read"] = True
                meta["read_at"] = utc_timestamp(self.clock())
            lines = [line for line in current.related_lines if not line.startswith("- Superseded by ")]
            lines.append(f"- Superseded by {wikilink(replacement.path, replacement.title)}")
            return self._revised(current, meta, replace_related(current.body, lines))

        self.vault.update_file(target.path, rebuild)


def _matches_handoff_status(record: Record, status: str) -> bool:
    if status == "pending":
        return record.pending
    if status == "read":
        return not record.pending
    return True
