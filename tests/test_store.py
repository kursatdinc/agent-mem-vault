import re

import pytest

from agent_mem_vault.store import Store
from agent_mem_vault.vault import VaultError

UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


def read_text(vault, record):
    return (vault.root / record.path).read_text(encoding="utf-8")


def titles(records):
    return [record.title for record in records]


# Context and ordering


def test_save_context_creates_a_note_that_can_be_listed_and_read_back(store):
    saved = store.save_context(
        agent="agent-a", title="Planning notes", content="Use this state later.", tags=["planning"]
    )

    assert UUID.match(saved.id)
    assert saved.kind == "note"
    assert saved.namespace == "default"
    assert titles(store.list_contexts(limit=1)) == ["Planning notes"]
    assert store.get_last_context(agent="agent-a").content == "Use this state later."


def test_listing_is_newest_first_and_honours_limit(store):
    for title in ("first", "second", "third"):
        store.save_context(agent="a", title=title, content="c")

    assert titles(store.list_contexts()) == ["third", "second", "first"]
    assert titles(store.list_contexts(limit=2)) == ["third", "second"]
    assert titles(store.list_contexts(limit=0)) == ["third", "second", "first"]


def test_save_context_sanitizes_input_before_writing(store):
    saved = store.save_context(
        agent="  agent-a\x00  ",
        title="  Planning\x07 notes  ",
        content="  Keep this context.\x08  ",
        tags=[" planning ", "", "planning", "handoff\x00"],
    )

    assert (saved.agent, saved.title, saved.content, saved.tags) == (
        "agent-a",
        "Planning notes",
        "Keep this context.",
        ["planning", "handoff"],
    )


def test_required_input_that_is_empty_after_sanitization_is_rejected_and_nothing_is_written(store, vault):
    with pytest.raises(ValueError, match="agent is required"):
        store.save_context(agent=" \x00 ", title="Planning notes", content="Keep this context.")

    assert vault.scan().records == []


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("title", "t" * 201, "title exceeds 200 characters"),
        ("content", "c" * 200_001, "content exceeds 200000 characters"),
        ("agent", "a" * 101, "agent exceeds 100 characters"),
        ("namespace", "n" * 101, "namespace exceeds 100 characters"),
        ("tags", ["t" * 65], "tag exceeds 64 characters"),
    ],
)
def test_input_limits_are_enforced(store, vault, field, value, message):
    arguments = {"agent": "a", "title": "t", "content": "c"} | {field: value}

    with pytest.raises(ValueError, match=message):
        store.save_context(**arguments)

    assert vault.scan().records == []


def test_input_at_the_limit_is_accepted(store):
    saved = store.save_context(agent="a" * 100, title="t" * 200, content="c" * 200_000, namespace="n" * 100)

    assert (len(saved.agent), len(saved.title), len(saved.content), len(saved.namespace)) == (100, 200, 200_000, 100)


def test_tags_are_capped_at_twenty(store):
    saved = store.save_context(agent="a", title="t", content="c", tags=[f"tag{index}" for index in range(25)])

    assert saved.tags == [f"tag{index}" for index in range(20)]


# Namespaces and filters


def test_namespaces_isolate_records_and_the_store_default_namespace_applies(vault, store):
    store.save_context(agent="a", title="Default note", content="c")
    store.save_context(agent="a", title="Alpha note", content="c", namespace="project-alpha")
    store.save_context(agent="a", title="Beta note", content="c", namespace="project-beta")

    assert titles(store.list_contexts(namespace="project-alpha")) == ["Alpha note"]
    assert titles(store.list_contexts(namespace="project-beta")) == ["Beta note"]
    assert titles(store.list_contexts(namespace="default")) == ["Default note"]
    assert titles(store.list_contexts()) == ["Default note"]
    assert titles(Store(vault, default_namespace="project-alpha").list_contexts()) == ["Alpha note"]


def test_the_frontmatter_namespace_is_authoritative_not_the_folder(store, vault):
    saved = store.save_context(agent="a", title="Moved note", content="c", namespace="project-alpha")
    moved = vault.root / "elsewhere" / "note" / "moved.md"
    moved.parent.mkdir(parents=True)
    (vault.root / saved.path).rename(moved)

    assert titles(store.list_contexts(namespace="project-alpha")) == ["Moved note"]


def test_list_filters_combine_agent_kind_and_all_tags(store):
    store.save_context(agent="planner", title="Plain", content="c", tags=["storage", "architecture"])
    store.save_memory(agent="planner", kind="decision", title="Decision", content="c", tags=["storage"])
    store.save_memory(agent="reviewer", kind="risk", title="Risk", content="c", tags=["storage", "architecture"])

    assert titles(store.list_contexts(agent="planner")) == ["Decision", "Plain"]
    assert titles(store.list_contexts(kind="risk")) == ["Risk"]
    assert titles(store.list_contexts(tags=["storage", "architecture"])) == ["Risk", "Plain"]
    assert titles(store.list_contexts(tags=["missing"])) == []


def test_search_combines_query_tags_agent_and_namespace(store):
    store.save_context(
        namespace="project-alpha",
        agent="planner",
        title="Database decision",
        content="Use local JSON storage for now.",
        tags=["architecture", "storage"],
    )
    store.save_context(
        namespace="project-beta",
        agent="planner",
        title="Search decision",
        content="Use SQLite full text search later.",
        tags=["architecture"],
    )

    results = store.search_memory(namespace="project-alpha", query="json", agent="planner", tags=["storage"])

    assert titles(results) == ["Database decision"]
    assert store.search_memory(namespace="project-alpha", query="sqlite") == []
    assert store.search_memory(namespace="project-alpha", query="json", agent="someone-else") == []


def test_read_latest_context_honours_the_agent_filter(store):
    store.save_context(agent="agent-a", title="From a", content="A content")
    store.save_context(agent="agent-b", title="From b", content="B content")

    assert store.get_last_context().title == "From b"
    assert store.get_last_context(agent="agent-a").title == "From a"
    assert store.get_last_context(agent="agent-c") is None
    assert store.get_last_context(namespace="empty") is None


# Structured memory


def test_save_memory_stores_structured_metadata_and_filters_by_kind(store, vault):
    note = store.save_context(namespace="alpha", agent="planner", title="Plain note", content="Compatible.")
    decision = store.save_memory(
        namespace="alpha",
        agent="planner",
        kind="decision",
        title="Storage choice",
        content="Keep Markdown files for v1.",
        status="accepted",
        related_files=["src/store.py"],
        branch="feat/phase-2",
        commit="abc123",
        next_action="Document the decision.",
        tags=["architecture"],
    )

    decisions = store.search_memory(namespace="alpha", kind="decision")

    assert note.kind == "note"
    assert [record.id for record in decisions] == [decision.id]
    assert decision.meta["status"] == "accepted"
    assert decision.meta["related_files"] == ["src/store.py"]
    assert (decision.meta["branch"], decision.meta["commit"]) == ("feat/phase-2", "abc123")
    assert decision.meta["next_action"] == "Document the decision."
    assert decision.path.startswith("alpha/decision/")
    assert "status" not in note.meta


@pytest.mark.parametrize("kind", ["bogus", "handoff"])
def test_save_memory_rejects_unknown_kinds_and_handoff_is_no_longer_one(store, vault, kind):
    with pytest.raises(ValueError, match="^kind must be one of: note, decision, assumption, task, risk, snapshot$"):
        store.save_memory(agent="a", kind=kind, title="t", content="c")

    assert vault.scan().records == []


LEGACY_HANDOFF = (
    "---\nid: 0f0f0f0f-1111-4000-8000-000000000000\nkind: handoff\nnamespace: proj\nagent: handoff\n"
    "title: Handoff to codex\ncreated: 2026-10-01T09:00:00Z\ntags: [handoff]\nto: codex\nread: false\n---\n"
    "## Summary\nLegacy pelican plan.\n"
)


def test_legacy_handoff_files_are_ignored_by_every_read_and_never_reported(store, vault):
    kept = store.save_context(agent="a", title="Kept pelican", content="c", namespace="proj")
    folder = vault.root / "proj" / "handoff"
    folder.mkdir()
    (folder / "2026-10-01-handoff-to-codex-0f0f0f0f.md").write_text(LEGACY_HANDOFF, encoding="utf-8")

    scan = vault.scan()

    assert ([record.id for record in scan.records], scan.issues) == ([kept.id], [])
    assert titles(store.list_contexts("proj")) == ["Kept pelican"]
    assert titles(store.search_memory("proj", "pelican")) == ["Kept pelican"]
    assert "Handoff" not in store.get_project_brief("proj").content


# Supersedes


def test_supersedes_validates_ids_before_writing_anything(store, vault):
    decision = store.save_memory(agent="a", kind="decision", title="D", content="c", namespace="alpha")
    other_namespace = store.save_memory(agent="a", kind="decision", title="E", content="c", namespace="beta")
    store.save_memory(agent="a", kind="decision", title="D2", content="c", namespace="alpha", supersedes=[decision.id])
    before = {record.id for record in vault.scan().records}

    with pytest.raises(VaultError, match="Record not found in namespace alpha: missing-id"):
        store.save_memory(
            agent="a", kind="decision", title="X", content="c", namespace="alpha", supersedes=["missing-id"]
        )
    with pytest.raises(VaultError, match="Record not found in namespace alpha"):
        store.save_memory(
            agent="a", kind="decision", title="X", content="c", namespace="alpha", supersedes=[other_namespace.id]
        )
    with pytest.raises(VaultError, match="Record is already superseded"):
        store.save_memory(
            agent="a", kind="decision", title="X", content="c", namespace="alpha", supersedes=[decision.id]
        )
    assert {record.id for record in vault.scan().records} == before


# Redaction


def test_secrets_are_redacted_in_every_persisted_field(store, vault):
    context = store.save_context(
        agent="agent-a token=agent-secret",
        title="api_key=title-secret",
        content="Token is gho_abcdefghijklmnopqrstuvwxyz123456 and token=content-secret.",
        tags=["secret=tag-secret"],
    )
    memory = store.save_memory(
        agent="agent-c token=memory-agent-secret",
        kind="task",
        title="Task",
        content="Done",
        status="secret=status-secret",
        related_files=["token=file-secret"],
        branch="secret=branch-secret",
        commit="token=commit-secret",
        next_action="api_key=next-secret",
    )

    assert context.content == "Token is [REDACTED_TOKEN] and token=[REDACTED_SECRET]"
    assert context.title == "api_key=[REDACTED_SECRET]"
    assert context.tags == ["secret=[REDACTED_SECRET]"]
    assert memory.agent == "agent-c token=[REDACTED_SECRET]"
    on_disk = "".join(read_text(vault, record) for record in (context, memory))
    for leaked in re.findall(r"[a-z-]*-secret|gho_\w+", on_disk):
        pytest.fail(f"secret leaked to disk: {leaked}")
    assert (memory.meta["status"], memory.meta["related_files"], memory.meta["branch"]) == (
        "secret=[REDACTED_SECRET]",
        ["token=[REDACTED_SECRET]"],
        "secret=[REDACTED_SECRET]",
    )


def test_redaction_can_be_turned_off(vault):
    plain = Store(vault, redact=False)

    saved = plain.save_context(agent="a", title="t", content="token=visible-value")

    assert saved.content == "token=visible-value"
