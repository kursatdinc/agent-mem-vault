# agent-vault-memory

> **Pre-alpha.** Interfaces and the on-disk format may still change.

A local MCP server that gives coding agents (Claude Code, Codex, any MCP client) durable, typed,
shared memory whose single source of truth is an [Obsidian](https://obsidian.md) vault: one
Markdown file per record, YAML frontmatter, editable by hand. No database, no persistent index,
no network calls. Tool names and reply texts are compatible with `shared-memory-mcp`.

Design contract: [docs/DESIGN.md](docs/DESIGN.md).

## Install

```sh
uvx --from git+https://github.com/kursatdinc/agent-vault-memory agent-vault-memory
```

## Configure

Claude Code:

```sh
claude mcp add agent-vault-memory \
  --env AGENT_VAULT_MEMORY_VAULT=/path/to/vault \
  -- uvx --from git+https://github.com/kursatdinc/agent-vault-memory agent-vault-memory
```

Codex (`~/.codex/config.toml`):

```toml
[mcp_servers.agent-vault-memory]
command = "uvx"
args = ["--from", "git+https://github.com/kursatdinc/agent-vault-memory", "agent-vault-memory"]
env = { AGENT_VAULT_MEMORY_VAULT = "/path/to/vault" }
```

## CLI

```sh
agent-vault-memory            # run the MCP server over stdio
agent-vault-memory doctor     # check config, vault and record counts
agent-vault-memory list       # list recent records
agent-vault-memory search QUERY
agent-vault-memory handoffs
agent-vault-memory import contexts.json [--namespace-map old=new]   # one-time shared-memory-mcp import
agent-vault-memory hook print-config --client claude|codex          # settings snippet for the hooks feature
```

## Features

Off unless enabled in the config file (`features.visibility` is the one that defaults to on):

```yaml
features:
  receipts: true      # write_receipt: immutable records of finished work
  companion: true     # get_companion / update_companion: last-session and threads cards
  visibility: true    # private records hidden unless include_private; rejected records marked
  hooks: true         # hook session-start | stop for Claude Code and Codex
companion:
  max_chars: 3000
```

## Development

```sh
uv sync
uv run ruff check
uv run pytest -q
```

MIT licensed.
