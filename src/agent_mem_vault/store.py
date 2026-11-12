import re
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from agent_mem_vault import git
from agent_mem_vault.companion import (
    CARD_FILES,
    OWNER_MARKER,
    Companion,
    card_namespace,
    card_relpath,
    card_sections,
    check_threads,
    existing_cards,
    read_card,
    render_card,
)
from agent_mem_vault.generated import DASHBOARD, DASHBOARD_RELPATH, hub_relpath, render_hub
from agent_mem_vault.links import Links, link_report
from agent_mem_vault.records import (
    RECEIPT_KIND,
    Record,
    build_body,
    namespace_slug,
    parse_record,
    read_note,
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
    sanitize_aliases,
    sanitize_ids,
    sanitize_kind,
    sanitize_namespace,
    sanitize_optional_text,
    sanitize_refs,
    sanitize_related_files,
    sanitize_tags,
    sanitize_text,
)
from agent_mem_vault.search import partial_score, partial_stems, query_stems, score
from agent_mem_vault.vault import Issue, RevisionConflict, Vault, VaultError, log

VISIBILITIES = ("public", "internal", "private")
VALIDITIES = ("valid", "rejected")
LIFECYCLES = {"decision": ("accepted", "superseded"), "risk": ("open", "mitigated", "resolved")}
CLOSED_BY_SUPERSEDE = {"decision": "superseded", "risk": "resolved"}
MIN_ID_PREFIX = 8
_ID_PREFIX = re.compile(r"[0-9a-f-]+")
CONSOLIDATION_AGE = timedelta(days=7)
CONSOLIDATION_DUE = "Consolidation due: "


@dataclass(frozen=True)
class Brief:
    namespace: str
    content: str


@dataclass(frozen=True)
class _MemoryChanges:
    title: str | None
    content: str | None
    tags: list[str] | None
    aliases: list[str] | None
    status: str | None
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
        aliases: list[str] | None = None,
    ) -> Record:
        safe_kind = sanitize_kind(kind)
        safe_status = _lifecycle_status(safe_kind, sanitize_optional_text(status, "status", INPUT_LIMITS["status"]))
        if safe_status is None and safe_kind in LIFECYCLES:
            safe_status = LIFECYCLES[safe_kind][0]
        fields = {
            "status": safe_status,
            "related_files": sanitize_related_files(related_files),
            "branch": sanitize_optional_text(branch, "branch", INPUT_LIMITS["file"]),
            "commit": sanitize_optional_text(commit, "commit", INPUT_LIMITS["file"]),
            "next_action": sanitize_optional_text(next_action, "nextAction", INPUT_LIMITS["title"]),
            "aliases": sanitize_aliases(aliases),
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
        supersedes: list[str] | None = None,
        aliases: list[str] | None = None,
    ) -> Record | None:
        """Change mutable fields of one record in place. Kind, namespace, id and file name never change.

        `supersedes` adds records this one replaces; they are closed the same way as on save.
        """
        safe_id = sanitize_text(id, "id", INPUT_LIMITS["content"])
        supersede_ids = sanitize_ids(supersedes)
        fields = (title, content, tags, aliases, status, visibility, validity, rejected_reason)
        if all(value is None for value in fields) and not supersede_ids:
            raise ValueError("nothing to update: pass at least one field to change")
        changes = _MemoryChanges(
            title=None if title is None else self._redacted(sanitize_text(title, "title", INPUT_LIMITS["title"])),
            content=None
            if content is None
            else self._redacted(sanitize_text(content, "content", INPUT_LIMITS["content"])),
            tags=None if tags is None else self._redacted(sanitize_tags(tags)),
            aliases=None if aliases is None else self._redacted(sanitize_aliases(aliases)),
            status=None if status is None else self._redacted(sanitize_text(status, "status", INPUT_LIMITS["status"])),
            visibility=_choice(visibility, "visibility", VISIBILITIES),
            validity=_choice(validity, "validity", VALIDITIES),
            rejected_reason=None
            if rejected_reason is None
            else self._redacted(sanitize_text(rejected_reason, "rejected_reason", INPUT_LIMITS["title"])),
        )
        with self.vault.lock():
            self._pull_latest()
            target = _resolve(self.vault.scan().records, safe_id)
            if target is None:
                return None
            if target.kind == RECEIPT_KIND:
                raise VaultError("receipts are immutable and cannot be updated")
            _lifecycle_status(target.kind, changes.status)
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
        """Replace the given companion cards of a namespace and refresh its hub. Over the cap nothing is written."""
        limit = self._companion_limit()
        if last_session is None and threads is None:
            raise ValueError("nothing to update: pass last_session or threads")
        safe_namespace = self._namespace(namespace)
        texts = {}
        for card, value in (("last_session", last_session), ("threads", threads)):
            if value is None:
                continue
            if card == "threads" and isinstance(value, str) and not value.strip():
                texts[card] = ""
                continue
            text = self._redacted(sanitize_text(value, card, INPUT_LIMITS["content"]))
            if card == "threads":
                check_threads(text)
            if len(text) > limit:
                raise ValueError(
                    f"{card} is {len(text)} characters, over the {limit} character limit: "
                    "compact it and retry. Nothing was written."
                )
            texts[card] = text
        with self.vault.lock():
            self._pull_latest()
            updated = utc_timestamp(self.clock())
            touched = []
            for card, text in texts.items():
                relpath = card_relpath(safe_namespace, card)
                if self.vault.write_generated(relpath, render_card(safe_namespace, text, updated), OWNER_MARKER):
                    touched.append(relpath)
            touched += self.refresh_generated(safe_namespace)
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

    def get_memories(self, ids: list[str], include_private: bool = False) -> list[Record | None]:
        """One entry per requested id or id prefix, in request order: the record, or None when none is readable."""
        records = self.vault.scan().records
        hide_private = self.visibility_filter and not include_private
        found = [_resolve(records, sanitize_text(id, "id", INPUT_LIMITS["content"])) for id in ids]
        return [
            None if record is None or (hide_private and record.meta.get("visibility") == "private") else record
            for record in found
        ]

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
        include_closed: bool = False,
    ) -> list[Record]:
        records = self._select(
            namespace, agent=agent, tags=tags, kind=kind, include_private=include_private, include_closed=include_closed
        )
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
        include_closed: bool = False,
    ) -> list[Record]:
        records = self._select(
            namespace, agent=agent, tags=tags, kind=kind, include_private=include_private, include_closed=include_closed
        )
        if query:
            safe_query = sanitize_text(query, "query", INPUT_LIMITS["content"])
            if id_matches := _id_matches(records, safe_query):
                return id_matches[: normalize_limit(limit)]
            wanted = query_stems(safe_query)
            now = self.clock()
            scored = [(score(record, wanted, now), record) for record in records]
            ranked = sorted((pair for pair in scored if pair[0] is not None), key=lambda pair: -pair[0])
            records = [record for _, record in ranked]
        return records[: normalize_limit(limit)]

    def search_partial(
        self,
        query: str,
        namespace: str | None = None,
        agent: str | None = None,
        tags: list[str] | None = None,
        kind: str | None = None,
        limit: float | None = None,
        include_private: bool = False,
        include_closed: bool = False,
    ) -> list[Record]:
        """Records holding at least half of the query's words, best first: what to offer when none holds them all."""
        records = self._select(
            namespace, agent=agent, tags=tags, kind=kind, include_private=include_private, include_closed=include_closed
        )
        wanted = partial_stems(sanitize_text(query, "query", INPUT_LIMITS["content"]))
        now = self.clock()
        scored = [(partial_score(record, wanted, now), record) for record in records]
        ranked = sorted((pair for pair in scored if pair[0] is not None), key=lambda pair: -pair[0])
        return [record for _, record in ranked][: normalize_limit(limit)]

    def get_project_brief(self, namespace: str | None = None, limit: float | None = None) -> Brief:
        """Companion cards, the latest snapshot, the active records created after it, and whether to consolidate.

        Records of the same second are ordered by path, never by file time, which differs on each synced machine. A
        record from the snapshot's own second is listed, since without file times it may have been written after it.
        """
        safe_namespace = self._namespace(namespace)
        records = sorted(
            (
                record
                for record in self._select(safe_namespace)
                if record.meta.get("visibility") != "private" and record.meta.get("validity") != "rejected"
            ),
            key=lambda record: (record.created, record.path),
            reverse=True,
        )
        snapshot = next((r for r in records if r.kind == "snapshot" and not r.meta.get("superseded_by")), None)
        active = [
            record
            for record in records
            if record.kind != "snapshot"
            and _is_active(record)
            and (snapshot is None or record.created >= snapshot.created)
        ]
        sections = card_sections(self.get_companion(safe_namespace)) if self.companion_max_chars is not None else []
        if snapshot is not None:
            sections.append(
                f"## Snapshot: {snapshot.title} ({snapshot.created[:10]}, id {snapshot.short_id})\n{snapshot.content}"
            )
        if active:
            shown = active[: normalize_limit(limit)]
            lines = [f"- [{_kind_and_status(record)}] {record.title} - id {record.short_id}" for record in shown]
            if len(active) > len(shown):
                lines.append(f"- ... and {len(active) - len(shown)} more")
            heading = "Since the snapshot" if snapshot is not None else "Active records"
            sections.append(f"## {heading}\n" + "\n".join(lines))
        if reason := self._consolidation_reason(snapshot, len(active)):
            sections.append(CONSOLIDATION_DUE + reason)
        return Brief(safe_namespace, "\n\n".join(sections) or f"No saved memory found for namespace: {safe_namespace}")

    # Internals

    def _consolidation_reason(self, snapshot: Record | None, active: int) -> str | None:
        if snapshot is None:
            return f"no snapshot yet and {active} active record{'' if active == 1 else 's'}" if active else None
        try:
            age = self.clock() - datetime.fromisoformat(snapshot.created)
        except (TypeError, ValueError):
            return None
        return f"latest snapshot is {age.days} days old" if age > CONSOLIDATION_AGE else None

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
        include_closed: bool = True,
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
            and (include_closed or _is_active(record))
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
        if changes.aliases:
            meta["aliases"] = changes.aliases
        elif changes.aliases is not None:
            meta.pop("aliases", None)
        if changes.status is not None:
            meta["status"] = changes.status
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

    def _pull_latest(self) -> None:
        """Start a write from the latest remote state, so the sync job has less to merge. The caller holds the lock."""
        if self.git_autocommit:
            git.pull_latest(self.vault.root)

    def _publish(self, op: str, record: Record, also_touched: list[str] | None = None) -> None:
        """Refresh the namespace hub and the dashboard, then commit; none of it may fail the write."""
        touched = [record.path, *(also_touched or []), *self.refresh_generated(record.namespace)]
        if self.git_autocommit:
            git.autocommit(self.vault.root, touched, f"avm: {op} {record.kind} {record.id[:8]}")

    def rebuild_hubs(self, slugs: list[str] | None = None) -> tuple[list[str], list[str]]:
        """Rebuild the hubs of these namespace folders, or of all, and commit; returns touched paths, unknown slugs."""
        with self.vault.lock():
            touched, unknown = self.refresh_hubs(slugs)
            if self.git_autocommit and touched:
                git.autocommit(self.vault.root, touched, "avm: rebuild hubs")
            return touched, unknown

    def refresh_hubs(self, slugs: list[str] | None = None) -> tuple[list[str], list[str]]:
        """`rebuild_hubs` without the lock and the commit, for a caller that holds the lock."""
        names = {namespace_slug(r.namespace): r.namespace for r in reversed(self._newest_first())}
        folders = {
            path.name
            for path in self.vault.root.iterdir()
            if path.is_dir() and not path.is_symlink() and namespace_slug(path.name) == path.name
        }
        known = folders | names.keys()
        wanted = sorted(known) if slugs is None else list(dict.fromkeys(slugs))
        touched: list[str] = []
        for slug in wanted:
            if slug in known:
                touched += self.refresh_generated(names.get(slug) or card_namespace(self.vault, slug) or slug)
        return touched, [slug for slug in wanted if slug not in known]

    def refresh_generated(self, namespace: str) -> list[str]:
        """Rewrite the namespace hub and create the dashboard if absent; a namespace without records or cards loses its
        generated hub. Returns the changed paths; failures are logged, never raised. The caller holds the lock."""
        touched: list[str] = []
        try:
            hub = hub_relpath(namespace)
            slug = namespace_slug(namespace)
            siblings = [r for r in self.vault.scan().records if namespace_slug(r.namespace) == slug]
            cards = existing_cards(self.vault, namespace)
            if not siblings and not cards:
                return self._remove_hub(hub)
            if self.vault.write_generated(hub, render_hub(namespace, siblings, cards)):
                touched.append(hub)
            if not (self.vault.root / DASHBOARD_RELPATH).exists():
                self.vault.write_new(DASHBOARD_RELPATH, DASHBOARD)
                touched.append(DASHBOARD_RELPATH)
        except (OSError, UnicodeDecodeError, VaultError) as error:
            log(f"could not refresh generated notes: {error}")
        return touched

    def _remove_hub(self, relpath: str) -> list[str]:
        """Delete a hub the server generated, and its folder once empty. Only a file carrying the whole hub frontmatter
        (generated, agent-written and a namespace of this folder) is ours; any other note there stays."""
        path = self.vault.root / relpath
        if path.is_symlink() or not path.is_file():
            return []
        meta = read_note(path.read_text(encoding="utf-8"))[0]
        namespace = meta.get("namespace")
        ours = meta.get("generated") is True and meta.get("agent-written") is True and isinstance(namespace, str)
        if not ours or hub_relpath(namespace) != relpath:
            return []
        path.unlink()
        if not any(path.parent.iterdir()):
            path.parent.rmdir()
        return [relpath]

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
            self._pull_latest()
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


def _is_active(record: Record) -> bool:
    return not record.meta.get("superseded_by") and record.meta.get("status") not in CLOSED_BY_SUPERSEDE.values()


def _kind_and_status(record: Record) -> str:
    status = record.meta.get("status")
    return f"{record.kind}: {status}" if status else record.kind


def _resolve(records: list[Record], wanted: str) -> Record | None:
    """The record with this id, or the only one whose id starts with a prefix of at least MIN_ID_PREFIX characters."""
    exact = next((record for record in records if record.id == wanted), None)
    if exact is not None or len(wanted) < MIN_ID_PREFIX:
        return exact
    matches = [record for record in records if record.id.startswith(wanted)]
    if len(matches) > 1:
        raise VaultError(f"id prefix {wanted} matches {len(matches)} records: pass more characters")
    return matches[0] if matches else None


def _id_matches(records: list[Record], query: str) -> list[Record]:
    """The records whose id starts with the query, when it is an id prefix of at least MIN_ID_PREFIX characters."""
    prefix = query.strip().lower()
    if len(prefix) < MIN_ID_PREFIX or not _ID_PREFIX.fullmatch(prefix):
        return []
    return [record for record in records if record.id.startswith(prefix)]


def _supersedes_lines(targets: list[Record]) -> list[str]:
    return [f"- Supersedes {wikilink(target.path, target.title)}" for target in targets]


def _lifecycle_status(kind: str, status: str | None) -> str | None:
    """Decisions and risks move through fixed states; every other kind keeps a free-text status."""
    allowed = LIFECYCLES.get(kind)
    if allowed is not None and status is not None and status not in allowed:
        raise ValueError(f"status of a {kind} must be one of: {', '.join(allowed)}")
    return status


def _choice(value: str | None, field: str, allowed: tuple[str, ...]) -> str | None:
    if value is not None and value not in allowed:
        raise ValueError(f"{field} must be one of: {', '.join(allowed)}")
    return value
