import re

import pytest

from agent_mem_vault.records import render_record
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


def test_list_filters_combine_agent_type_kind_and_all_tags(store):
    store.save_context(agent="planner", title="Plain", content="c", tags=["storage", "architecture"])
    store.save_memory(agent="planner", kind="decision", title="Decision", content="c", tags=["storage"])
    store.save_memory(agent="reviewer", kind="risk", title="Risk", content="c", tags=["storage", "architecture"])
    store.create_handoff(to="reviewer", summary="Handoff", context="c")

    assert titles(store.list_contexts(agent="planner")) == ["Decision", "Plain"]
    assert titles(store.list_contexts(kind="risk")) == ["Risk"]
    assert titles(store.list_contexts(tags=["storage", "architecture"])) == ["Risk", "Plain"]
    assert titles(store.list_contexts(tags=["missing"])) == []
    assert titles(store.list_contexts(type="handoff")) == ["Handoff to reviewer"]
    assert titles(store.list_contexts(type="context")) == ["Risk", "Decision", "Plain"]


def test_search_combines_query_tags_agent_type_and_namespace(store):
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

    results = store.search_memory(
        namespace="project-alpha", query="json", agent="planner", tags=["storage"], type="context"
    )

    assert titles(results) == ["Database decision"]
    assert store.search_memory(namespace="project-alpha", query="sqlite") == []
    assert store.search_memory(namespace="project-alpha", query="json", agent="someone-else") == []


def test_read_latest_context_ignores_handoffs_and_honours_the_agent_filter(store):
    store.save_context(agent="agent-a", title="From a", content="A content")
    store.save_context(agent="agent-b", title="From b", content="B content")
    store.create_handoff(to="agent-a", summary="Handoff", context="c")

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


def test_save_memory_rejects_unknown_kinds_and_points_handoffs_to_create_handoff(store, vault):
    with pytest.raises(
        ValueError, match="kind must be one of: note, decision, assumption, task, risk, handoff, snapshot"
    ):
        store.save_memory(agent="a", kind="bogus", title="t", content="c")
    with pytest.raises(ValueError, match="kind handoff is created with create_handoff"):
        store.save_memory(agent="a", kind="handoff", title="t", content="c")

    assert vault.scan().records == []


# Snapshots and brief


def test_the_latest_snapshot_is_the_project_brief(store):
    store.save_memory(
        agent="planner",
        kind="decision",
        title="Search API",
        content="Add text and metadata filters.",
        namespace="alpha",
    )
    store.create_snapshot(agent="planner", title="Old brief", content="Old state.", namespace="alpha")
    snapshot = store.create_snapshot(
        agent="planner", title="Project Alpha Brief", content="Latest state: search API is ready.", namespace="alpha"
    )

    brief = store.get_project_brief(namespace="alpha")

    assert snapshot.kind == "snapshot"
    assert snapshot.tags == ["snapshot"]
    assert (brief.title, brief.namespace, brief.content) == (
        "Project Alpha Brief",
        "alpha",
        "Latest state: search API is ready.",
    )
    assert brief.created == snapshot.created


def test_the_brief_falls_back_to_recent_records_newest_first(store):
    store.save_memory(
        agent="planner", kind="decision", title="Use Markdown", content="Keep storage local.", namespace="alpha"
    )
    store.save_memory(
        agent="reviewer",
        kind="risk",
        title="Retention risk",
        content="Pending handoffs must survive.",
        namespace="alpha",
    )
    store.create_handoff(to="x", summary="Not in brief", context="c", namespace="alpha")

    brief = store.get_project_brief(namespace="alpha")

    assert brief.title == "Project brief for alpha"
    assert brief.content == (
        "- [risk] Retention risk (reviewer): Pending handoffs must survive.\n"
        "- [decision] Use Markdown (planner): Keep storage local."
    )
    assert store.get_project_brief(namespace="alpha", limit=1).content == (
        "- [risk] Retention risk (reviewer): Pending handoffs must survive."
    )


def test_the_brief_of_an_empty_namespace_says_so(store):
    brief = store.get_project_brief(namespace="nothing-here")

    assert (brief.title, brief.content) == (
        "Project brief for nothing-here",
        "No saved memory found for namespace: nothing-here",
    )


def test_the_brief_skips_private_and_rejected_records(store, vault):
    snapshot = store.create_snapshot(agent="a", title="Private snapshot", content="Secret state.", namespace="alpha")
    visible = store.save_memory(agent="a", kind="note", title="Visible", content="Shown.", namespace="alpha")
    rejected = store.save_memory(agent="a", kind="note", title="Rejected", content="Wrong.", namespace="alpha")
    (vault.root / snapshot.path).write_text(
        render_record({**snapshot.meta, "visibility": "private"}, snapshot.body), encoding="utf-8"
    )
    (vault.root / rejected.path).write_text(
        render_record({**rejected.meta, "validity": "rejected"}, rejected.body), encoding="utf-8"
    )

    brief = store.get_project_brief(namespace="alpha")

    assert brief.content == f"- [note] {visible.title} ({visible.agent}): Shown."


# Handoffs


def test_a_handoff_is_read_once_and_marked_read_in_its_file(store, vault):
    created = store.create_handoff(to="agent-b", summary="Finished discovery.", context="Continue implementation.")

    first = store.read_handoff(agent="agent-b")
    second = store.read_handoff(agent="agent-b")

    assert first.id == created.id
    assert first.content == "## Summary\nFinished discovery.\n\n## Full Context\nContinue implementation."
    assert second is None
    meta = store.list_handoffs()[0].meta
    assert meta["read"] is True
    assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$", meta["read_at"])
    assert meta["revision"] == 2
    assert "read: true" in read_text(vault, created)


def test_a_handoff_has_the_summary_and_full_context_shape(store):
    handoff = store.create_handoff(to="codex", summary="Sum", context="Ctx", namespace="alpha")

    assert (handoff.kind, handoff.agent, handoff.title, handoff.tags) == (
        "handoff",
        "handoff",
        "Handoff to codex",
        ["handoff"],
    )
    assert (handoff.to, handoff.meta["read"], handoff.pending) == ("codex", False, True)
    assert handoff.path.startswith("alpha/handoff/")


def test_read_handoff_takes_the_newest_pending_one_for_the_agent_and_namespace(store):
    store.create_handoff(to="agent-b", summary="Older", context="c", namespace="alpha")
    store.create_handoff(to="agent-c", summary="Other agent", context="c", namespace="alpha")
    store.create_handoff(to="agent-b", summary="Other namespace", context="c", namespace="beta")
    newest = store.create_handoff(to="agent-b", summary="Newest", context="c", namespace="alpha")

    assert store.peek_handoff(agent="agent-b", namespace="alpha").id == newest.id
    assert store.read_handoff(agent="agent-b", namespace="alpha").id == newest.id
    assert "Older" in store.read_handoff(agent="agent-b", namespace="alpha").content
    assert store.read_handoff(agent="agent-b", namespace="alpha") is None
    assert "Other namespace" in store.read_handoff(agent="agent-b", namespace="beta").content


def test_peek_does_not_mark_the_handoff_as_read(store):
    handoff = store.create_handoff(to="agent-b", summary="Keep pending", context="c")

    assert store.peek_handoff(agent="agent-b").id == handoff.id
    assert store.peek_handoff(agent="agent-b").id == handoff.id
    assert store.peek_handoff(agent="agent-z") is None
    assert store.list_handoffs(status="pending")[0].meta["revision"] == 1


def test_ack_and_reopen_move_a_handoff_between_pending_and_read(store):
    handoff = store.create_handoff(namespace="alpha", to="implementer", summary="Discovery done.", context="Build it.")

    assert [item.id for item in store.list_handoffs(namespace="alpha", agent="implementer", status="pending")] == [
        handoff.id
    ]

    acked = store.ack_handoff(namespace="alpha", id=handoff.id)
    assert acked.meta["read"] is True
    assert [item.id for item in store.list_handoffs(namespace="alpha", status="read")] == [handoff.id]
    assert store.list_handoffs(namespace="alpha", status="pending") == []

    reopened = store.reopen_handoff(namespace="alpha", id=handoff.id)
    assert reopened.meta["read"] is False
    assert "read_at" not in reopened.meta
    assert store.peek_handoff(agent="implementer", namespace="alpha").id == handoff.id


def test_ack_and_reopen_are_idempotent_and_report_unknown_ids(store):
    handoff = store.create_handoff(to="agent-b", summary="s", context="c")

    assert store.reopen_handoff(id=handoff.id).meta["revision"] == 1
    store.ack_handoff(id=handoff.id)
    assert store.ack_handoff(id=handoff.id).meta["revision"] == 2
    assert store.ack_handoff(id="no-such-id") is None
    assert store.reopen_handoff(id="no-such-id") is None
    assert store.ack_handoff(id=handoff.id, namespace="other") is None


def test_list_handoffs_filters_by_destination_agent_and_status(store):
    first = store.create_handoff(to="agent-b", summary="For b", context="c")
    store.create_handoff(to="agent-c", summary="For c", context="c")
    store.ack_handoff(id=first.id)

    assert titles(store.list_handoffs()) == ["Handoff to agent-c", "Handoff to agent-b"]
    assert titles(store.list_handoffs(agent="agent-b")) == ["Handoff to agent-b"]
    assert titles(store.list_handoffs(status="pending")) == ["Handoff to agent-c"]
    assert titles(store.list_handoffs(status="read")) == ["Handoff to agent-b"]


def test_search_applies_the_handoff_status_only_to_handoffs(store):
    store.save_context(agent="a", title="Shared word note", content="shared")
    pending = store.create_handoff(to="agent-b", summary="shared pending", context="c")
    done = store.create_handoff(to="agent-b", summary="shared done", context="c")
    store.ack_handoff(id=done.id)

    assert titles(store.search_memory(query="shared", handoff_status="pending")) == [
        "Shared word note",
        "Handoff to agent-b",
    ]
    assert [r.id for r in store.search_memory(query="shared", type="handoff", handoff_status="pending")] == [pending.id]
    assert [r.id for r in store.search_memory(query="shared", type="handoff", handoff_status="read")] == [done.id]


# Supersedes


def test_a_new_handoff_supersedes_pending_handoffs_and_marks_them_read(store, vault):
    old = store.create_handoff(to="agent-b", summary="Old plan", context="c", namespace="alpha")

    new = store.create_handoff(to="agent-b", summary="New plan", context="c", namespace="alpha", supersedes=[old.id])

    assert [record.id for record in store.list_handoffs(namespace="alpha", status="pending")] == [new.id]
    old_after = next(record for record in store.list_handoffs(namespace="alpha") if record.id == old.id)
    assert old_after.meta["read"] is True
    assert old_after.meta["superseded_by"] == f"[[{new.path.removesuffix('.md')}]]"
    assert old_after.meta["revision"] == 2
    assert new.meta["supersedes"] == [f"[[{old.path.removesuffix('.md')}]]"]


def test_supersedes_validates_ids_before_writing_anything(store, vault):
    decision = store.save_memory(agent="a", kind="decision", title="D", content="c", namespace="alpha")
    other_namespace = store.save_memory(agent="a", kind="decision", title="E", content="c", namespace="beta")
    replacement = store.save_memory(
        agent="a", kind="decision", title="D2", content="c", namespace="alpha", supersedes=[decision.id]
    )
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
    with pytest.raises(VaultError, match="Record is not a handoff"):
        store.create_handoff(to="b", summary="s", context="c", namespace="alpha", supersedes=[replacement.id])

    assert {record.id for record in vault.scan().records} == before


# Redaction


def test_secrets_are_redacted_in_every_persisted_field(store, vault):
    context = store.save_context(
        agent="agent-a token=agent-secret",
        title="api_key=title-secret",
        content="Token is gho_abcdefghijklmnopqrstuvwxyz123456 and token=content-secret.",
        tags=["secret=tag-secret"],
    )
    handoff = store.create_handoff(
        to="agent-b token=to-secret", summary="api_key=summary-secret", context="token=context-secret"
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
    assert handoff.to == "agent-b token=[REDACTED_SECRET]"
    assert handoff.title == "Handoff to agent-b token=[REDACTED_SECRET]"
    assert handoff.content == "## Summary\napi_key=[REDACTED_SECRET]\n\n## Full Context\ntoken=[REDACTED_SECRET]"
    assert memory.agent == "agent-c token=[REDACTED_SECRET]"
    on_disk = "".join(read_text(vault, record) for record in (context, handoff, memory))
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
