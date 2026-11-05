import pytest
import yaml

from agent_mem_vault.generated import DASHBOARD_RELPATH
from agent_mem_vault.records import render_record
from agent_mem_vault.vault import RevisionConflict, Vault, VaultError
from mcp_session import call, run_session


def text_of(vault, record):
    return (vault.root / record.path).read_text(encoding="utf-8")


def reread(store, record):
    return next(found for found in store.vault.scan().records if found.id == record.id)


def save(store, kind, title="T", **fields):
    return store.save_memory(agent="a", kind=kind, title=title, content="c", namespace="alpha", **fields)


# Status per kind


def test_decisions_and_risks_get_their_first_status_by_default_and_other_kinds_none(store):
    assert save(store, "decision").meta["status"] == "accepted"
    assert save(store, "risk").meta["status"] == "open"
    assert "status" not in save(store, "note").meta
    assert save(store, "task", status="in progress").meta["status"] == "in progress"


@pytest.mark.parametrize(
    ("kind", "status", "message"),
    [
        ("decision", "proposed", "status of a decision must be one of: accepted, superseded"),
        ("decision", "open", "status of a decision must be one of: accepted, superseded"),
        ("risk", "accepted", "status of a risk must be one of: open, mitigated, resolved"),
        ("risk", "done", "status of a risk must be one of: open, mitigated, resolved"),
    ],
)
def test_a_status_outside_the_kind_lifecycle_is_refused_on_save_and_on_update(store, vault, kind, status, message):
    with pytest.raises(ValueError, match=message):
        save(store, kind, status=status)
    record = save(store, kind)
    before = text_of(vault, record)

    with pytest.raises(ValueError, match=message):
        store.update_memory(record.id, status=status)

    assert text_of(vault, record) == before


def test_update_moves_a_risk_through_its_lifecycle(store):
    risk = save(store, "risk")

    assert store.update_memory(risk.id, status="mitigated").meta["status"] == "mitigated"
    assert store.update_memory(risk.id, status="resolved").meta["status"] == "resolved"


def test_a_hand_written_legacy_status_does_not_block_other_updates(store, vault):
    decision = save(store, "decision")
    (vault.root / decision.path).write_text(
        render_record({**decision.meta, "status": "proposed"}, decision.body), encoding="utf-8"
    )

    updated = store.update_memory(decision.id, title="Renamed")

    assert (updated.title, updated.meta["status"]) == ("Renamed", "proposed")


# Hand-written review date


def test_a_hand_written_review_by_still_loads_and_survives_an_update_in_place(store, vault):
    risk = save(store, "risk", "Lock time")
    (vault.root / risk.path).write_text(
        render_record({**risk.meta, "review_by": "2026-12-01"}, risk.body), encoding="utf-8"
    )

    updated = store.update_memory(risk.id, status="mitigated")

    assert reread(store, risk).meta["review_by"] == "2026-12-01"
    assert updated.meta["status"] == "mitigated"
    assert "status: mitigated\nreview_by: 2026-12-01\n" in text_of(vault, risk)


# Supersedes


def test_superseding_closes_decisions_and_resolves_risks_and_leaves_other_statuses_alone(store):
    decision = save(store, "decision", "Old decision")
    risk = save(store, "risk", "Old risk", status="mitigated")
    task = save(store, "task", "Old task", status="in progress")

    replacement = save(store, "decision", "New decision", supersedes=[decision.id, risk.id, task.id])

    assert reread(store, decision).meta["status"] == "superseded"
    assert reread(store, risk).meta["status"] == "resolved"
    assert reread(store, task).meta["status"] == "in progress"
    for old in (decision, risk, task):
        assert reread(store, old).meta["superseded_by"] == f"[[{replacement.path.removesuffix('.md')}]]"


def test_update_memory_can_supersede_records_and_extends_the_supersedes_list(store, vault):
    first = save(store, "decision", "First")
    second = save(store, "risk", "Second")
    keeper = save(store, "decision", "Keeper", supersedes=[first.id])

    updated = store.update_memory(keeper.id, expected_revision=1, supersedes=[second.id])

    assert updated.revision == 2
    assert updated.meta["supersedes"] == [
        f"[[{first.path.removesuffix('.md')}]]",
        f"[[{second.path.removesuffix('.md')}]]",
    ]
    assert updated.related_lines == [
        f"- Supersedes [[{first.path.removesuffix('.md')}|First]]",
        f"- Supersedes [[{second.path.removesuffix('.md')}|Second]]",
    ]
    assert reread(store, second).meta["status"] == "resolved"
    assert updated.content == "c"


def test_update_memory_supersedes_validates_before_writing_anything(store, vault):
    record = save(store, "decision", "Keeper")
    gone = save(store, "decision", "Gone")
    save(store, "decision", "Replacement", supersedes=[gone.id])
    fresh = save(store, "risk", "Fresh")
    before = {found.path: text_of(vault, found) for found in vault.scan().records}

    with pytest.raises(VaultError, match="A record cannot supersede itself"):
        store.update_memory(record.id, supersedes=[record.id])
    with pytest.raises(VaultError, match="Record is already superseded"):
        store.update_memory(record.id, supersedes=[gone.id])
    with pytest.raises(VaultError, match="Record not found in namespace alpha: missing-id"):
        store.update_memory(record.id, supersedes=["missing-id"])
    with pytest.raises(RevisionConflict):
        store.update_memory(record.id, expected_revision=7, supersedes=[fresh.id[:8]])

    assert {found.path: text_of(vault, found) for found in vault.scan().records} == before


def test_a_snapshot_can_supersede_the_previous_snapshot(store):
    old = store.create_snapshot(agent="a", title="Old state", content="Old.", namespace="alpha")

    new = store.create_snapshot(agent="a", title="New state", content="New.", namespace="alpha", supersedes=[old.id])

    assert new.meta["supersedes"] == [f"[[{old.path.removesuffix('.md')}]]"]
    assert reread(store, old).meta["superseded_by"] == f"[[{new.path.removesuffix('.md')}]]"
    assert "status" not in reread(store, old).meta


# Closed records


def save_cache_history(store):
    old = save(store, "decision", "Old cache plan")
    save(store, "decision", "New cache plan", supersedes=[old.id])
    save(store, "risk", "Cache stampede", status="resolved")
    save(store, "risk", "Cache warmup", status="mitigated")
    replaced = save(store, "task", "Cache task", status="in progress")
    save(store, "task", "Cache task v2", supersedes=[replaced.id])
    save(store, "decision", "Cache hand-closed", status="superseded")


def titles(records):
    return [record.title for record in records]


ALL_CACHE_TITLES = [
    "Cache hand-closed",
    "Cache task v2",
    "Cache task",
    "Cache warmup",
    "Cache stampede",
    "New cache plan",
    "Old cache plan",
]


def test_list_and_search_hide_superseded_resolved_and_replaced_records_unless_asked(store):
    save_cache_history(store)

    assert titles(store.list_contexts("alpha")) == ["Cache task v2", "Cache warmup", "New cache plan"]
    assert titles(store.search_memory("alpha", "cache")) == ["Cache task v2", "Cache warmup", "New cache plan"]
    assert titles(store.list_contexts("alpha", kind="decision")) == ["New cache plan"]
    assert titles(store.list_contexts("alpha", include_closed=True)) == ALL_CACHE_TITLES
    assert titles(store.search_memory("alpha", "cache", include_closed=True)) == ALL_CACHE_TITLES
    assert titles(store.search_memory("alpha", kind="decision", include_closed=True)) == [
        "Cache hand-closed",
        "New cache plan",
        "Old cache plan",
    ]


def test_include_closed_is_exposed_over_stdio_and_off_by_default(tmp_path):
    async def scenario(session):
        tools = {tool.name: tool for tool in (await session.list_tools()).tools}
        decision = {"agent": "a", "kind": "decision", "content": "c", "namespace": "alpha"}
        old = await call(session, "save_memory", title="Old plan", **decision)
        await call(session, "save_memory", title="New plan", supersedes=[old.rsplit(" ", 1)[1]], **decision)
        replies = {
            "list": await call(session, "list_contexts", namespace="alpha"),
            "list_closed": await call(session, "list_contexts", namespace="alpha", include_closed=True),
            "search": await call(session, "search_memory", namespace="alpha", query="plan"),
            "search_closed": await call(session, "search_memory", namespace="alpha", query="plan", include_closed=True),
        }
        return tools, replies

    tools, replies = run_session(tmp_path, scenario)

    for name in ("list_contexts", "search_memory"):
        parameter = tools[name].input_schema["properties"]["include_closed"]
        assert (parameter["type"], parameter["default"]) == ("boolean", False)
    entries = {
        key: sorted(line.split(" - ")[0].split(" ", 1)[1] for line in reply.splitlines())
        for key, reply in replies.items()
    }
    assert entries["list"] == entries["search"] == ["[decision: accepted] (alpha) New plan"]
    assert (
        entries["list_closed"]
        == entries["search_closed"]
        == [
            "[decision: accepted] (alpha) New plan",
            "[decision: superseded] (alpha) Old plan",
        ]
    )


# Short ids


def write_record(vault, record_id, title):
    folder = vault.root / "alpha" / "decision"
    folder.mkdir(parents=True, exist_ok=True)
    meta = {
        "id": record_id,
        "kind": "decision",
        "namespace": "alpha",
        "title": title,
        "created": "2026-10-01T09:00:00Z",
    }
    (folder / f"2026-10-01-{title.lower()}-{record_id[:8]}.md").write_text(render_record(meta, "c\n"), encoding="utf-8")


def test_an_eight_character_prefix_is_accepted_wherever_an_id_is_taken(store):
    old = save(store, "decision", "Old")
    record = save(store, "decision", "Current", supersedes=[old.id[:8]])

    assert store.update_memory(record.id[:8], title="Current, renamed").title == "Current, renamed"
    assert store.get_links(record.id[:8])[0].id == record.id
    assert reread(store, old).meta["status"] == "superseded"


def test_a_prefix_shorter_than_eight_characters_is_not_an_id(store):
    record = save(store, "decision")

    assert store.update_memory(record.id[:7], title="Ghost") is None
    with pytest.raises(VaultError, match=f"Record not found in namespace alpha: {record.id[:7]}"):
        save(store, "decision", supersedes=[record.id[:7]])


def test_an_ambiguous_prefix_is_refused_with_the_number_of_matches(store, vault):
    write_record(vault, "abcdef12-0000-4000-8000-000000000001", "One")
    write_record(vault, "abcdef12-0000-4000-8000-000000000002", "Two")

    with pytest.raises(VaultError, match="id prefix abcdef12 matches 2 records: pass more characters"):
        store.update_memory("abcdef12", title="Which")
    assert store.update_memory("abcdef12-0000-4000-8000-000000000002", title="Exact").title == "Exact"


# Dashboard and tools


def test_the_dashboard_lists_only_active_decisions_and_risks(store, vault):
    save(store, "note")

    decisions = yaml.safe_load((vault.root / DASHBOARD_RELPATH).read_text(encoding="utf-8"))["views"][0]

    assert decisions["name"] == "Active decisions and risks"
    assert decisions["filters"] == {
        "and": [
            {"or": ['note.kind == "decision"', 'note.kind == "risk"']},
            'note.validity == "valid"',
            'note.status != "superseded"',
            'note.status != "resolved"',
        ]
    }
    assert decisions["order"] == ["file.name", "note.kind", "note.status", "note.created"]


def test_the_lifecycle_parameters_are_exposed_and_validated_over_stdio(tmp_path):
    async def scenario(session):
        tools = {tool.name: tool for tool in (await session.list_tools()).tools}
        saved = await call(
            session,
            "save_memory",
            agent="a",
            kind="risk",
            title="Lock time",
            content="c",
            namespace="alpha",
            review_by="2026-12-01",
        )
        record_id = saved.rsplit(" ", 1)[1]
        bad = await session.call_tool("update_memory", {"id": record_id[:8], "status": "accepted"})
        good = await call(session, "update_memory", id=record_id[:8], status="mitigated", review_by="2027-01-01")
        return tools, bad, good, record_id

    tools, bad, good, record_id = run_session(tmp_path, scenario)

    [risk] = Vault(tmp_path / "vault").scan().records
    assert "review_by" not in tools["save_memory"].input_schema["properties"]
    assert "review_by" not in tools["update_memory"].input_schema["properties"]
    assert "supersedes" in tools["update_memory"].input_schema["properties"]
    assert "supersedes" in tools["create_snapshot"].input_schema["properties"]
    assert bad.is_error is True
    assert bad.content[0].text == (
        "Error executing tool update_memory: status of a risk must be one of: open, mitigated, resolved"
    )
    assert good == f"Memory updated. ID: {record_id}. Revision: 2"
    assert risk.meta["status"] == "mitigated"
    assert "review_by" not in risk.meta
