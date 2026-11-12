from agent_mem_vault.store import Store
from agent_mem_vault.vault import Vault
from conftest import TickingClock
from mcp_session import call, run_session


def test_get_memories_returns_each_record_in_request_order_and_none_for_an_unknown_id(store):
    first = store.save_memory(agent="a", kind="decision", title="First", content="Body one.", namespace="p")
    second = store.save_memory(agent="a", kind="risk", title="Second", content="Body two.", namespace="p")

    found = store.get_memories([second.id, "nope", first.id[:8]])

    assert [record.title if record else None for record in found] == ["Second", None, "First"]
    assert found[0].content == "Body two."


def test_get_memories_reads_a_closed_record_by_id(store):
    old = store.save_memory(agent="a", kind="decision", title="Old", content="x", namespace="p")
    store.save_memory(agent="a", kind="decision", title="New", content="y", namespace="p", supersedes=[old.id])

    assert store.get_memories([old.id])[0].title == "Old"


def test_get_memories_hides_a_private_record_unless_asked(tmp_path):
    root = tmp_path / "vault"
    root.mkdir()
    store = Store(Vault(root), clock=TickingClock(), visibility_filter=True)
    record = store.save_memory(agent="a", kind="note", title="Private plan", content="x", namespace="p")
    store.update_memory(record.id, visibility="private")

    assert store.get_memories([record.id]) == [None]
    assert store.get_memories([record.id], include_private=True)[0].title == "Private plan"


def test_a_search_by_id_prefix_finds_the_record_whatever_the_text_says(store):
    target = store.save_memory(agent="a", kind="decision", title="Pick storage", content="Plain.", namespace="p")
    store.save_memory(agent="a", kind="decision", title="Other", content=target.short_id, namespace="p")

    found = store.search_memory(namespace="p", query=target.short_id.upper())

    assert [record.title for record in found] == ["Pick storage"]


def test_a_hex_looking_query_that_is_no_id_is_searched_as_text(store):
    store.save_context(agent="a", title="Build deadbeef", content="x", namespace="p")

    assert [record.title for record in store.search_memory(namespace="p", query="deadbeef")] == ["Build deadbeef"]


def test_the_get_memory_tool_replies_with_the_full_record_and_names_a_missing_id(tmp_path):
    async def scenario(session):
        saved = await call(
            session,
            "save_memory",
            agent="claude-code",
            kind="decision",
            title="Pick storage",
            content="Use files.\n\nNo database.",
            namespace="alpha",
            status="accepted",
        )
        record_id = saved.rsplit(" ", 1)[1]
        found = await call(session, "get_memory", ids=[record_id[:8], "missing1"])
        empty = await session.call_tool("get_memory", {"ids": []})
        return record_id, found, empty.is_error

    record_id, found, empty_is_error = run_session(tmp_path, scenario)

    record, missing = found.split("\n\n---\n\n")
    heading, body = record.split("\n\n", 1)
    assert heading.startswith("**Pick storage** - [decision: accepted] (alpha) - claude-code - ")
    assert heading.endswith(f" - id {record_id[:8]} - revision 1")
    assert body == "Use files.\n\nNo database."
    assert missing == "Memory not found: missing1"
    assert empty_is_error is True
