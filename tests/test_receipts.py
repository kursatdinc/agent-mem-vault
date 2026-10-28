import pytest

from agent_mem_vault.records import RECEIPT_KIND
from agent_mem_vault.vault import VaultError
from mcp_session import call, run_session

RECEIPT_CONFIG = "features:\n  receipts: true\n"


def read_text(vault, record):
    return (vault.root / record.path).read_text(encoding="utf-8")


def test_a_receipt_is_a_record_with_refs_in_frontmatter_and_in_the_related_list(receipt_store):
    receipt = receipt_store.write_receipt(
        agent="claude-code",
        title="Wire the hooks",
        summary="Added hook commands.",
        refs=["src/cli.py", "5ef1613"],
        namespace="project/demo",
        harness="claude",
        session="s-42",
    )

    text = read_text(receipt_store.vault, receipt)
    assert receipt.path == f"project-demo/receipt/2026-10-28-wire-the-hooks-{receipt.id[:8]}.md"
    assert text.startswith(
        f"---\nid: {receipt.id}\nkind: receipt\nnamespace: project/demo\nagent: claude-code\n"
        "title: Wire the hooks\ncreated: 2026-10-28T09:00:01Z\nupdated: 2026-10-28T09:00:01Z\nrevision: 1\n"
        "visibility: internal\nvalidity: valid\ntags: [receipt]\nrefs: [src/cli.py, 5ef1613]\n"
        "harness: claude\nsession: s-42\nagent-written: true\n---\n"
    )
    assert text.endswith(
        "Added hook commands.\n\n<!-- avm:related:start -->\n## Related\n- `src/cli.py`\n- `5ef1613`\n"
        "<!-- avm:related:end -->\n"
    )
    assert receipt_store.list_contexts(namespace="project/demo", kind="receipt")[0].id == receipt.id


def test_a_receipt_cannot_be_updated_or_superseded(receipt_store):
    receipt = receipt_store.write_receipt(agent="a", title="Done", summary="Finished.", refs=["a.py"])
    before = read_text(receipt_store.vault, receipt)

    with pytest.raises(VaultError, match="receipts are immutable and cannot be updated"):
        receipt_store.update_memory(receipt.id, title="Changed")
    with pytest.raises(VaultError, match=f"Record is an immutable receipt: {receipt.id}"):
        receipt_store.save_memory(agent="a", kind="decision", title="New", content="c", supersedes=[receipt.id])

    assert read_text(receipt_store.vault, receipt) == before


def test_receipts_are_not_a_kind_for_save_memory(receipt_store):
    with pytest.raises(ValueError, match="kind must be one of: note, decision, assumption, task, risk, handoff"):
        receipt_store.save_memory(agent="a", kind="receipt", title="t", content="c")


def test_refs_are_redacted_and_validated(receipt_store):
    receipt = receipt_store.write_receipt(
        agent="a", title="t", summary="s", refs=["deploy token=abc123", "a.py", "a.py"]
    )

    assert receipt.meta["refs"] == ["deploy token=[REDACTED_SECRET]", "a.py"]
    assert "- `deploy token=[REDACTED_SECRET]`" in read_text(receipt_store.vault, receipt)
    with pytest.raises(ValueError, match="ref must not contain newlines or backticks"):
        receipt_store.write_receipt(agent="a", title="t", summary="s", refs=["a`b"])
    with pytest.raises(ValueError, match="ref must not contain newlines or backticks"):
        receipt_store.write_receipt(agent="a", title="t", summary="s", refs=["a\nb"])
    with pytest.raises(TypeError, match="refs must be an array"):
        receipt_store.write_receipt(agent="a", title="t", summary="s", refs="a.py")


def test_with_the_feature_off_receipts_cannot_be_written_and_receipt_files_are_ignored(store, vault):
    with pytest.raises(VaultError, match="receipts are disabled: set features.receipts in the config"):
        store.write_receipt(agent="a", title="t", summary="s", refs=[])

    folder = vault.root / "default" / RECEIPT_KIND
    folder.mkdir(parents=True)
    (folder / "2026-10-28-stray-00000000.md").write_text(
        "---\nid: x\nkind: receipt\nnamespace: default\n---\nbody\n", encoding="utf-8"
    )

    scan = vault.scan()
    assert (scan.records, scan.issues) == ([], [])


def test_the_write_receipt_tool_is_registered_only_when_the_feature_is_on(tmp_path):
    async def tool_names(session):
        return {tool.name for tool in (await session.list_tools()).tools}

    off = run_session(tmp_path / "off", tool_names)
    on = run_session(tmp_path / "on", tool_names, RECEIPT_CONFIG)

    assert "write_receipt" not in off
    assert "write_receipt" in on


def test_the_receipt_tool_replies_and_update_memory_refuses_the_receipt_over_stdio(tmp_path):
    async def scenario(session):
        tools = {tool.name: tool for tool in (await session.list_tools()).tools}
        saved = await call(
            session,
            "write_receipt",
            agent="codex",
            title="Shipped",
            summary="Merged the change.",
            refs=["abc1234"],
            namespace="alpha",
        )
        record_id = saved.rsplit(" ", 1)[1]
        update = await session.call_tool("update_memory", {"id": record_id, "title": "Edited"})
        listing = await call(session, "list_contexts", namespace="alpha", kind="receipt")
        return tools["write_receipt"], saved, update, listing

    (tool, saved, update, listing) = run_session(tmp_path, scenario, RECEIPT_CONFIG)

    assert set(tool.input_schema["properties"]) == {
        "agent",
        "title",
        "summary",
        "refs",
        "namespace",
        "harness",
        "session",
    }
    assert set(tool.input_schema["required"]) == {"agent", "title", "summary", "refs"}
    assert saved.startswith("Receipt saved with ID: ")
    assert update.is_error is True
    assert update.content[0].text == "Error executing tool update_memory: receipts are immutable and cannot be updated"
    assert listing.startswith("1. [context/receipt] (alpha) Shipped - codex - ")
