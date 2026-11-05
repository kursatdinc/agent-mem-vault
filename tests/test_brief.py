from datetime import timedelta

from agent_mem_vault.format import format_brief
from agent_mem_vault.records import render_record


def save(store, kind, title, **fields):
    return store.save_memory(agent="a", kind=kind, title=title, content="c", namespace="alpha", **fields)


def snapshot(store, title="State", content="Snapshot body.", **fields):
    return store.create_snapshot(agent="a", title=title, content=content, namespace="alpha", **fields)


def test_the_brief_shows_the_latest_snapshot_then_the_active_records_created_after_it(store):
    save(store, "decision", "Before the snapshot")
    snapshot(store, "Old state", "Old.")
    latest = snapshot(store, "Latest state", "Search API is ready.")
    decision = save(store, "decision", "Cache in Redis")
    risk = save(store, "risk", "Redis is a new service")

    brief = store.get_project_brief("alpha")

    assert brief.namespace == "alpha"
    assert brief.content == (
        f"## Snapshot: Latest state (2026-10-28, id {latest.id[:8]})\n"
        "Search API is ready.\n\n"
        "## Since the snapshot\n"
        f"- [risk] Redis is a new service - id {risk.id[:8]}\n"
        f"- [decision] Cache in Redis - id {decision.id[:8]}"
    )
    assert format_brief(brief) == f"**Project brief for alpha**\n\n{brief.content}"


def test_without_a_snapshot_the_active_records_are_listed_and_consolidation_is_due(store):
    note = save(store, "note", "Plain note")
    decision = save(store, "decision", "Use Markdown")

    assert store.get_project_brief("alpha").content == (
        "## Active records\n"
        f"- [decision] Use Markdown - id {decision.id[:8]}\n"
        f"- [note] Plain note - id {note.id[:8]}\n\n"
        "Consolidation due: no snapshot yet and 2 active records"
    )


def test_the_brief_of_an_empty_namespace_says_so_and_asks_for_no_consolidation(store):
    assert store.get_project_brief("nothing-here").content == "No saved memory found for namespace: nothing-here"


def test_closed_superseded_private_and_rejected_records_are_not_active(store, vault):
    old = save(store, "decision", "Old decision")
    current = save(store, "decision", "Current decision", supersedes=[old.id])
    save(store, "risk", "Resolved risk", status="resolved")
    mitigated = save(store, "risk", "Mitigated risk", status="mitigated")
    hidden = save(store, "note", "Private note")
    wrong = save(store, "note", "Rejected note")
    store.update_memory(hidden.id, visibility="private")
    store.update_memory(wrong.id, validity="rejected", rejected_reason="disproved")

    content = store.get_project_brief("alpha").content

    assert content.splitlines()[1:3] == [
        f"- [risk] Mitigated risk - id {mitigated.id[:8]}",
        f"- [decision] Current decision - id {current.id[:8]}",
    ]
    for gone in ("Old decision", "Resolved risk", "Private note", "Rejected note"):
        assert gone not in content


def test_a_superseded_private_or_rejected_snapshot_drops_out(store, vault):
    kept = snapshot(store, "Kept state")
    private = snapshot(store, "Private state")
    (vault.root / private.path).write_text(
        render_record({**private.meta, "visibility": "private"}, private.body), encoding="utf-8"
    )
    replaced = snapshot(store, "Replaced state")
    snapshot(store, "Replacement note", supersedes=[replaced.id])
    store.update_memory(store.list_contexts("alpha", kind="snapshot")[0].id, validity="rejected", rejected_reason="x")

    assert store.get_project_brief("alpha").content.startswith(
        f"## Snapshot: Kept state (2026-10-28, id {kept.id[:8]})"
    )


def test_consolidation_is_due_once_the_latest_snapshot_is_older_than_seven_days(store):
    snapshot(store)
    store.clock.moment += timedelta(days=7, seconds=-1)
    assert "Consolidation due" not in store.get_project_brief("alpha").content

    store.clock.moment += timedelta(seconds=5)
    assert store.get_project_brief("alpha").content.endswith(
        "Snapshot body.\n\nConsolidation due: latest snapshot is 7 days old"
    )
    store.clock.moment += timedelta(days=3)
    assert store.get_project_brief("alpha").content.endswith("Consolidation due: latest snapshot is 10 days old")


def test_the_limit_caps_the_listed_records_and_counts_the_rest(store):
    for index in range(4):
        save(store, "note", f"Note {index}")

    lines = store.get_project_brief("alpha", limit=2).content.splitlines()

    assert [line.split(" - ")[0] for line in lines[1:4]] == ["- [note] Note 3", "- [note] Note 2", "- ... and 2 more"]
    assert lines[-1] == "Consolidation due: no snapshot yet and 4 active records"


def test_the_companion_cards_open_the_brief_before_the_snapshot(companion_store):
    companion_store.create_snapshot(agent="a", title="State", content="Snapshot body.", namespace="alpha")
    companion_store.update_companion("alpha", last_session="Wired hooks.", threads="- main: wiring; next: test")

    content = companion_store.get_project_brief("alpha").content

    assert content.startswith(
        "## Last session\nWired hooks.\n\n## Threads\n- main: wiring; next: test\n\n## Snapshot: State (2026-10-28, id "
    )


def test_a_namespace_with_only_companion_cards_shows_them_without_consolidation(companion_store):
    companion_store.update_companion("alpha", last_session="Started.")

    assert companion_store.get_project_brief("alpha").content == "## Last session\nStarted."
