import pytest

from agent_mem_vault.vault import RevisionConflict


def file_text(vault, record):
    return (vault.root / record.path).read_text(encoding="utf-8")


def saved_decision(store, **overrides):
    arguments = {
        "agent": "agent-a",
        "kind": "decision",
        "title": "Pick storage",
        "content": "Use Markdown files.",
        "namespace": "alpha",
        "tags": ["storage"],
        "status": "proposed",
    } | overrides
    return store.save_memory(**arguments)


def test_update_changes_fields_bumps_revision_and_never_renames_the_file(store, vault):
    record = saved_decision(store)

    updated = store.update_memory(
        record.id,
        title="Pick storage engine",
        content="Use Markdown files in an Obsidian vault.",
        tags=["storage", "obsidian"],
        status="accepted",
        visibility="private",
    )

    assert updated.path == record.path
    assert [path.name for path in (vault.root / "alpha" / "decision").iterdir()] == [record.path.rsplit("/", 1)[1]]
    assert updated.title == "Pick storage engine"
    assert updated.content == "Use Markdown files in an Obsidian vault."
    assert updated.tags == ["storage", "obsidian"]
    assert updated.meta["status"] == "accepted"
    assert updated.meta["visibility"] == "private"
    assert updated.revision == 2
    assert updated.meta["updated"] == "2026-10-28T09:00:02Z"
    assert updated.meta["created"] == record.meta["created"]
    assert (updated.id, updated.kind, updated.namespace) == (record.id, "decision", "alpha")


def test_update_keeps_the_related_block_and_replaces_only_the_content(store, vault):
    old = saved_decision(store, title="Old choice")
    new = saved_decision(store, title="New choice", supersedes=[old.id])

    updated = store.update_memory(new.id, content="Revised reasoning.")

    text = file_text(vault, updated)
    assert updated.content == "Revised reasoning."
    assert f"- Supersedes [[{old.path.removesuffix('.md')}|Old choice]]" in text
    assert updated.meta["supersedes"] == [f"[[{old.path.removesuffix('.md')}]]"]


def test_a_stale_expected_revision_returns_a_conflict_naming_the_current_revision_and_writes_nothing(store, vault):
    record = saved_decision(store)
    store.update_memory(record.id, status="accepted")
    before = file_text(vault, record)

    with pytest.raises(RevisionConflict) as conflict:
        store.update_memory(record.id, expected_revision=1, title="Lost update")

    assert (conflict.value.expected, conflict.value.current) == (1, 2)
    assert str(conflict.value) == "expected revision 1 but the current revision is 2"
    assert file_text(vault, record) == before


def test_a_matching_expected_revision_is_accepted(store):
    record = saved_decision(store)

    updated = store.update_memory(record.id, expected_revision=1, status="accepted")

    assert updated.revision == 2


def test_rejecting_requires_a_reason_and_a_valid_again_record_drops_it(store, vault):
    record = saved_decision(store)
    before = file_text(vault, record)

    with pytest.raises(ValueError, match="rejected_reason is required when validity is rejected"):
        store.update_memory(record.id, validity="rejected")
    assert file_text(vault, record) == before

    rejected = store.update_memory(record.id, validity="rejected", rejected_reason="Superseded by a better plan")
    assert rejected.meta["validity"] == "rejected"
    assert rejected.meta["rejected_reason"] == "Superseded by a better plan"
    assert "Pick storage" not in store.get_project_brief("alpha").content

    restored = store.update_memory(record.id, validity="valid")
    assert restored.meta["validity"] == "valid"
    assert "rejected_reason" not in restored.meta


def test_a_reason_without_rejection_is_refused(store):
    record = saved_decision(store)

    with pytest.raises(ValueError, match="rejected_reason is only allowed when validity is rejected"):
        store.update_memory(record.id, rejected_reason="Because")


def test_an_update_without_fields_an_unknown_id_and_bad_choices_are_handled(store, vault):
    record = saved_decision(store)
    before = file_text(vault, record)

    with pytest.raises(ValueError, match="nothing to update"):
        store.update_memory(record.id)
    with pytest.raises(ValueError, match="visibility must be one of: public, internal, private"):
        store.update_memory(record.id, visibility="secret")
    with pytest.raises(ValueError, match="validity must be one of: valid, rejected"):
        store.update_memory(record.id, validity="maybe")
    assert store.update_memory("00000000-0000-0000-0000-000000000000", title="Ghost") is None
    assert file_text(vault, record) == before


def test_empty_tags_clear_the_tags_and_secrets_in_updates_are_redacted(store):
    record = saved_decision(store)

    cleared = store.update_memory(record.id, tags=[])
    redacted = store.update_memory(record.id, content="Rotate password=hunter2 today.")

    assert "tags" not in cleared.meta
    assert redacted.content == "Rotate password=[REDACTED_SECRET] today."


def test_an_update_regenerates_the_hub_with_the_new_title(store, vault):
    record = saved_decision(store)

    store.update_memory(record.id, title="Pick storage engine")

    hub = (vault.root / "alpha" / "alpha.md").read_text(encoding="utf-8")
    assert f"- [[{record.path.removesuffix('.md')}|Pick storage engine]] (2026-10-28)" in hub
    assert "Pick storage]]" not in hub
