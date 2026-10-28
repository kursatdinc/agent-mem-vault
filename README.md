# agent-vault-memory

**Memory your coding agents share, and you can read, link and fix in Obsidian.**

[![ci](https://github.com/kursatdinc/agent-vault-memory/actions/workflows/ci.yml/badge.svg)](https://github.com/kursatdinc/agent-vault-memory/actions/workflows/ci.yml)
![python](https://img.shields.io/badge/python-3.12%2B-blue)
![license](https://img.shields.io/badge/license-MIT-green)
![status](https://img.shields.io/badge/status-pre--alpha-orange)

agent-vault-memory is an [MCP](https://modelcontextprotocol.io) server that turns an
[Obsidian](https://obsidian.md) vault into the long-term memory of your coding agents. Claude Code,
Codex and any other MCP client record decisions, risks, handoffs and project snapshots as notes in
the vault. They read them back in the next session, in the next tool, on the next day. You see
the same memory in Obsidian, and you can correct it there.

> **Pre-alpha.** The tool surface is stable enough for daily use; the on-disk format may still
> change before v0.1.

## Why

- **Agents forget.** Every new session starts cold, and the reasoning behind yesterday's choice
  is gone.
- **Agents don't talk to each other.** What Claude Code decided is invisible to Codex, and the
  other way round.
- **Agent memory is a black box.** It hides in JSON files or databases you can't read, review or
  fix. A wrong "memory" quietly steers every later session.

## What you get

**One memory for all your agents.**
- Claude Code and Codex read and write the same records.
- A handoff left by one agent is picked up by the next, with a real lifecycle: pending, read,
  acknowledged.
- A new handoff can supersede older ones, so the queue holds one live thread instead of a
  growing pile.

**Memory you can see.**
- Every record is a note in your vault.
- Obsidian's graph shows how decisions supersede each other and which records belong to which
  project.
- A generated Bases dashboard lists pending handoffs, open decisions and risks.

**Memory you can correct.**
- Edit a note in Obsidian and the next query sees it.
- Mark a decision rejected, with a reason, and it stops steering agents but stays on record.
- Mark a record private and it stays out of automatic context.

**Typed, not a transcript dump.** Records are `decision`, `risk`, `handoff`, `snapshot`, `note`,
`assumption` and `task`, plus optional `receipt`. Agents can therefore ask precise questions:
"open risks in this project", "what did we decide about caching", "what is waiting for me".

**Yours.** Memory is plain Markdown in a folder you own. Put the vault in git and you get a full
audit trail for free. Everything works offline, and Obsidian does not need to be open.

## How it looks

```text
agent-memory/                         # your Obsidian vault
├── project-ai-agents/
│   ├── _index.md                     # generated hub: every record of the project
│   ├── decision/2026-10-28-use-adk-2-11-for-the-runtime-3f9a2c1e.md
│   ├── risk/2026-10-27-gcs-path-traversal-in-bot-uploads-7c41d0aa.md
│   └── handoff/2026-10-28-handoff-to-codex-b2e95f10.md
├── project-sphere-arena/
│   └── ...
└── _dashboards/memory.base           # pending handoffs, decisions and risks, all records
```

```markdown
---
id: 3f9a2c1e-6b1d-4c3e-9a51-0e2f7d8c4b11
kind: decision
namespace: project/ai-agents
agent: claude-code
title: Use ADK 2.11 for the agent runtime
created: 2026-10-28T09:13:05Z
revision: 1
visibility: internal
validity: valid
tags: [runtime, adk]
supersedes: ['[[project-ai-agents/decision/2026-09-02-use-adk-2-10-a1b2c3d4]]']
agent-written: true
---
ADK 2.11 fixes the streaming cache markers we patched by hand; the upgrade removes our fork.

<!-- avm:related:start -->
## Related
- Supersedes [[project-ai-agents/decision/2026-09-02-use-adk-2-10-a1b2c3d4|Use ADK 2.10]]
<!-- avm:related:end -->
```

## Quick start

1. **Create a vault.** In Obsidian choose *Create new vault*, for example `~/agent-memory`.
   Optionally run `git init` inside it.
2. **Add the server to your agents.**

   Claude Code:

   ```sh
   claude mcp add agent-vault-memory -s user \
     --env AGENT_VAULT_MEMORY_VAULT="$HOME/agent-memory" \
     -- uvx --from git+https://github.com/kursatdinc/agent-vault-memory agent-vault-memory
   ```

   Codex (`~/.codex/config.toml`):

   ```toml
   [mcp_servers.agent-vault-memory]
   command = "uvx"
   args = ["--from", "git+https://github.com/kursatdinc/agent-vault-memory", "agent-vault-memory"]
   env = { AGENT_VAULT_MEMORY_VAULT = "/Users/you/agent-memory" }
   ```

3. **Check the setup.**

   ```sh
   AGENT_VAULT_MEMORY_VAULT="$HOME/agent-memory" \
     uvx --from git+https://github.com/kursatdinc/agent-vault-memory agent-vault-memory doctor
   ```

4. **Use it.** Ask your agent to "record this decision", "leave a handoff for Codex" or "what are
   the open risks in this project?". It uses the tools below. Open the vault in Obsidian to watch
   the notes appear.

## Tools

| Group | Tools |
|---|---|
| Write | `save_memory`, `save_context`, `create_snapshot`, `update_memory` |
| Handoffs | `create_handoff`, `read_handoff`, `peek_handoff`, `ack_handoff`, `reopen_handoff`, `list_handoffs` |
| Read | `get_project_brief`, `search_memory`, `list_contexts`, `read_latest_context`, `get_links` |
| Health | `list_issues` |
| Optional | `write_receipt` (receipts), `get_companion`, `update_companion` (companion) |

- Records are grouped by namespace, usually `project/<repo>`.
- Free-text search is stemmed, so "caching" finds "cache" and "cached".
- Memory content is written in English.
- The first 13 tools keep the names and reply texts of
  [shared-memory-mcp](https://github.com/gamazyn/shared-memory-mcp), so existing agent
  instructions keep working.

## Configuration

`~/.config/agent-vault-memory/config.yaml`. Every key is optional, and environment variables win.

```yaml
vault: ~/agent-memory              # or AGENT_VAULT_MEMORY_VAULT
default_namespace: default         # or AGENT_VAULT_MEMORY_DEFAULT_NAMESPACE
redact_secrets: true               # or AGENT_VAULT_MEMORY_REDACT_SECRETS
features:
  visibility: true                 # private records stay out of automatic context
  receipts: false                  # immutable records of finished work, with file/commit refs
  companion: false                 # per-project "last session" and "open threads" cards
  hooks: false                     # session-start brief and stop nudge for Claude Code / Codex
  git_autocommit: false            # commit every change in the vault's git repo (never pushes)
companion:
  max_chars: 3000
```

With `hooks` on, `agent-vault-memory hook print-config --client claude|codex` prints the snippet
to add to your client settings. The server never edits client settings itself.

## Guarantees

- **No lost writes.** Two agents writing at once are serialized by a file lock, and every file is
  replaced atomically.
- **No silent overwrites.** Updates check the record's revision. A note you edited by hand is
  never overwritten; the agent gets a conflict and re-reads.
- **Broken notes are reported, not dropped.** A note with invalid frontmatter shows up in
  `list_issues` and `doctor`, untouched.
- **Hands off your setup.** It never writes `.obsidian/`, never launches Obsidian, never pushes
  git and makes no network calls.
- **Secrets stay out.** Token, key and password patterns are redacted before anything is
  written.

## Migrating from shared-memory-mcp

```sh
agent-vault-memory import ~/.shared-memory-mcp/contexts.json
```

The import keeps ids and timestamps and marks handoffs that a later handoff superseded as read. It
is idempotent and never modifies the source file.

## Status and roadmap

- [x] Typed records, handoff lifecycle, supersedes, stemmed search
- [x] Hand-edit safety: revisions, conflicts, issue reporting
- [x] Hub notes, Bases dashboard, optional git autocommit, `doctor`
- [x] Optional receipts, companion cards, visibility, client hooks
- [ ] v0.1 on PyPI (`uvx agent-vault-memory`)

The design contract lives in [docs/DESIGN.md](docs/DESIGN.md).

## Development

```sh
uv sync
uv run ruff check
uv run pytest -q
```

Requires Python 3.12+ on macOS or Linux; file locking uses `fcntl`, so Windows is not supported
yet.

## License

[MIT](LICENSE) © 2026 Kürşat Dinç
