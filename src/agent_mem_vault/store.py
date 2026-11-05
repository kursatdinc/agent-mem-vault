import re
import uuid
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from typing import Any

from agent_mem_vault import git
from agent_mem_vault.companion import CARD_FILES, OWNER_MARKER, Companion, card_relpath, read_card, render_card
from agent_mem_vault.generated import DASHBOARD, DASHBOARD_RELPATH, hub_relpath, render_hub
from agent_mem_vault.links import Links, link_report
from agent_mem_vault.records import (
    RECEIPT_KIND,
    Record,
    build_body,
    namespace_slug,
    parse_record,
    record_relpath,
    render_record,
    replace_related,
    utc_timestamp,
    wikilink,
)
from agent_mem_vault.sanitize import (
    INPUT_LIMITS,
    normalize_limit,
    redact_secrets,
    sanitize_ids,
    sanitize_kind,
    sanitize_namespace,
    sanitize_optional_text,
    sanitize_refs,
    sanitize_related_files,
    sanitize_tags,
    sanitize_text,
)
from agent_mem_vault.search import query_stems, score
from agent_mem_vault.vault import Issue, RevisionConflict, Vault, VaultError, log

VISIBILITIES = ("public", "internal", "private")
VALIDITIES = ("valid", "rejected")
LIFECYCLES = {"decision": ("accepted", "superseded"), "risk": ("open", "mitigated", "resolved")}
CLOSED_BY_SUPERSEDE = {"decision": "superseded", "risk": "resolved"}
MIN_ID_PREFIX = 8
_REVIEW_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


@dataclass(frozen=True)
class Brief:
    title: str
    namespace: str
    created: str
    content: str


@dataclass(frozen=True)
class _MemoryChanges:
    title: str | None
    content: str | None
    tags: list[str] | None
    status: str | None
    review_by: str | None
    visibility: str | None
    validity: str | None
    rejected_reason: str | None


def _now() -> datetime:
    return datetime.now(UTC)


class Store:
    def __init__(
        self,
        vault: Vault,
        default_namespace: str = "default",
        redact: bool = True,
        clock: Callable[[], datetime] = _now,
        git_autocommit: bool = False,
        companion_max_chars: int | None = None,
        visibility_filter: bool = True,
    ) -> None:
        self.vault = vault
        self.default_namespace = default_namespace
        self.redact = redact
        self.clock = clock
        self.git_autocommit = git_autocommit
        self.companion_max_chars = companion_max_chars
        self.visibility_filter = visibility_filter

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
        review_by: str | None = None,
    ) -> Record:
        safe_kind = sanitize_kind(kind)
        safe_status = _lifecycle_status(safe_kind, sanitize_optional_text(status, "status", INPUT_LIMITS["status"]))
        if safe_status is None and safe_kind in LIFECYCLES:
            safe_status = LIFECYCLES[safe_kind][0]
        fields = {
            "status": safe_status,
            "review_by": _review_date(safe_kind, review_by),
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

    def create_snapshot(
        self,
        agent: str,
        title: str,
        content: str,
        namespace: str | None = None,
        supersedes: list[str] | None = None,
    ) -> Record:
        return self._create(
            kind="snapshot",
            agent=sanitize_text(agent, "agent", INPUT_LIMITS["agent"]),
            namespace=self._namespace(namespace),
            title=sanitize_text(title, "title", INPUT_LIMITS["title"]),
            content=sanitize_text(content, "content", INPUT_LIMITS["content"]),
            tags=["snapshot"],
            supersedes_ids=sanitize_ids(supersedes),
        )

    def write_receipt(
        self,
        agent: str,
        title: str,
        summary: str,
        refs: list[str],
        namespace: str | None = None,
        harness: str | None = None,
        session: str | None = None,
    ) -> Record:
        """Record finished work with the files and commits it touched. Receipts are immutable."""
        if RECEIPT_KIND not in self.vault.kinds:
            raise VaultError("receipts are disabled: set features.receipts in the config")
        safe_refs = sanitize_refs(refs)
        fields = {
            "refs": safe_refs,
            "harness": sanitize_optional_text(harness, "harness", INPUT_LIMITS["agent"]),
            "session": sanitize_optional_text(session, "session", INPUT_LIMITS["file"]),
        }
        return self._create(
            kind=RECEIPT_KIND,
            agent=sanitize_text(agent, "agent", INPUT_LIMITS["agent"]),
            namespace=self._namespace(namespace),
            title=sanitize_text(title, "title", INPUT_LIMITS["title"]),
            content=sanitize_text(summary, "summary", INPUT_LIMITS["content"]),
            tags=[RECEIPT_KIND],
            fields=fields,
            related=[f"- `{self._redacted(ref)}`" for ref in safe_refs],
        )

    def update_memory(
        self,
        id: str,
        expected_revision: int | None = None,
        title: str | None = None,
        content: str | None = None,
        tags: list[str] | None = None,
        status: str | None = None,
        visibility: str | None = None,
        validity: str | None = None,
        rejected_reason: str | None = None,
        review_by: str | None = None,
        supersedes: list[str] | None = None,
    ) -> Record | None:
        """Change mutable fields of one record in place. Kind, namespace, id and file name never change.

        `supersedes` adds records this one replaces; they are closed the same way as on save.
        """
        safe_id = sanitize_text(id, "id", INPUT_LIMITS["content"])
        supersede_ids = sanitize_ids(supersedes)
        fields = (title, content, tags, status, visibility, validity, rejected_reason, review_by)
        if all(value is None for value in fields) and not supersede_ids:
            raise ValueError("nothing to update: pass at least one field to change")
        changes = _MemoryChanges(
            title=None if title is None else self._redacted(sanitize_text(title, "title", INPUT_LIMITS["title"])),
            content=None
            if content is None
            else self._redacted(sanitize_text(content, "content", INPUT_LIMITS["content"])),
            tags=None if tags is None else self._redacted(sanitize_tags(tags)),
            status=None if status is None else self._redacted(sanitize_text(status, "status", INPUT_LIMITS["status"])),
            review_by=review_by,
            visibility=_choice(visibility, "visibility", VISIBILITIES),
            validity=_choice(validity, "validity", VALIDITIES),
            rejected_reason=None
            if rejected_reason is None
            else self._redacted(sanitize_text(rejected_reason, "rejected_reason", INPUT_LIMITS["title"])),
        )
        with self.vault.lock():
            target = _resolve(self.vault.scan().records, safe_id)
            if target is None:
                return None
            if target.kind == RECEIPT_KIND:
                raise VaultError("receipts are immutable and cannot be updated")
            _lifecycle_status(target.kind, changes.status)
            _review_date(target.kind, changes.review_by)
            superseded = self._supersede_targets(supersede_ids, target.namespace, replacement_id=target.id)
            updated = self.vault.update_file(
                target.path, lambda current: self._apply_changes(current, changes, expected_revision, superseded)
            )
            for old in superseded:
                self._mark_superseded(old, updated)
            self._publish("update", updated, [old.path for old in superseded])
            return updated

    def update_companion(
        self, namespace: str | None = None, last_session: str | None = None, threads: str | None = None
    ) -> None:
        """Replace the given companion cards of a namespace. Over the size cap nothing is written."""
        limit = self._companion_limit()
        if last_session is None and threads is None:
            raise ValueError("nothing to update: pass last_session or threads")
        safe_namespace = self._namespace(namespace)
        texts = {}
        for card, value in (("last_session", last_session), ("threads", threads)):
            if value is None:
                continue
            text = self._redacted(sanitize_text(value, card, INPUT_LIMITS["content"]))
            if len(text) > limit:
                raise ValueError(
                    f"{card} is {len(text)} characters, over the {limit} character limit: "
                    "compact it and retry. Nothing was written."
                )
            texts[card] = text
        with self.vault.lock():
            updated = utc_timestamp(self.clock())
            touched = []
            for card, text in texts.items():
                relpath = card_relpath(safe_namespace, card)
                if self.vault.write_generated(relpath, render_card(safe_namespace, text, updated), OWNER_MARKER):
                    touched.append(relpath)
            if self.git_autocommit and touched:
                git.autocommit(self.vault.root, touched, f"avm: update companion {namespace_slug(safe_namespace)}")

    # Reads

    def get_companion(self, namespace: str | None = None) -> Companion:
        self._companion_limit()
        safe_namespace = self._namespace(namespace)
        return Companion(*(read_card(self.vault, safe_namespace, card) for card in CARD_FILES))

    def get_links(self, id: str) -> tuple[Record, Links] | None:
        record = _resolve(self.vault.scan().records, sanitize_text(id, "id", INPUT_LIMITS["content"]))
        return None if record is None else (record, link_report(self.vault, record))

    def list_issues(self) -> list[Issue]:
        return self.vault.scan().issues

    def get_last_context(
        self, namespace: str | None = None, agent: str | None = None, include_private: bool = False
    ) -> Record | None:
        records = self._select(namespace, agent=agent, include_private=include_private)
        return records[0] if records else None

    def list_contexts(
        self,
        namespace: str | None = None,
        agent: str | None = None,
        tags: list[str] | None = None,
        kind: str | None = None,
        limit: float | None = None,
        include_private: bool = False,
    ) -> list[Record]:
        records = self._select(namespace, agent=agent, tags=tags, kind=kind, include_private=include_private)
        return records[: normalize_limit(limit)]

    def search_memory(
        self,
        namespace: str | None = None,
        query: str | None = None,
        agent: str | None = None,
        tags: list[str] | None = None,
        kind: str | None = None,
        limit: float | None = None,
        include_private: bool = False,
    ) -> list[Record]:
        records = self._select(namespace, agent=agent, tags=tags, kind=kind, include_private=include_private)
        if query:
            wanted = query_stems(sanitize_text(query, "query", INPUT_LIMITS["content"]))
            scored = [(score(record, wanted), record) for record in records]
            ranked = sorted((pair for pair in scored if pair[0] is not None), key=lambda pair: -pair[0])
            records = [record for _, record in ranked]
        return records[: normalize_limit(limit)]

    def get_project_brief(self, namespace: str | None = None, limit: float | None = None) -> Brief:
        safe_namespace = self._namespace(namespace)
        brief = self._brief(safe_namespace, limit)
        last_session = read_card(self.vault, safe_namespace, "last_session") if self.companion_max_chars else None
        if last_session is None:
            return brief
        return replace(brief, content=f"{brief.content}\n\n## Last session\n{last_session}")

    # Internals

    def _brief(self, safe_namespace: str, limit: float | None) -> Brief:
        records = [
            record
            for record in self._select(safe_namespace)
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

    def _companion_limit(self) -> int:
        if self.companion_max_chars is None:
            raise VaultError("companion is disabled: set features.companion in the config")
        return self.companion_max_chars

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
        kind: str | None = None,
        include_private: bool = True,
    ) -> list[Record]:
        safe_namespace = self._namespace(namespace)
        hide_private = self.visibility_filter and not include_private
        safe_agent = sanitize_text(agent, "agent", INPUT_LIMITS["agent"]) if agent else None
        safe_tags = sanitize_tags(tags)
        return [
            record
            for record in self._newest_first()
            if record.namespace == safe_namespace
            and (safe_agent is None or record.agent == safe_agent)
            and (kind is None or record.kind == kind)
            and not (hide_private and record.meta.get("visibility") == "private")
            and set(safe_tags) <= set(record.tags)
        ]

    def _apply_changes(
        self, current: Record, changes: _MemoryChanges, expected_revision: int | None, superseded: list[Record]
    ) -> str:
        if expected_revision is not None and current.revision != expected_revision:
            raise RevisionConflict(expected_revision, current.revision)
        meta = dict(current.meta)
        if changes.title is not None:
            meta["title"] = changes.title
        if changes.tags is not None and changes.tags:
            meta["tags"] = changes.tags
        elif changes.tags is not None:
            meta.pop("tags", None)
        if changes.status is not None:
            meta["status"] = changes.status
        if changes.review_by is not None:
            meta["review_by"] = changes.review_by
        if changes.visibility is not None:
            meta["visibility"] = changes.visibility
        reason = changes.rejected_reason if changes.rejected_reason is not None else meta.get("rejected_reason")
        resulting_validity = changes.validity or meta.get("validity", "valid")
        if resulting_validity == "rejected":
            if not reason:
                raise ValueError("rejected_reason is required when validity is rejected")
            meta["rejected_reason"] = reason
        elif changes.rejected_reason is not None:
            raise ValueError("rejected_reason is only allowed when validity is rejected")
        else:
            meta.pop("rejected_reason", None)
        if changes.validity is not None:
            meta["validity"] = changes.validity
        related = current.related_lines
        body = None
        if superseded:
            earlier = meta.get("supersedes")
            earlier = earlier if isinstance(earlier, list) else [earlier] if earlier else []
            meta["supersedes"] = [*earlier, *(wikilink(old.path) for old in superseded)]
            related = [*related, *_supersedes_lines(superseded)]
            body = replace_related(current.body, related)
        if changes.content is not None:
            body = build_body(changes.content, related)
        return self._revised(current, meta, body)

    def _publish(self, op: str, record: Record, also_touched: list[str] | None = None) -> None:
        """Refresh the namespace hub and the dashboard, then commit; none of it may fail the write."""
        touched = [record.path, *(also_touched or []), *self.refresh_generated(record.namespace)]
        if self.git_autocommit:
            git.autocommit(self.vault.root, touched, f"avm: {op} {record.kind} {record.id[:8]}")

    def refresh_generated(self, namespace: str) -> list[str]:
        touched: list[str] = []
        try:
            hub = hub_relpath(namespace)
            slug = namespace_slug(namespace)
            siblings = [r for r in self.vault.scan().records if namespace_slug(r.namespace) == slug]
            self.vault.write_generated(hub, render_hub(namespace, siblings))
            touched.append(hub)
            if not (self.vault.root / DASHBOARD_RELPATH).exists():
                self.vault.write_new(DASHBOARD_RELPATH, DASHBOARD)
                touched.append(DASHBOARD_RELPATH)
        except (OSError, VaultError) as error:
            log(f"could not refresh generated notes: {error}")
        return touched

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
        related: list[str] | None = None,
    ) -> Record:
        with self.vault.lock():
            targets = self._supersede_targets(supersedes_ids or [], namespace)
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
            related_lines = [*_supersedes_lines(targets), *(related or [])]
            text = render_record(meta, build_body(self._redacted(content), related_lines))
            self.vault.write_new(relpath, text)
            record = parse_record(relpath, text, (self.vault.root / relpath).stat().st_mtime_ns, self.vault.kinds)
            for target in targets:
                self._mark_superseded(target, record)
            self._publish("create", record, [target.path for target in targets])
            return record

    def _unused_identity(self, namespace: str, kind: str, created: str, title: str) -> tuple[str, str]:
        while True:
            record_id = str(uuid.uuid4())
            relpath = record_relpath(namespace, kind, created, title, record_id)
            if not (self.vault.root / relpath).exists():
                return record_id, relpath

    def _supersede_targets(self, ids: list[str], namespace: str, replacement_id: str | None = None) -> list[Record]:
        if not ids:
            return []
        candidates = [record for record in self.vault.scan().records if record.namespace == namespace]
        targets: list[Record] = []
        for target_id in ids:
            target = _resolve(candidates, target_id)
            if target is None:
                raise VaultError(f"Record not found in namespace {namespace}: {target_id}")
            if target.id == replacement_id:
                raise VaultError("A record cannot supersede itself")
            if target.kind == RECEIPT_KIND:
                raise VaultError(f"Record is an immutable receipt: {target_id}")
            if target.meta.get("superseded_by"):
                raise VaultError(f"Record is already superseded: {target_id}")
            if all(found.id != target.id for found in targets):
                targets.append(target)
        return targets

    def _mark_superseded(self, target: Record, replacement: Record) -> None:
        def rebuild(current: Record) -> str:
            meta = dict(current.meta)
            meta["superseded_by"] = wikilink(replacement.path)
            if current.kind in CLOSED_BY_SUPERSEDE:
                meta["status"] = CLOSED_BY_SUPERSEDE[current.kind]
            lines = [line for line in current.related_lines if not line.startswith("- Superseded by ")]
            lines.append(f"- Superseded by {wikilink(replacement.path, replacement.title)}")
            return self._revised(current, meta, replace_related(current.body, lines))

        self.vault.update_file(target.path, rebuild)


def _resolve(records: list[Record], wanted: str) -> Record | None:
    """The record with this id, or the only one whose id starts with a prefix of at least MIN_ID_PREFIX characters."""
    exact = next((record for record in records if record.id == wanted), None)
    if exact is not None or len(wanted) < MIN_ID_PREFIX:
        return exact
    matches = [record for record in records if record.id.startswith(wanted)]
    if len(matches) > 1:
        raise VaultError(f"id prefix {wanted} matches {len(matches)} records: pass more characters")
    return matches[0] if matches else None


def _supersedes_lines(targets: list[Record]) -> list[str]:
    return [f"- Supersedes {wikilink(target.path, target.title)}" for target in targets]


def _lifecycle_status(kind: str, status: str | None) -> str | None:
    """Decisions and risks move through fixed states; every other kind keeps a free-text status."""
    allowed = LIFECYCLES.get(kind)
    if allowed is not None and status is not None and status not in allowed:
        raise ValueError(f"status of a {kind} must be one of: {', '.join(allowed)}")
    return status


def _review_date(kind: str, value: str | None) -> str | None:
    if value is None:
        return None
    if kind != "risk":
        raise ValueError("review_by is only allowed on risks")
    if not isinstance(value, str) or not _is_calendar_date(value):
        raise ValueError("review_by must be a date as YYYY-MM-DD")
    return value


def _is_calendar_date(value: str) -> bool:
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return _REVIEW_DATE.fullmatch(value) is not None


def _choice(value: str | None, field: str, allowed: tuple[str, ...]) -> str | None:
    if value is not None and value not in allowed:
        raise ValueError(f"{field} must be one of: {', '.join(allowed)}")
    return value
