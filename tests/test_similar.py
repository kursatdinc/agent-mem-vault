import re

from agent_mem_vault.store import SIMILAR_LIMIT
from mcp_session import call, run_session

SAVED = r"Memory saved with ID: [0-9a-f-]{36}"


def titles(records):
    return [record.title for record in records]


def decision(store, title, content="c", namespace="p", **fields):
    return store.save_memory(agent="a", kind="decision", title=title, content=content, namespace=namespace, **fields)


def test_a_similar_record_holds_most_of_the_title_words_and_one_of_them_in_its_own_title(store):
    decision(store, "Cache layout uses two shards")
    decision(store, "Release notes", content="Cache layout uses three shards.")
    decision(store, "Queue retry policy")
    new = decision(store, "Cache layout uses three shards")
    assert titles(store.similar_records(new)) == ["Cache layout uses two shards"]


def test_the_aliases_of_the_new_record_count_as_title_words(store):
    plain = decision(store, "Agent runtime upgrade", namespace="q")
    decision(store, "ADK runtime upgrade", namespace="q")
    named = decision(store, "Agent runtime upgrade", namespace="r", aliases=["ADK"])
    decision(store, "ADK runtime upgrade", namespace="r")
    assert store.similar_records(plain) == []
    assert titles(store.similar_records(named)) == ["ADK runtime upgrade"]


def test_similar_records_leave_out_closed_private_snapshot_and_own_records(store):
    decision(store, "Cache layout uses two shards")
    closed = decision(store, "Cache layout uses one shard")
    private = decision(store, "Cache layout uses six shards")
    store.update_memory(private.id, visibility="private")
    store.create_snapshot(agent="a", title="Cache layout uses five shards", content="c", namespace="p")
    new = decision(store, "Cache layout uses four shards", supersedes=[closed.id])
    assert titles(store.similar_records(new)) == ["Cache layout uses two shards"]


def test_similar_records_are_capped(store):
    for number in ("two", "three", "four", "five"):
        decision(store, f"Cache layout uses {number} shards")
    new = decision(store, "Cache layout uses six shards")
    assert len(store.similar_records(new)) == SIMILAR_LIMIT


def test_save_memory_replies_with_the_id_and_then_the_similar_active_records(tmp_path):
    async def scenario(session):
        fields = {"agent": "a", "kind": "decision", "content": "c", "namespace": "alpha"}
        first = await call(session, "save_memory", title="Cache layout uses two shards", **fields)
        second = await call(session, "save_memory", title="Cache layout uses three shards", **fields)
        ids = [reply.splitlines()[0].rsplit(" ", 1)[1] for reply in (first, second)]
        third = await call(session, "save_memory", title="Cache layout uses four shards", supersedes=ids, **fields)
        return first, second, third

    first, second, third = run_session(tmp_path, scenario)
    assert re.fullmatch(SAVED, first)
    saved, heading, listed = second.splitlines()
    assert re.fullmatch(SAVED, saved)
    assert "update_memory" in heading and "supersedes" in heading
    assert "Cache layout uses two shards" in listed
    assert re.fullmatch(SAVED, third)
