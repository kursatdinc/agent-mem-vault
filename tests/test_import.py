import hashlib
import json

import pytest

from agent_vault_memory.cli import main
from agent_vault_memory.legacy import parse_store
from agent_vault_memory.store import Store
from conftest import TickingClock

FULL_CONTEXT_ID = "11111111-1111-4111-8111-111111111111"


def context_entry(**overrides):
    entry = {
        "id": FULL_CONTEXT_ID,
        "agent": "claude-code",
        "namespace": "project/alpha",
        "kind": "decision",
        "title": "Pick storage",
        "content": "Use Markdown files.",
        "tags": ["storage"],
        "timestamp": "2026-03-04T05:06:07.891Z",
        "type": "context",
        "status": "accepted",
        "relatedFiles": ["src/a.py"],
        "branch": "main",
        "commit": "abc1234",
        "nextAction": "Write docs",
    }
    return entry | overrides


def handoff_entry(entry_id, summary="Continue the work", **overrides):
    entry = {
        "id": entry_id,
        "agent": "handoff",
        "namespace": "alpha",
        "kind": "handoff",
        "to": "codex",
        "title": "Handoff to codex",
        "content": f"## Summary\n{summary}\n\n## Full Context\nDetails",
        "tags": ["handoff"],
        "timestamp": "2026-03-05T10:00:00.000Z",
        "type": "handoff",
        "read": False,
    }
    return entry | overrides


def write_source(tmp_path, entries, name="contexts.json"):
    source = tmp_path / name
    source.write_text(json.dumps({"contexts": entries}), encoding="utf-8")
    return source


def run_import(store, source, namespace_map=None):
    prepared, errors = parse_store(source, namespace_map or {})
    report = store.import_records(prepared)
    return report, errors + report.errors


def snapshot_of(vault):
    return {
        str(path.relative_to(vault.root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(vault.root.rglob("*.md"))
    }


def test_every_legacy_context_field_is_mapped_and_the_id_and_timestamp_are_kept(store, vault, tmp_path):
    source = write_source(tmp_path, [context_entry()])

    report, errors = run_import(store, source)

    assert (report.imported, report.skipped, report.superseded_marked, errors) == (1, 0, 0, [])
    text = (vault.root / f"project-alpha/decision/2026-03-04-pick-storage-{FULL_CONTEXT_ID[:8]}.md").read_text(
        encoding="utf-8"
    )
    assert text == (
        f"---\nid: {FULL_CONTEXT_ID}\nkind: decision\nnamespace: project/alpha\nagent: claude-code\n"
        "title: Pick storage\ncreated: 2026-03-04T05:06:07Z\nupdated: 2026-03-04T05:06:07Z\nrevision: 1\n"
        "visibility: internal\nvalidity: valid\ntags: [storage]\nstatus: accepted\nrelated_files: [src/a.py]\n"
        "next_action: Write docs\nbranch: main\ncommit: abc1234\nagent-written: true\n---\nUse Markdown files.\n"
    )


def test_handoffs_keep_their_destination_read_state_and_a_normalized_read_time(store, tmp_path):
    entries = [
        handoff_entry("aaaaaaaa-0000-4000-8000-00000000000a", read=True, readAt="2026-03-05T12:00:00+02:00"),
        handoff_entry("bbbbbbbb-0000-4000-8000-00000000000b", timestamp="2026-03-06T10:00:00Z", to="claude-code"),
    ]

    report, errors = run_import(store, write_source(tmp_path, entries))

    assert (report.imported, errors) == (2, [])
    read = next(record for record in store.list_handoffs("alpha", status="read"))
    assert (read.meta["to"], read.meta["read"], read.meta["read_at"], read.meta["updated"]) == (
        "codex",
        True,
        "2026-03-05T10:00:00Z",
        "2026-03-05T10:00:00Z",
    )
    assert read.content == "## Summary\nContinue the work\n\n## Full Context\nDetails"
    assert store.peek_handoff("claude-code", "alpha").id == "bbbbbbbb-0000-4000-8000-00000000000b"
    assert store.peek_handoff("codex", "alpha") is None


def test_missing_namespace_becomes_default_and_namespace_map_renames_namespaces(store, vault, tmp_path):
    entries = [
        context_entry(id="22222222-0000-4000-8000-000000000002", namespace=None, kind=None, title="No namespace"),
        context_entry(id="33333333-0000-4000-8000-000000000003", namespace="old", title="Renamed"),
        handoff_entry("44444444-0000-4000-8000-000000000004", namespace="old"),
    ]

    run_import(store, write_source(tmp_path, entries), {"old": "project/new"})

    assert sorted(path.name for path in (vault.root / "default" / "note").iterdir()) == [
        "2026-03-04-no-namespace-22222222.md"
    ]
    assert [record.title for record in store.list_contexts("project/new")] == ["Handoff to codex", "Renamed"]
    assert store.list_contexts("old") == []


def test_a_handoff_whose_summary_starts_with_supersedes_marks_the_referenced_pending_handoff(store, vault, tmp_path):
    older = "aaaaaaaa-0000-4000-8000-000000000001"
    newer = "bbbbbbbb-0000-4000-8000-000000000002"
    other_namespace = "aaaaaaaa-1111-4000-8000-000000000003"
    entries = [
        handoff_entry(newer, "Supersedes aaaaaaaa: take the new plan", timestamp="2026-03-06T10:00:00Z"),
        handoff_entry(other_namespace, namespace="beta", timestamp="2026-03-05T11:00:00Z"),
        handoff_entry(older),
    ]

    report, errors = run_import(store, write_source(tmp_path, entries))

    assert (report.imported, report.superseded_marked, errors) == (3, 1, [])
    records = {record.id: record for record in vault.scan().records}
    replacement_link = records[newer].path.removesuffix(".md")
    assert records[older].meta["superseded_by"] == f"[[{replacement_link}]]"
    assert (records[older].meta["read"], records[older].revision) == (True, 2)
    assert "read_at" in records[older].meta
    assert f"- Superseded by [[{replacement_link}|Handoff to codex]]" in records[older].related_lines
    assert records[newer].pending is True
    assert records[other_namespace].pending is True
    assert "superseded_by" not in records[other_namespace].meta
    assert [record.id for record in store.list_handoffs("alpha", status="pending")] == [newer]


def test_supersedes_is_ignored_for_read_targets_and_summaries_that_do_not_start_with_it(store, vault, tmp_path):
    read_target = "cccccccc-0000-4000-8000-000000000001"
    pending_target = "dddddddd-0000-4000-8000-000000000002"
    entries = [
        handoff_entry(
            "eeeeeeee-0000-4000-8000-000000000003", "Supersedes cccccccc now", timestamp="2026-03-07T10:00:00Z"
        ),
        handoff_entry(
            "ffffffff-0000-4000-8000-000000000004", "Plan: Supersedes dddddddd", timestamp="2026-03-07T11:00:00Z"
        ),
        handoff_entry(read_target, read=True, readAt="2026-03-05T12:00:00Z", timestamp="2026-03-05T10:00:00Z"),
        handoff_entry(pending_target, timestamp="2026-03-05T11:00:00Z"),
    ]

    report, errors = run_import(store, write_source(tmp_path, entries))

    assert (report.imported, report.superseded_marked, errors) == (4, 0, [])
    assert all("superseded_by" not in record.meta for record in vault.scan().records)


def test_an_ambiguous_supersedes_prefix_marks_nothing_and_is_reported(store, vault, tmp_path):
    entries = [
        handoff_entry("11112222-aaaa-4000-8000-000000000001", timestamp="2026-03-04T10:00:00Z"),
        handoff_entry("11112222-bbbb-4000-8000-000000000002", timestamp="2026-03-05T11:00:00Z"),
        handoff_entry("99999999-0000-4000-8000-000000000003", "Supersedes 11112222", timestamp="2026-03-06T10:00:00Z"),
    ]

    report, errors = run_import(store, write_source(tmp_path, entries))

    assert (report.imported, report.superseded_marked) == (3, 0)
    assert errors == ["99999999-0000-4000-8000-000000000003: Supersedes 11112222 matches 2 pending handoffs"]
    assert all("superseded_by" not in record.meta for record in vault.scan().records)


def test_importing_twice_skips_every_known_id_changes_no_file_and_never_touches_the_source(store, vault, tmp_path):
    entries = [
        handoff_entry("bbbbbbbb-0000-4000-8000-000000000002", "Supersedes aaaaaaaa", timestamp="2026-03-06T10:00:00Z"),
        handoff_entry("aaaaaaaa-0000-4000-8000-000000000001"),
        context_entry(),
    ]
    source = write_source(tmp_path, entries)
    source_bytes = source.read_bytes()

    first, _ = run_import(store, source)
    after_first = snapshot_of(vault)
    second, second_errors = run_import(store, source)

    assert (first.imported, first.skipped, first.superseded_marked) == (3, 0, 1)
    assert (second.imported, second.skipped, second.superseded_marked, second_errors) == (0, 3, 0, [])
    assert snapshot_of(vault) == after_first
    assert source.read_bytes() == source_bytes


def test_entries_that_cannot_be_imported_are_reported_and_the_rest_is_imported(store, tmp_path):
    entries = [
        context_entry(id="55555555-0000-4000-8000-000000000005", title="Fine"),
        "not an object",
        context_entry(id="66666666-0000-4000-8000-000000000006", kind="bogus"),
        context_entry(id="77777777-0000-4000-8000-000000000007", title=""),
        context_entry(id="88888888-0000-4000-8000-000000000008", timestamp="yesterday"),
        context_entry(id=None),
        handoff_entry("99999999-0000-4000-8000-000000000009", to=None),
        context_entry(id="55555555-0000-4000-8000-000000000005", title="Same id again"),
    ]

    report, errors = run_import(store, write_source(tmp_path, entries))

    assert (report.imported, report.skipped) == (1, 1)
    assert errors == [
        "entry 1: entry must be an object",
        "entry 2: unknown kind: bogus",
        "entry 3: title is required",
        "entry 4: timestamp must be a valid ISO 8601 date",
        "entry 5: id must be a string",
        "entry 6: to must be a string",
    ]
    assert store.list_contexts() == []
    assert len(store.list_contexts("project/alpha")) == 1


def test_entries_sharing_a_timestamp_keep_their_original_newest_first_order(store, tmp_path):
    same_second = "2026-03-04T05:06:07.100Z"
    entries = [
        context_entry(id="a0000000-0000-4000-8000-000000000001", title="Newest", timestamp="2026-03-04T05:06:07.900Z"),
        context_entry(id="a0000000-0000-4000-8000-000000000002", title="Middle", timestamp="2026-03-04T05:06:07.500Z"),
        context_entry(id="a0000000-0000-4000-8000-000000000003", title="Oldest", timestamp=same_second),
    ]

    run_import(store, write_source(tmp_path, entries))

    assert [record.title for record in store.list_contexts("project/alpha")] == ["Newest", "Middle", "Oldest"]


def test_the_import_refreshes_the_namespace_hubs(store, vault, tmp_path):
    run_import(store, write_source(tmp_path, [context_entry()]))

    hub = (vault.root / "project-alpha" / "_index.md").read_text(encoding="utf-8")
    assert (
        f"- [[project-alpha/decision/2026-03-04-pick-storage-{FULL_CONTEXT_ID[:8]}|Pick storage]] (2026-03-04)" in hub
    )


@pytest.mark.parametrize("content", ["not json", '{"contexts": "nope"}', "[]"])
def test_a_source_that_is_not_a_legacy_store_is_refused(tmp_path, content):
    source = tmp_path / "bad.json"
    source.write_text(content, encoding="utf-8")

    with pytest.raises(ValueError, match="cannot read|is not a shared-memory-mcp store"):
        parse_store(source, {})


def test_the_import_command_prints_the_counts_and_the_failed_entries(configured_vault, tmp_path, capsys):
    source = write_source(
        tmp_path,
        [context_entry(namespace="old"), context_entry(id="99999999-0000-4000-8000-000000000009", kind="bogus")],
    )

    first = main(["import", str(source), "--namespace-map", "old=project/new"])
    first_output = capsys.readouterr().out
    second = main(["import", str(source), "--namespace-map", "old=project/new"])
    second_output = capsys.readouterr().out

    assert first == second == 0
    assert first_output == "imported: 1\nskipped: 0\nsuperseded-marked: 0\nerrors: 1\n  entry 1: unknown kind: bogus\n"
    assert second_output == "imported: 0\nskipped: 1\nsuperseded-marked: 0\nerrors: 1\n  entry 1: unknown kind: bogus\n"
    assert [record.title for record in Store(configured_vault).list_contexts("project/new")] == ["Pick storage"]


def test_the_import_command_reports_an_unreadable_source_with_exit_code_two(configured_vault, tmp_path, capsys):
    assert main(["import", str(tmp_path / "missing.json")]) == 2
    assert "cannot read" in capsys.readouterr().err


def test_a_malformed_namespace_map_is_a_usage_error(configured_vault, tmp_path, capsys):
    with pytest.raises(SystemExit) as exit_info:
        main(["import", str(tmp_path / "x.json"), "--namespace-map", "no-equals-sign"])

    assert exit_info.value.code == 2
    assert "expected OLD=NEW" in capsys.readouterr().err


def test_the_supersede_mark_is_stamped_with_the_import_time_not_a_legacy_time(vault, tmp_path):
    ticking = Store(vault, clock=TickingClock())
    entries = [
        handoff_entry("bbbbbbbb-0000-4000-8000-000000000002", "Supersedes aaaaaaaa", timestamp="2026-03-06T10:00:00Z"),
        handoff_entry("aaaaaaaa-0000-4000-8000-000000000001"),
    ]

    run_import(ticking, write_source(tmp_path, entries))

    marked = next(record for record in vault.scan().records if record.id.startswith("aaaaaaaa"))
    assert (marked.meta["read_at"], marked.meta["updated"]) == ("2026-10-28T09:00:01Z", "2026-10-28T09:00:02Z")
