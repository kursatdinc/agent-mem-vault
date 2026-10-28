import re

import yaml

from agent_vault_memory.records import RELATED_END, RELATED_START

FILENAME = re.compile(r"^\d{4}-\d{2}-\d{2}-[a-z0-9-]+-[0-9a-f]{8}\.md$")


def test_save_memory_writes_the_documented_record_format(store, vault):
    record = store.save_memory(
        agent="claude-code",
        kind="decision",
        title="Use ADK 2.11 for the agent runtime",
        content="Adopt ADK 2.11.",
        namespace="project/ai-agents",
        tags=["runtime", "adk"],
        status="accepted",
        related_files=["src/runtime.py"],
        branch="feat/adk",
        commit="abc1234",
        next_action="Update the docs.",
    )

    folder, filename = record.path.rsplit("/", 1)
    assert folder == "project-ai-agents/decision"
    assert FILENAME.match(filename)
    assert filename == f"2026-10-28-use-adk-2-11-for-the-agent-runtime-{record.id[:8]}.md"
    assert (
        (vault.root / record.path).read_text(encoding="utf-8")
        == f"""---
id: {record.id}
kind: decision
namespace: project/ai-agents
agent: claude-code
title: Use ADK 2.11 for the agent runtime
created: 2026-10-28T09:00:01Z
updated: 2026-10-28T09:00:01Z
revision: 1
visibility: internal
validity: valid
tags: [runtime, adk]
status: accepted
related_files: [src/runtime.py]
next_action: Update the docs.
branch: feat/adk
commit: abc1234
agent-written: true
---
Adopt ADK 2.11.
"""
    )


def test_supersedes_writes_links_and_related_block_on_both_records(store, vault):
    old = store.save_memory(
        agent="claude-code", kind="decision", title="Old runtime", content="Use the old one.", namespace="proj"
    )

    new = store.save_memory(
        agent="claude-code",
        kind="decision",
        title="New runtime",
        content="Use the new one.",
        namespace="proj",
        supersedes=[old.id],
    )

    new_text = (vault.root / new.path).read_text(encoding="utf-8")
    old_text = (vault.root / old.path).read_text(encoding="utf-8")
    old_link = old.path.removesuffix(".md")
    new_link = new.path.removesuffix(".md")
    assert yaml.safe_load(new_text.split("---\n")[1])["supersedes"] == [f"[[{old_link}]]"]
    assert new_text.endswith(
        f"Use the new one.\n\n{RELATED_START}\n## Related\n- Supersedes [[{old_link}|Old runtime]]\n{RELATED_END}\n"
    )
    old_meta = yaml.safe_load(old_text.split("---\n")[1])
    assert old_meta["superseded_by"] == f"[[{new_link}]]"
    assert old_meta["revision"] == 2
    assert old_text.endswith(
        f"Use the old one.\n\n{RELATED_START}\n## Related\n- Superseded by [[{new_link}|New runtime]]\n{RELATED_END}\n"
    )


def test_a_record_without_lists_still_has_one_frontmatter_key_per_line(store, vault):
    record = store.save_context(agent="agent-a", title="Plain", content="Body.", namespace="proj")

    text = (vault.root / record.path).read_text(encoding="utf-8")

    assert text.startswith(f"---\nid: {record.id}\nkind: note\nnamespace: proj\nagent: agent-a\ntitle: Plain\n")
    assert "{" not in text.split("---\n")[1]
