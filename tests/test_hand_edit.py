import pytest

from agent_vault_memory.vault import ConflictError


def test_search_reflects_a_body_edited_directly_in_the_file(store, vault):
    record = store.save_context(
        agent="agent-a", title="Release notes", content="Original wording about pelicans.", namespace="proj"
    )
    assert [found.id for found in store.search_memory(namespace="proj", query="pelicans")] == [record.id]
    assert store.search_memory(namespace="proj", query="albatross") == []

    path = vault.root / record.path
    path.write_text(path.read_text(encoding="utf-8").replace("pelicans", "albatross"), encoding="utf-8")

    assert store.search_memory(namespace="proj", query="pelicans") == []
    found = store.search_memory(namespace="proj", query="albatross")
    assert [item.id for item in found] == [record.id]
    assert found[0].content == "Original wording about albatross."


def test_a_frontmatter_key_added_by_a_human_survives_server_updates(store, vault):
    record = store.save_memory(agent="agent-a", kind="decision", title="Pick storage", content="c", namespace="proj")
    path = vault.root / record.path
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "agent-written: true\n", "agent-written: true\nreviewer: Dana\nscore: [1, 2]\n"
        ),
        encoding="utf-8",
    )

    updated = store.update_memory(record.id, title="Pick storage engine", status="accepted")

    assert updated.meta["reviewer"] == "Dana"
    assert updated.meta["score"] == [1, 2]
    on_disk = path.read_text(encoding="utf-8")
    assert "reviewer: Dana\n" in on_disk
    assert "score: [1, 2]\n" in on_disk
    assert on_disk.startswith("---\nid: ")


def test_a_record_with_broken_yaml_is_listed_as_an_issue_and_leaves_other_records_working(store, vault):
    healthy = store.save_context(agent="agent-a", title="Healthy", content="Still here.", namespace="proj")
    broken = vault.root / "proj" / "note" / "broken.md"
    broken.write_text("---\nid: [unclosed\ntitle: x\n---\nbody\n", encoding="utf-8")
    broken_before = broken.read_bytes()

    issues = store.list_issues()
    updated = store.update_memory(healthy.id, status="done")

    assert [(issue.path, issue.reason) for issue in issues] == [
        ("proj/note/broken.md", "unparseable frontmatter: ParserError")
    ]
    assert updated.meta["status"] == "done"
    assert [record.title for record in store.list_contexts(namespace="proj")] == ["Healthy"]
    assert broken.read_bytes() == broken_before


def test_every_kind_of_invalid_candidate_is_reported_with_its_reason_and_left_untouched(store, vault):
    first = store.save_context(agent="agent-a", title="Original", content="c", namespace="proj")
    note_dir = vault.root / "proj" / "note"
    valid = (vault.root / first.path).read_text(encoding="utf-8")
    candidates = {
        "no-frontmatter.md": "just text\n",
        "missing-id.md": "---\nkind: note\nnamespace: proj\n---\n",
        "missing-kind.md": f"---\nid: {first.id}x\nnamespace: proj\n---\n",
        "missing-namespace.md": f"---\nid: {first.id}y\nkind: note\n---\n",
        "unknown-kind.md": f"---\nid: {first.id}z\nkind: bogus\nnamespace: proj\n---\n",
        "zz-duplicate.md": valid,
    }
    for name, text in candidates.items():
        (note_dir / name).write_text(text, encoding="utf-8")

    reasons = {issue.path: issue.reason for issue in store.list_issues()}

    assert reasons == {
        "proj/note/no-frontmatter.md": "missing frontmatter",
        "proj/note/missing-id.md": "missing or invalid id",
        "proj/note/missing-kind.md": "missing or invalid kind",
        "proj/note/missing-namespace.md": "missing or invalid namespace",
        "proj/note/unknown-kind.md": "unknown kind: bogus",
        "proj/note/zz-duplicate.md": f"duplicate id (also at {first.path})",
    }
    for name, text in candidates.items():
        assert (note_dir / name).read_text(encoding="utf-8") == text


class EditingClock:
    """Time boundary that also lets a human edit the file at the moment the server is between read and write."""

    def __init__(self, inner, edit, times):
        self.inner = inner
        self.edit = edit
        self.times = times

    def __call__(self):
        if self.times:
            self.times -= 1
            self.edit()
        return self.inner()


def test_a_body_edited_between_the_servers_read_and_write_is_kept_after_one_retry(store, vault):
    record = store.save_context(agent="agent-a", title="Plan", content="Original.", namespace="proj")
    path = vault.root / record.path
    store.clock = EditingClock(
        store.clock, lambda: path.write_text(path.read_text(encoding="utf-8") + "\nHuman addition.\n"), times=1
    )

    updated = store.update_memory(record.id, status="done")

    on_disk = path.read_text(encoding="utf-8")
    assert updated.meta["status"] == "done"
    assert "Original.\n\nHuman addition." in on_disk
    assert updated.revision == 2


def test_a_body_edited_on_every_attempt_ends_in_a_conflict_and_nothing_is_overwritten(store, vault):
    record = store.save_context(agent="agent-a", title="Plan", content="Original.", namespace="proj")
    path = vault.root / record.path
    edits = iter(["\nFirst human edit.\n", "\nSecond human edit.\n"])
    store.clock = EditingClock(
        store.clock, lambda: path.write_text(path.read_text(encoding="utf-8") + next(edits)), times=2
    )

    with pytest.raises(ConflictError, match="was changed while updating it"):
        store.update_memory(record.id, title="Server title")

    on_disk = path.read_text(encoding="utf-8")
    assert "Original.\n\nFirst human edit.\n\nSecond human edit." in on_disk
    assert "title: Plan\n" in on_disk
    assert "revision: 1\n" in on_disk
    assert vault.tmp_leftovers() == []
