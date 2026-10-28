import functools
from collections.abc import Callable
from typing import Annotated, Any, Literal

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field

from agent_vault_memory.companion import format_companion
from agent_vault_memory.format import format_brief, format_issues, format_links, format_records, format_timestamp
from agent_vault_memory.records import KINDS, RECEIPT_KIND
from agent_vault_memory.sanitize import INPUT_LIMITS
from agent_vault_memory.store import Store
from agent_vault_memory.vault import RevisionConflict, VaultError

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
IncludePrivate = Annotated[
    bool, Field(description="Include private records; hidden by default while the visibility feature is on")
]
HandoffStatus = Literal["all", "pending", "read"]
Visibility = Literal["public", "internal", "private"]
Validity = Literal["valid", "rejected"]


def _text(maximum: str, description: str):
    return Annotated[str, Field(min_length=1, max_length=INPUT_LIMITS[maximum], description=description)]


def _optional_text(maximum: str, description: str):
    return Annotated[str | None, Field(min_length=1, max_length=INPUT_LIMITS[maximum], description=description)]


def _anticipated_errors(function: Callable[..., str]) -> Callable[..., str]:
    """mcp 2 hides the text of crashes; validation and vault failures are expected, so the caller reads them."""

    @functools.wraps(function)
    def guarded(*args: Any, **kwargs: Any) -> str:
        try:
            return function(*args, **kwargs)
        except (ValueError, TypeError, VaultError) as error:
            raise ToolError(str(error)) from error

    return guarded


def create_server(store: Store) -> MCPServer:
    server = MCPServer("agent-vault-memory")
    FilterKind = Annotated[
        Literal[*store.vault.kinds] | None, Field(description="Optional structured memory kind filter")
    ]

    def tool(name: str, description: str):
        register = server.tool(name=name, description=description + ENGLISH, structured_output=False)
        return lambda function: register(_anticipated_errors(function))

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
    def read_latest_context(
        namespace: Namespace = None, agent: OptionalAgent = None, include_private: IncludePrivate = False
    ) -> str:
        record = store.get_last_context(namespace, agent, include_private)
        if record is None:
            return "No context found."
        return f"**{record.title}** - {record.agent} - {format_timestamp(record.created)}\n\n{record.content}"

    @tool("list_contexts", "List recent contexts and handoffs.")
    def list_contexts(
        namespace: Namespace = None,
        agent: OptionalAgent = None,
        tags: Tags = None,
        type: ItemType = None,
        kind: FilterKind = None,
        limit: Annotated[float | None, Field(description="Maximum number of items to list, default: 10")] = None,
        include_private: IncludePrivate = False,
    ) -> str:
        records = store.list_contexts(namespace, agent, tags, type, kind, limit, include_private)
        return format_records(records, store.visibility_filter) if records else "No saved context yet."

    @tool("search_memory", "Search saved contexts and handoffs by text and filters.")
    def search_memory(
        namespace: Namespace = None,
        query: _optional_text("content", "Optional case-insensitive text query") = None,
        agent: OptionalAgent = None,
        tags: Tags = None,
        type: ItemType = None,
        kind: FilterKind = None,
        handoffStatus: Annotated[HandoffStatus | None, Field(description="Optional status filter for handoffs")] = None,
        limit: Annotated[float | None, Field(description="Maximum number of items to return, default: 10")] = None,
        include_private: IncludePrivate = False,
    ) -> str:
        records = store.search_memory(
            namespace, query, agent, tags, type, kind, handoffStatus or "all", limit, include_private
        )
        return format_records(records, store.visibility_filter) if records else "No matching memory found."

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
        return format_brief(store.get_project_brief(namespace, limit))

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

    @tool(
        "update_memory",
        "Update the title, content, tags, status, visibility or validity of an existing record by ID. "
        "Pass expected_revision to detect changes made since the record was last read.",
    )
    def update_memory(
        id: _text("content", "Record ID"),
        expected_revision: Annotated[
            int | None, Field(ge=1, description="Optional revision last read; a newer revision returns a conflict")
        ] = None,
        title: _optional_text("title", "New title") = None,
        content: _optional_text("content", "New full content") = None,
        tags: Annotated[
            list[Annotated[str, Field(max_length=INPUT_LIMITS["tag"])]] | None,
            Field(max_length=INPUT_LIMITS["tags"], description="New tags replacing all current tags"),
        ] = None,
        status: _optional_text("status", "New status") = None,
        visibility: Annotated[Visibility | None, Field(description="New visibility")] = None,
        validity: Annotated[Validity | None, Field(description="New validity; rejected needs rejected_reason")] = None,
        rejected_reason: _optional_text("title", "Why the record is rejected") = None,
    ) -> str:
        try:
            record = store.update_memory(
                id, expected_revision, title, content, tags, status, visibility, validity, rejected_reason
            )
        except RevisionConflict as conflict:
            return (
                f"Revision conflict: expected revision {conflict.expected} but the current revision is "
                f"{conflict.current}. Read the record again before updating."
            )
        return f"Memory updated. ID: {record.id}. Revision: {record.revision}" if record else "Memory not found."

    @tool("get_links", "List the outgoing links and the backlinks of a record by ID.")
    def get_links(id: _text("content", "Record ID")) -> str:
        found = store.get_links(id)
        return format_links(*found) if found else "Memory not found."

    @tool("list_issues", "List vault files that look like records but cannot be used, with the reason.")
    def list_issues() -> str:
        issues = store.list_issues()
        return format_issues(issues) if issues else "No issues found."

    if RECEIPT_KIND in store.vault.kinds:

        @tool(
            "write_receipt",
            "Record an immutable receipt of finished work with the files and commits it touched.",
        )
        def write_receipt(
            agent: _text("agent", "Agent that did the work"),
            title: _text("title", "Short receipt title"),
            summary: _text("content", "What was done"),
            refs: Annotated[
                list[Annotated[str, Field(max_length=INPUT_LIMITS["file"])]],
                Field(max_length=INPUT_LIMITS["refs"], description="File paths or commit SHAs the work touched"),
            ],
            namespace: Namespace = None,
            harness: _optional_text("agent", "Optional client or harness name, for example: claude-code") = None,
            session: _optional_text("file", "Optional session identifier") = None,
        ) -> str:
            record = store.write_receipt(agent, title, summary, refs, namespace, harness, session)
            return f"Receipt saved with ID: {record.id}"

    if store.companion_max_chars is not None:

        @tool(
            "get_companion",
            "Read the last-session and threads companion cards of a namespace: short notes from the previous session.",
        )
        def get_companion(namespace: Namespace = None) -> str:
            return format_companion(store.get_companion(namespace))

        @tool(
            "update_companion",
            "Replace the last-session and/or threads companion card of a namespace. "
            f"Each card is limited to {store.companion_max_chars} characters: keep them short and compact old text "
            "when rewriting.",
        )
        def update_companion(
            namespace: Namespace = None,
            last_session: _optional_text(
                "content", "New last-session card: what the last session did and left open"
            ) = None,
            threads: _optional_text("content", "New threads card: open threads to pick up") = None,
        ) -> str:
            store.update_companion(namespace, last_session, threads)
            return "Companion updated."

    return server
