from typing import Annotated, Literal

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from agent_vault_memory.format import format_records, format_timestamp
from agent_vault_memory.records import KINDS
from agent_vault_memory.sanitize import INPUT_LIMITS
from agent_vault_memory.store import Store

ENGLISH = " Memory content is written in English."

Kind = Literal[*KINDS]
Namespace = Annotated[
    str | None,
    Field(
        max_length=INPUT_LIMITS["namespace"], description="Optional project or workspace namespace, default: default"
    ),
]
Tags = Annotated[
    list[Annotated[str, Field(max_length=INPUT_LIMITS["tag"])]] | None,
    Field(max_length=INPUT_LIMITS["tags"], description="Optional categorization tags; all tags must match"),
]
Supersedes = Annotated[
    list[str] | None,
    Field(max_length=INPUT_LIMITS["tags"], description="Optional ids of records this one supersedes"),
]
OptionalAgent = Annotated[str | None, Field(max_length=INPUT_LIMITS["agent"], description="Optional agent filter")]
ItemType = Annotated[Literal["context", "handoff"] | None, Field(description="Optional item type filter")]
OptionalKind = Annotated[Kind | None, Field(description="Optional structured memory kind filter")]
HandoffStatus = Literal["all", "pending", "read"]


def _text(maximum: str, description: str):
    return Annotated[str, Field(min_length=1, max_length=INPUT_LIMITS[maximum], description=description)]


def _optional_text(maximum: str, description: str):
    return Annotated[str | None, Field(min_length=1, max_length=INPUT_LIMITS[maximum], description=description)]


def create_server(store: Store) -> FastMCP:
    server = FastMCP("agent-vault-memory")

    def tool(name: str, description: str):
        return server.tool(name=name, description=description + ENGLISH, structured_output=False)

    @tool("save_context", "Save free-form context so another MCP-compatible agent can read it later.")
    def save_context(
        agent: _text("agent", "Agent saving the context, for example: claude-code, codex, assistant-a"),
        title: _text("title", "Short descriptive title"),
        content: _text("content", "Full context content"),
        namespace: Namespace = None,
        tags: Tags = None,
    ) -> str:
        record = store.save_context(agent, title, content, namespace, tags)
        return f"Context saved with ID: {record.id}"

    @tool("save_memory", "Save structured memory with a kind and optional workflow metadata.")
    def save_memory(
        agent: _text("agent", "Agent saving the memory"),
        kind: Annotated[Kind, Field(description="Structured memory kind")],
        title: _text("title", "Short descriptive title"),
        content: _text("content", "Full memory content"),
        namespace: Namespace = None,
        status: _optional_text("status", "Optional status, for example: open, accepted, done") = None,
        relatedFiles: Annotated[
            list[Annotated[str, Field(max_length=INPUT_LIMITS["file"])]] | None,
            Field(description="Optional related file paths"),
        ] = None,
        branch: _optional_text("file", "Optional related branch name") = None,
        commit: _optional_text("file", "Optional related commit SHA") = None,
        nextAction: _optional_text("title", "Optional next action") = None,
        tags: Tags = None,
        supersedes: Supersedes = None,
    ) -> str:
        record = store.save_memory(
            agent, kind, title, content, namespace, status, relatedFiles, branch, commit, nextAction, tags, supersedes
        )
        return f"Memory saved with ID: {record.id}"

    @tool("create_handoff", "Create a structured handoff for another MCP-compatible agent.")
    def create_handoff(
        to: _text("agent", "Destination agent, for example: claude-code, codex, assistant-b"),
        summary: _text("title", "Summary of what happened and what should continue"),
        context: _text("content", "Full context needed to continue the work"),
        namespace: Namespace = None,
        supersedes: Supersedes = None,
    ) -> str:
        record = store.create_handoff(to, summary, context, namespace, supersedes)
        return f"Handoff created for {to}. ID: {record.id}"

    @tool("read_handoff", "Read the next pending handoff for this agent and mark it as read.")
    def read_handoff(
        agent: _text("agent", "Current agent name, for example: claude-code, codex, assistant-b"),
        namespace: Namespace = None,
    ) -> str:
        record = store.read_handoff(agent, namespace)
        return record.content if record else "No pending handoff."

    @tool("read_latest_context", "Read the most recent saved context, optionally filtered by agent.")
    def read_latest_context(namespace: Namespace = None, agent: OptionalAgent = None) -> str:
        record = store.get_last_context(namespace, agent)
        if record is None:
            return "No context found."
        return f"**{record.title}** - {record.agent} - {format_timestamp(record.created)}\n\n{record.content}"

    @tool("list_contexts", "List recent contexts and handoffs.")
    def list_contexts(
        namespace: Namespace = None,
        agent: OptionalAgent = None,
        tags: Tags = None,
        type: ItemType = None,
        kind: OptionalKind = None,
        limit: Annotated[float | None, Field(description="Maximum number of items to list, default: 10")] = None,
    ) -> str:
        records = store.list_contexts(namespace, agent, tags, type, kind, limit)
        return format_records(records) if records else "No saved context yet."

    @tool("search_memory", "Search saved contexts and handoffs by text and filters.")
    def search_memory(
        namespace: Namespace = None,
        query: _optional_text("content", "Optional case-insensitive text query") = None,
        agent: OptionalAgent = None,
        tags: Tags = None,
        type: ItemType = None,
        kind: OptionalKind = None,
        handoffStatus: Annotated[HandoffStatus | None, Field(description="Optional status filter for handoffs")] = None,
        limit: Annotated[float | None, Field(description="Maximum number of items to return, default: 10")] = None,
    ) -> str:
        records = store.search_memory(namespace, query, agent, tags, type, kind, handoffStatus or "all", limit)
        return format_records(records) if records else "No matching memory found."

    @tool("create_snapshot", "Save a durable snapshot summary for a namespace.")
    def create_snapshot(
        agent: _text("agent", "Agent creating the snapshot"),
        title: _text("title", "Snapshot title"),
        content: _text("content", "Snapshot summary content"),
        namespace: Namespace = None,
    ) -> str:
        record = store.create_snapshot(agent, title, content, namespace)
        return f"Snapshot created with ID: {record.id}"

    @tool("get_project_brief", "Read the latest snapshot for a namespace, or a generated brief from recent memory.")
    def get_project_brief(
        namespace: Namespace = None,
        limit: Annotated[
            float | None, Field(description="Maximum number of recent items to include when no snapshot exists")
        ] = None,
    ) -> str:
        brief = store.get_project_brief(namespace, limit)
        return f"**{brief.title}** - {brief.namespace} - {format_timestamp(brief.created)}\n\n{brief.content}"

    @tool("list_handoffs", "List handoffs, optionally filtered by destination agent and status.")
    def list_handoffs(
        namespace: Namespace = None,
        agent: Annotated[
            str | None,
            Field(max_length=INPUT_LIMITS["agent"], description="Optional destination agent filter"),
        ] = None,
        status: Annotated[HandoffStatus | None, Field(description="Optional handoff status filter")] = None,
        limit: Annotated[float | None, Field(description="Maximum number of handoffs to list, default: 10")] = None,
    ) -> str:
        records = store.list_handoffs(namespace, agent, status or "all", limit)
        return format_records(records) if records else "No handoffs found."

    @tool("peek_handoff", "Read the next pending handoff for this agent without marking it as read.")
    def peek_handoff(
        agent: _text("agent", "Current agent name"),
        namespace: Namespace = None,
    ) -> str:
        record = store.peek_handoff(agent, namespace)
        return record.content if record else "No pending handoff."

    @tool("ack_handoff", "Mark a handoff as read by ID.")
    def ack_handoff(id: _text("content", "Handoff ID"), namespace: Namespace = None) -> str:
        record = store.ack_handoff(id, namespace)
        return f"Handoff marked as read. ID: {record.id}" if record else "Handoff not found."

    @tool("reopen_handoff", "Mark a read handoff as pending again by ID.")
    def reopen_handoff(id: _text("content", "Handoff ID"), namespace: Namespace = None) -> str:
        record = store.reopen_handoff(id, namespace)
        return f"Handoff reopened. ID: {record.id}" if record else "Handoff not found."

    return server
