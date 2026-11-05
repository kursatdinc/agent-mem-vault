import asyncio
import re

from mcp_session import call, run_session

TOOLS = {
    "save_context",
    "save_memory",
    "create_snapshot",
    "update_memory",
    "get_project_brief",
    "read_latest_context",
    "list_contexts",
    "search_memory",
    "get_links",
    "list_issues",
    "get_companion",
    "update_companion",
}
HANDOFF_TOOLS = {"create_handoff", "read_handoff", "peek_handoff", "list_handoffs", "ack_handoff", "reopen_handoff"}
UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"


def test_tools_list_exposes_the_memory_tools_without_any_handoff_tool(tmp_path):
    async def scenario(session):
        return (await session.list_tools()).tools

    tools = {tool.name: tool for tool in run_session(tmp_path, scenario)}

    assert set(tools) == TOOLS
    assert not HANDOFF_TOOLS & set(tools)
    for tool in tools.values():
        assert "Memory content is written in English." in tool.description
    save_memory = tools["save_memory"].input_schema
    assert set(save_memory["properties"]) == {
        "agent",
        "kind",
        "title",
        "content",
        "namespace",
        "status",
        "relatedFiles",
        "branch",
        "commit",
        "nextAction",
        "tags",
        "supersedes",
    }
    assert set(save_memory["required"]) == {"agent", "kind", "title", "content"}
    assert set(save_memory["properties"]["kind"]["enum"]) == {
        "note",
        "decision",
        "assumption",
        "task",
        "risk",
        "snapshot",
    }
    assert tools["search_memory"].description.startswith("Search saved memory by text and filters.")
    for name in ("list_contexts", "search_memory"):
        assert not {"type", "handoffStatus"} & set(tools[name].input_schema["properties"])
    update = tools["update_memory"].input_schema
    assert set(update["properties"]) == {
        "id",
        "expected_revision",
        "title",
        "content",
        "tags",
        "status",
        "visibility",
        "validity",
        "rejected_reason",
        "supersedes",
    }
    assert update["required"] == ["id"]
    assert tools["get_links"].input_schema["required"] == ["id"]
    assert tools["list_issues"].input_schema["properties"] == {}


def test_every_tool_replies_with_the_documented_texts(tmp_path):
    async def scenario(session):
        replies = {}
        replies["empty_list"] = await call(session, "list_contexts")
        replies["empty_search"] = await call(session, "search_memory", query="anything")
        replies["empty_latest"] = await call(session, "read_latest_context")
        replies["empty_brief"] = await call(session, "get_project_brief", namespace="alpha")
        replies["save_context"] = await call(
            session, "save_context", agent="agent-a", title="Planning", content="Remember pelicans.", namespace="alpha"
        )
        replies["save_memory"] = await call(
            session,
            "save_memory",
            agent="agent-a",
            kind="decision",
            title="Pick storage",
            content="Markdown files.",
            namespace="alpha",
            tags=["storage"],
            relatedFiles=["src/a.py"],
            nextAction="Write docs",
        )
        await asyncio.sleep(1.1)
        replies["snapshot"] = await call(
            session, "create_snapshot", agent="agent-a", title="Brief", content="State.", namespace="alpha"
        )
        replies["list"] = await call(session, "list_contexts", namespace="alpha", kind="decision")
        replies["search"] = await call(session, "search_memory", namespace="alpha", query="pelican")
        replies["latest"] = await call(session, "read_latest_context", namespace="alpha", agent="agent-a")
        replies["brief"] = await call(session, "get_project_brief", namespace="alpha")
        return replies

    replies = run_session(tmp_path, scenario)

    assert replies["empty_list"] == "No saved context yet."
    assert replies["empty_search"] == "No matching memory found."
    assert replies["empty_latest"] == "No context found."
    assert replies["empty_brief"] == "**Project brief for alpha**\n\nNo saved memory found for namespace: alpha"
    assert re.fullmatch(f"Context saved with ID: {UUID}", replies["save_context"])
    assert re.fullmatch(f"Memory saved with ID: {UUID}", replies["save_memory"])
    assert re.fullmatch(f"Snapshot created with ID: {UUID}", replies["snapshot"])
    decision_id = re.search(UUID, replies["save_memory"]).group(0)[:8]
    snapshot_id = re.search(UUID, replies["snapshot"]).group(0)[:8]
    assert re.fullmatch(
        r"1\. \[decision: accepted\] \(alpha\) Pick storage - agent-a - \d+/\d+/\d{4}, \d+:\d{2}:\d{2} [AP]M"
        f" - id {decision_id}",
        replies["list"],
    )
    assert re.fullmatch(
        r"1\. \[note\] \(alpha\) Planning - agent-a - \d+/\d+/\d{4}, \d+:\d{2}:\d{2} [AP]M - id [0-9a-f]{8}",
        replies["search"],
    )
    assert re.fullmatch(
        r"\*\*Brief\*\* - agent-a - \d+/\d+/\d{4}, \d+:\d{2}:\d{2} [AP]M" f" - id {snapshot_id}\n\nState\.",
        replies["latest"],
    )
    assert re.fullmatch(
        r"\*\*Project brief for alpha\*\*\n\n"
        rf"## Snapshot: Brief \(\d{{4}}-\d{{2}}-\d{{2}}, id {snapshot_id}\)\nState\.",
        replies["brief"],
    )


def test_invalid_input_is_reported_as_a_tool_error_and_writes_nothing(tmp_path):
    async def scenario(session):
        bad_kind = await session.call_tool("save_memory", {"agent": "a", "kind": "bogus", "title": "t", "content": "c"})
        too_long = await session.call_tool("save_context", {"agent": "a", "title": "t" * 201, "content": "c"})
        blank = await session.call_tool("save_context", {"agent": "a", "title": "   ", "content": "c"})
        listing = await call(session, "list_contexts")
        return bad_kind, too_long, blank, listing

    bad_kind, too_long, blank, listing = run_session(tmp_path, scenario)

    assert bad_kind.is_error is True
    assert too_long.is_error is True
    assert blank.is_error is True
    assert "title is required" in blank.content[0].text
    assert listing == "No saved context yet."


def test_update_links_and_issues_tools_reply_and_reject_identity_changes(tmp_path):
    async def scenario(session):
        replies = {}
        saved = await call(
            session,
            "save_memory",
            agent="a",
            kind="decision",
            title="Pick storage",
            content="Plain.",
            namespace="alpha",
        )
        record_id = re.search(UUID, saved).group(0)
        replies["id"] = record_id
        replies["update"] = await call(session, "update_memory", id=record_id, expected_revision=1, status="accepted")
        replies["stale"] = await call(session, "update_memory", id=record_id, expected_revision=1, title="Lost")
        replies["missing"] = await call(session, "update_memory", id="nope", title="Ghost")
        replies["no_fields"] = (await session.call_tool("update_memory", {"id": record_id})).content[0].text
        replies["no_reason"] = (
            (await session.call_tool("update_memory", {"id": record_id, "validity": "rejected"})).content[0].text
        )
        replies["kind_change"] = (await session.call_tool("update_memory", {"id": record_id, "kind": "note"})).is_error
        replies["namespace_change"] = (
            await session.call_tool("update_memory", {"id": record_id, "namespace": "beta"})
        ).is_error
        replies["links"] = await call(session, "get_links", id=record_id)
        replies["links_missing"] = await call(session, "get_links", id="nope")
        replies["issues_none"] = await call(session, "list_issues")
        return replies

    replies = run_session(tmp_path, scenario)

    assert replies["update"] == f"Memory updated. ID: {replies['id']}. Revision: 2"
    assert replies["stale"] == (
        "Revision conflict: expected revision 1 but the current revision is 2. Read the record again before updating."
    )
    assert replies["missing"] == "Memory not found."
    assert (
        replies["no_fields"]
        == "Error executing tool update_memory: nothing to update: pass at least one field to change"
    )
    assert replies["no_reason"] == (
        "Error executing tool update_memory: rejected_reason is required when validity is rejected"
    )
    assert replies["kind_change"] is True
    assert replies["namespace_change"] is True
    assert replies["links"] == (
        "**Pick storage** - alpha\n\nOutgoing links (0):\n\nUnresolved links (0):\n\nBacklinks (1):\n- alpha/alpha.md"
    )
    assert replies["links_missing"] == "Memory not found."
    assert replies["issues_none"] == "No issues found."
