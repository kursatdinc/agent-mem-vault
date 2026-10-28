# Getting Started

## Requirements

- [uv](https://docs.astral.sh/uv/), which provides `uvx`.
- Python 3.12 or newer (uv installs it if needed). macOS or Linux: the file lock uses `fcntl`, so
  Windows is not supported yet.
- An Obsidian vault, or any folder you want to use as one. Obsidian itself is optional for the
  server and needed only to browse the notes.

## 1. Try the demo vault

The repository contains a vault of synthetic records for two fictional projects.

```sh
git clone https://github.com/kursatdinc/agent-mem-vault && cd agent-mem-vault
export AGENT_MEM_VAULT_VAULT="$PWD/examples/demo-vault"

uv run agent-mem-vault doctor
uv run agent-mem-vault handoffs --namespace project/harbor-api --status pending
uv run agent-mem-vault search "backfill" --namespace project/harbor-api
```

`doctor` should report 14 records and 0 issues. Open `examples/demo-vault` in Obsidian
(*Open folder as vault*) to see the graph and the dashboard.

## 2. Create your own vault

In Obsidian choose *Create new vault*, for example `~/agent-memory`. Running `git init` inside it is
optional but gives you history for free.

## 3. Add the server to your agents

Claude Code:

```sh
claude mcp add agent-mem-vault -s user \
  --env AGENT_MEM_VAULT_VAULT="$HOME/agent-memory" \
  -- uvx agent-mem-vault
```

Codex, in `~/.codex/config.toml`:

```toml
[mcp_servers.agent-mem-vault]
command = "uvx"
args = ["agent-mem-vault"]
env = { AGENT_MEM_VAULT_VAULT = "/Users/you/agent-memory" }
```

Instead of the `env` line you can put `vault: ~/agent-memory` in
`~/.config/agent-mem-vault/config.yaml`; see
[Configuration](https://github.com/kursatdinc/agent-mem-vault/wiki/Configuration).

To run the development version from GitHub, use
`uvx --from git+https://github.com/kursatdinc/agent-mem-vault agent-mem-vault` in place of
`uvx agent-mem-vault`.

Other MCP clients: the server speaks MCP over stdio, started by running `agent-mem-vault` with no
arguments.

## 4. Check the setup

```sh
AGENT_MEM_VAULT_VAULT="$HOME/agent-memory" uvx agent-mem-vault doctor
```

It prints the config file in use, the vault path, whether `.obsidian/` exists, record counts by kind,
issues, leftover temporary files and the vault's git state.

## 5. Use it

Ask your agent in plain language:

- "Record this decision: we use PostgreSQL because ..."
- "Leave a handoff for Codex about the migration."
- "What are the open risks in this project?"
- "What did we decide about caching?"

The agent calls the tools in the
[Tools Reference](https://github.com/kursatdinc/agent-mem-vault/wiki/Tools-Reference) and the notes
appear in the vault. Records are grouped by namespace; the usual namespace is `project/<repo name>`.

## Optional: session hooks

With `features.hooks` on, Claude Code and Codex can load the project brief at session start and get a
nudge to record decisions when a session stops. Install the command once, then print the snippet for
your client:

```sh
uv tool install agent-mem-vault
agent-mem-vault hook print-config --client claude   # or: codex
```

Paste the output into your client's settings. The server never edits client settings itself.
