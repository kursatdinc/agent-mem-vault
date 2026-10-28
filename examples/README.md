# Examples

| Path | What it is |
|---|---|
| [`demo-vault/`](demo-vault) | A ready-made vault with synthetic records for two fictional projects. Open it in Obsidian, or point the server at it. Regenerate it with `uv run python scripts/build_demo_vault.py`. |
| [`config.yaml`](config.yaml) | Every configuration key with its default. |
| [`claude-code.mcp.json`](claude-code.mcp.json) | A project-level `.mcp.json` for Claude Code. |
| [`codex-config.toml`](codex-config.toml) | The `[mcp_servers]` table for `~/.codex/config.toml`. |

Try the demo vault without touching your own memory:

```sh
export AGENT_MEM_VAULT_VAULT="$PWD/examples/demo-vault"
uvx agent-mem-vault doctor
uvx agent-mem-vault handoffs --namespace project/harbor-api --status pending
uvx agent-mem-vault search "backfill" --namespace project/harbor-api
```

Session hooks (feature `hooks`) need the command on your `PATH`:

```sh
uv tool install agent-mem-vault
agent-mem-vault hook print-config --client claude   # or codex
```
