import asyncio
import re
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

LEGACY_TOOLS = {
    "save_context",
    "save_memory",
    "create_handoff",
    "create_snapshot",
    "get_project_brief",
    "read_handoff",
    "peek_handoff",
    "ack_handoff",
    "reopen_handoff",
    "list_handoffs",
    "read_latest_context",
    "list_contexts",
    "search_memory",
}
UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"


def run_session(tmp_path, scenario):
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    config_file = tmp_path / "config.yaml"
    config_file.write_text("", encoding="utf-8")
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-c", "from agent_vault_memory.cli import run; run()"],
        env={"AGENT_VAULT_MEMORY_VAULT": str(vault_root), "AGENT_VAULT_MEMORY_CONFIG": str(config_file)},
    )

    async def session_run():
        async with stdio_client(parameters) as (read, write), ClientSession(read, write) as session:
            await session.initialize()
            return await scenario(session)

    return asyncio.run(asyncio.wait_for(session_run(), timeout=60))


async def call(session, name, **arguments):
    result = await session.call_tool(name, arguments)
    return result.content[0].text


def test_tools_list_exposes_the_13_legacy_tools_with_compatible_parameters(tmp_path):
    async def scenario(session):
        return (await session.list_tools()).tools

    tools = {tool.name: tool for tool in run_session(tmp_path, scenario)}

    assert set(tools) == LEGACY_TOOLS
    for tool in tools.values():
        assert "Memory content is written in English." in tool.description
    save_memory = tools["save_memory"].inputSchema
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
        "handoff",
        "snapshot",
    }
    assert set(tools["create_handoff"].inputSchema["properties"]) == {
        "namespace",
        "to",
        "summary",
        "context",
        "supersedes",
    }
    assert tools["search_memory"].description.startswith("Search saved contexts and handoffs by text and filters.")


def test_every_tool_replies_with_the_legacy_texts(tmp_path):
    async def scenario(session):
        replies = {}
        replies["empty_list"] = await call(session, "list_contexts")
        replies["empty_search"] = await call(session, "search_memory", query="anything")
        replies["empty_latest"] = await call(session, "read_latest_context")
        replies["empty_handoffs"] = await call(session, "list_handoffs")
        replies["empty_peek"] = await call(session, "peek_handoff", agent="agent-b")
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
        replies["snapshot"] = await call(
            session, "create_snapshot", agent="agent-a", title="Brief", content="State.", namespace="alpha"
        )
        replies["handoff"] = await call(
            session, "create_handoff", to="agent-b", summary="Continue", context="Details", namespace="alpha"
        )
        replies["list"] = await call(session, "list_contexts", namespace="alpha", kind="decision")
        replies["search"] = await call(session, "search_memory", namespace="alpha", query="pelican")
        replies["latest"] = await call(session, "read_latest_context", namespace="alpha", agent="agent-a")
        replies["brief"] = await call(session, "get_project_brief", namespace="alpha")
        replies["handoffs"] = await call(session, "list_handoffs", namespace="alpha", status="pending")
        replies["peek"] = await call(session, "peek_handoff", agent="agent-b", namespace="alpha")
        replies["read"] = await call(session, "read_handoff", agent="agent-b", namespace="alpha")
        replies["read_again"] = await call(session, "read_handoff", agent="agent-b", namespace="alpha")
        handoff_id = re.search(UUID, replies["handoff"]).group(0)
        replies["ack"] = await call(session, "ack_handoff", id=handoff_id, namespace="alpha")
        replies["reopen"] = await call(session, "reopen_handoff", id=handoff_id, namespace="alpha")
        replies["ack_missing"] = await call(session, "ack_handoff", id="nope", namespace="alpha")
        replies["reopen_missing"] = await call(session, "reopen_handoff", id="nope", namespace="alpha")
        replies["handoff_id"] = handoff_id
        return replies

    replies = run_session(tmp_path, scenario)

    assert replies["empty_list"] == "No saved context yet."
    assert replies["empty_search"] == "No matching memory found."
    assert replies["empty_latest"] == "No context found."
    assert replies["empty_handoffs"] == "No handoffs found."
    assert replies["empty_peek"] == "No pending handoff."
    assert re.fullmatch(
        r"\*\*Project brief for alpha\*\* - alpha - \d+/\d+/\d{4}, \d+:\d{2}:\d{2} [AP]M\n\n"
        r"No saved memory found for namespace: alpha",
        replies["empty_brief"],
    )
    assert re.fullmatch(f"Context saved with ID: {UUID}", replies["save_context"])
    assert re.fullmatch(f"Memory saved with ID: {UUID}", replies["save_memory"])
    assert re.fullmatch(f"Snapshot created with ID: {UUID}", replies["snapshot"])
    assert re.fullmatch(f"Handoff created for agent-b. ID: {UUID}", replies["handoff"])
    assert re.fullmatch(
        r"1\. \[context/decision\] \(alpha\) Pick storage - agent-a - \d+/\d+/\d{4}, \d+:\d{2}:\d{2} [AP]M",
        replies["list"],
    )
    assert re.fullmatch(
        r"1\. \[context/note\] \(alpha\) Planning - agent-a - \d+/\d+/\d{4}, \d+:\d{2}:\d{2} [AP]M", replies["search"]
    )
    assert re.fullmatch(r"\*\*Brief\*\* - agent-a - \d+/\d+/\d{4}, \d+:\d{2}:\d{2} [AP]M\n\nState\.", replies["latest"])
    assert re.fullmatch(r"\*\*Brief\*\* - alpha - \d+/\d+/\d{4}, \d+:\d{2}:\d{2} [AP]M\n\nState\.", replies["brief"])
    assert re.fullmatch(
        r"1\. \[handoff/handoff -> agent-b \[PENDING\]\] \(alpha\) Handoff to agent-b - handoff - "
        r"\d+/\d+/\d{4}, \d+:\d{2}:\d{2} [AP]M",
        replies["handoffs"],
    )
    expected_content = "## Summary\nContinue\n\n## Full Context\nDetails"
    assert replies["peek"] == expected_content
    assert replies["read"] == expected_content
    assert replies["read_again"] == "No pending handoff."
    assert replies["ack"] == f"Handoff marked as read. ID: {replies['handoff_id']}"
    assert replies["reopen"] == f"Handoff reopened. ID: {replies['handoff_id']}"
    assert replies["ack_missing"] == "Handoff not found."
    assert replies["reopen_missing"] == "Handoff not found."


def test_invalid_input_is_reported_as_a_tool_error_and_writes_nothing(tmp_path):
    async def scenario(session):
        bad_kind = await session.call_tool("save_memory", {"agent": "a", "kind": "bogus", "title": "t", "content": "c"})
        too_long = await session.call_tool("save_context", {"agent": "a", "title": "t" * 201, "content": "c"})
        blank = await session.call_tool("save_context", {"agent": "a", "title": "   ", "content": "c"})
        listing = await call(session, "list_contexts")
        return bad_kind, too_long, blank, listing

    bad_kind, too_long, blank, listing = run_session(tmp_path, scenario)

    assert bad_kind.isError is True
    assert too_long.isError is True
    assert blank.isError is True
    assert "title is required" in blank.content[0].text
    assert listing == "No saved context yet."
