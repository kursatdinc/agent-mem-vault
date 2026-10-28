import pytest

from agent_vault_memory.vault import VaultError
from mcp_session import call, run_session

COMPANION_CONFIG = "features:\n  companion: true\ncompanion:\n  max_chars: 40\n"
LAST_SESSION_PATH = "project-demo/_companion/last-session.md"


def vault_files(vault):
    return sorted(str(path.relative_to(vault.root)) for path in vault.root.rglob("*") if path.is_file())


def test_updating_a_card_writes_a_companion_note_and_reading_returns_the_text(companion_store):
    companion_store.update_companion("project/demo", last_session="Wired hooks.", threads="Open: import CLI.")

    vault = companion_store.vault
    assert (vault.root / LAST_SESSION_PATH).read_text(encoding="utf-8") == (
        "---\nkind: companion\nnamespace: project/demo\nupdated: 2026-10-28T09:00:01Z\nagent-written: true\n---\n"
        "Wired hooks.\n"
    )
    assert (
        (vault.root / "project-demo/_companion/threads.md")
        .read_text(encoding="utf-8")
        .endswith("---\nOpen: import CLI.\n")
    )
    cards = companion_store.get_companion("project/demo")
    assert (cards.last_session, cards.threads) == ("Wired hooks.", "Open: import CLI.")


def test_a_card_is_replaced_wholesale_and_the_other_card_is_left_alone(companion_store):
    companion_store.update_companion(last_session="First.", threads="Keep me.")
    companion_store.update_companion(last_session="Second.")

    cards = companion_store.get_companion()
    assert (cards.last_session, cards.threads) == ("Second.", "Keep me.")
    assert companion_store.vault.tmp_leftovers() == []


def test_a_card_over_the_cap_is_refused_and_nothing_is_written_even_for_the_valid_card(companion_store):
    too_long = "x" * 41

    with pytest.raises(ValueError, match="threads is 41 characters, over the 40 character limit: compact it"):
        companion_store.update_companion(last_session="Fine.", threads=too_long)

    assert vault_files(companion_store.vault) == []
    companion_store.update_companion(last_session="x" * 40)
    assert companion_store.get_companion().last_session == "x" * 40


def test_an_update_without_any_card_is_refused(companion_store):
    with pytest.raises(ValueError, match="nothing to update: pass last_session or threads"):
        companion_store.update_companion()


def test_a_human_note_at_a_card_path_is_never_overwritten(companion_store):
    note = companion_store.vault.root / LAST_SESSION_PATH
    note.parent.mkdir(parents=True)
    note.write_text("my own notes\n", encoding="utf-8")

    with pytest.raises(VaultError, match="refusing to overwrite a file that is not generated"):
        companion_store.update_companion("project/demo", last_session="Mine now.")

    assert note.read_text(encoding="utf-8") == "my own notes\n"


def test_cards_are_not_records_and_do_not_show_up_as_issues(companion_store):
    companion_store.update_companion(last_session="Note.", threads="Threads.")

    scan = companion_store.vault.scan()

    assert (scan.records, scan.issues) == ([], [])


def test_the_brief_appends_the_last_session_card_but_not_the_threads_card(companion_store):
    companion_store.save_context(agent="a", title="Plan", content="Details.", namespace="alpha")
    companion_store.update_companion("alpha", last_session="Left off at hooks.", threads="Secret thread.")

    brief = companion_store.get_project_brief("alpha")

    assert brief.content == "- [note] Plan (a): Details.\n\n## Last session\nLeft off at hooks."


def test_the_card_is_appended_to_a_snapshot_brief_too(companion_store):
    companion_store.create_snapshot(agent="a", title="State", content="Snapshot body.", namespace="alpha")
    companion_store.update_companion("alpha", last_session="Resume here.")

    assert companion_store.get_project_brief("alpha").content == "Snapshot body.\n\n## Last session\nResume here."


def test_with_the_feature_off_cards_are_unavailable_and_the_brief_ignores_them(store):
    path = store.vault.root / "alpha/_companion/last-session.md"
    path.parent.mkdir(parents=True)
    path.write_text("---\nkind: companion\n---\nIgnored.\n", encoding="utf-8")

    with pytest.raises(VaultError, match="companion is disabled: set features.companion in the config"):
        store.update_companion(last_session="x")
    with pytest.raises(VaultError, match="companion is disabled"):
        store.get_companion()
    assert store.get_project_brief("alpha").content == "No saved memory found for namespace: alpha"


def test_companion_tools_are_registered_only_when_the_feature_is_on(tmp_path):
    async def tool_names(session):
        return {tool.name for tool in (await session.list_tools()).tools}

    off = run_session(tmp_path / "off", tool_names)
    on = run_session(tmp_path / "on", tool_names, COMPANION_CONFIG)

    assert not {"get_companion", "update_companion"} & off
    assert {"get_companion", "update_companion"} <= on


def test_companion_tools_over_stdio_reply_with_cards_and_a_compact_and_retry_error(tmp_path):
    async def scenario(session):
        replies = {"empty": await call(session, "get_companion", namespace="alpha")}
        replies["update"] = await call(
            session, "update_companion", namespace="alpha", last_session="Did X.", threads="Do Y."
        )
        replies["get"] = await call(session, "get_companion", namespace="alpha")
        over = await session.call_tool("update_companion", {"namespace": "alpha", "last_session": "y" * 41})
        replies["over"] = (over.is_error, over.content[0].text)
        replies["brief"] = await call(session, "get_project_brief", namespace="alpha")
        replies["kept"] = await call(session, "get_companion", namespace="alpha")
        return replies

    replies = run_session(tmp_path, scenario, COMPANION_CONFIG)

    assert replies["empty"] == "No companion cards yet."
    assert replies["update"] == "Companion updated."
    assert replies["get"] == "## Last session\nDid X.\n\n## Threads\nDo Y."
    assert replies["over"] == (
        True,
        "Error executing tool update_companion: last_session is 41 characters, over the 40 character limit: "
        "compact it and retry. Nothing was written.",
    )
    assert replies["brief"].endswith("No saved memory found for namespace: alpha\n\n## Last session\nDid X.")
    assert replies["kept"] == replies["get"]
