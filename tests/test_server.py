import re

from mcp_session import call, run_session

CORE_TOOLS = {
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
NEW_TOOLS = {"update_memory", "get_links", "list_issues"}
UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"


def test_tools_list_exposes_the_core_and_additional_tools_with_their_parameters(tmp_path):
    async def scenario(session):
        return (await session.list_tools()).tools

    tools = {tool.name: tool for tool in run_session(tmp_path, scenario)}

    assert set(tools) == CORE_TOOLS | NEW_TOOLS
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
        "handoff",
        "snapshot",
    }
    assert set(tools["create_handoff"].input_schema["properties"]) == {
        "namespace",
        "to",
        "summary",
        "context",
        "supersedes",
    }
    assert tools["search_memory"].description.startswith("Search saved contexts and handoffs by text and filters.")
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
