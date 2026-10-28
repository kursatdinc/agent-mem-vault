from agent_vault_memory.cli import main
from agent_vault_memory.format import format_records
from agent_vault_memory.store import Store
from conftest import TickingClock
from mcp_session import call, run_session


def titles(records):
    return [record.title for record in records]


def seed(store):
    store.save_context(agent="a", title="Public pelican", content="Pelicans are shared.", namespace="alpha")
    secret = store.save_context(agent="a", title="Private pelican", content="Pelicans are secret.", namespace="alpha")
    store.update_memory(secret.id, visibility="private")
    return secret


def test_private_records_are_hidden_from_list_search_and_latest_unless_requested(store):
    secret = seed(store)

    assert titles(store.list_contexts("alpha")) == ["Public pelican"]
    assert titles(store.search_memory("alpha", "pelican")) == ["Public pelican"]
    assert store.get_last_context("alpha").title == "Public pelican"
    assert titles(store.list_contexts("alpha", include_private=True)) == ["Private pelican", "Public pelican"]
    assert titles(store.search_memory("alpha", "pelican", include_private=True)) == [
        "Private pelican",
        "Public pelican",
    ]
    assert store.get_last_context("alpha", include_private=True).id == secret.id


def test_with_the_feature_off_private_records_are_listed_without_asking(vault):
    unfiltered = Store(vault, clock=TickingClock(), visibility_filter=False)
    seed(unfiltered)

    assert titles(unfiltered.list_contexts("alpha")) == ["Private pelican", "Public pelican"]
    assert titles(unfiltered.search_memory("alpha", "secret")) == ["Private pelican"]
    assert unfiltered.get_last_context("alpha").title == "Private pelican"


def test_private_and_rejected_records_stay_out_of_the_brief_in_both_states(vault):
    for visibility_filter in (True, False):
        store = Store(vault, clock=TickingClock(), visibility_filter=visibility_filter)
        namespace = f"brief-{visibility_filter}"
        store.save_context(agent="a", title="Visible", content="ok", namespace=namespace)
        hidden = store.save_context(agent="a", title="Hidden", content="no", namespace=namespace)
        store.update_memory(hidden.id, visibility="private")
        bad = store.save_context(agent="a", title="Wrong", content="no", namespace=namespace)
        store.update_memory(bad.id, validity="rejected", rejected_reason="superseded by facts")

        assert store.get_project_brief(namespace).content == "- [note] Visible (a): ok"


def test_rejected_records_are_marked_in_listings_only_when_asked_to(store):
    bad = store.save_context(agent="a", title="Wrong claim", content="c", namespace="alpha")
    store.update_memory(bad.id, validity="rejected", rejected_reason="disproved")
    records = store.list_contexts("alpha")

    marked = format_records(records, mark_rejected=True)
    plain = format_records(records)

    assert marked.startswith("1. [context/note [rejected]] (alpha) Wrong claim - a - ")
    assert plain.startswith("1. [context/note] (alpha) Wrong claim - a - ")


def test_visibility_is_applied_over_stdio_with_the_optional_include_private_parameter(tmp_path):
    async def scenario(session):
        replies = {}
        tools = {tool.name: tool for tool in (await session.list_tools()).tools}
        replies["params"] = {
            name: tools[name].input_schema["properties"].get("include_private")
            for name in ("list_contexts", "search_memory", "read_latest_context")
        }
        for title, content in (
            ("Public pelican", "Shared."),
            ("Private pelican", "Secret."),
            ("Wrong pelican", "Bad."),
        ):
            saved = await call(session, "save_context", agent="a", title=title, content=content, namespace="alpha")
            replies[title] = saved.rsplit(" ", 1)[1]
        await call(session, "update_memory", id=replies["Private pelican"], visibility="private")
        await call(
            session, "update_memory", id=replies["Wrong pelican"], validity="rejected", rejected_reason="disproved"
        )
        replies["list"] = await call(session, "list_contexts", namespace="alpha")
        replies["list_private"] = await call(session, "list_contexts", namespace="alpha", include_private=True)
        replies["search"] = await call(session, "search_memory", namespace="alpha", query="pelican")
        replies["latest"] = await call(session, "read_latest_context", namespace="alpha")
        replies["latest_private"] = await call(session, "read_latest_context", namespace="alpha", include_private=True)
        replies["brief"] = await call(session, "get_project_brief", namespace="alpha")
        return replies

    replies = run_session(tmp_path, scenario)

    assert all(param["type"] == "boolean" and param["default"] is False for param in replies["params"].values())
    assert [line.split(" - ")[0] for line in replies["list"].splitlines()] == [
        "1. [context/note [rejected]] (alpha) Wrong pelican",
        "2. [context/note] (alpha) Public pelican",
    ]
    assert [line.split(" - ")[0] for line in replies["list_private"].splitlines()] == [
        "1. [context/note [rejected]] (alpha) Wrong pelican",
        "2. [context/note] (alpha) Private pelican",
        "3. [context/note] (alpha) Public pelican",
    ]
    assert replies["search"].count("\n") == 1
    assert "Private pelican" not in replies["search"]
    assert replies["latest"].startswith("**Wrong pelican**")
    assert replies["latest_private"].startswith("**Wrong pelican**")
    assert replies["brief"].endswith("- [note] Public pelican (a): Shared.")
    assert "Private" not in replies["brief"] and "Wrong" not in replies["brief"]


def test_the_cli_hides_private_records_unless_include_private_is_passed(configured_vault, capsys):
    seed(Store(configured_vault))

    assert main(["list", "--namespace", "alpha"]) == 0
    hidden = capsys.readouterr().out.splitlines()
    assert main(["list", "--namespace", "alpha", "--include-private"]) == 0
    shown = capsys.readouterr().out.splitlines()
    assert main(["search", "pelican", "--namespace", "alpha", "--include-private"]) == 0
    searched = capsys.readouterr().out.splitlines()

    assert [line.split(" - ")[0] for line in hidden] == ["1. [context/note] (alpha) Public pelican"]
    assert len(shown) == len(searched) == 2
