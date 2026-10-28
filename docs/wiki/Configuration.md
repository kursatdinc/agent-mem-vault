# Configuration

Precedence, lowest to highest: built-in defaults, the config file, environment variables.

## Config file

`$AGENT_MEM_VAULT_CONFIG` if set (the file must exist), otherwise
`~/.config/agent-mem-vault/config.yaml`. A missing default file is fine. The file must contain a
YAML mapping. A commented copy is in
[examples/config.yaml](https://github.com/kursatdinc/agent-mem-vault/blob/main/examples/config.yaml).

```yaml
vault: ~/agent-memory              # required here or in the environment
default_namespace: default
redact_secrets: true
features:
  visibility: true
  receipts: false
  companion: false
  hooks: false
  git_autocommit: false
companion:
  max_chars: 3000
```

## Settings

| Key | Environment variable | Default | Meaning |
|---|---|---|---|
| `vault` | `AGENT_MEM_VAULT_VAULT` | none, required | Path of the vault folder. `~` is expanded. |
| `default_namespace` | `AGENT_MEM_VAULT_DEFAULT_NAMESPACE` | `default` | Namespace used when a tool call omits one. |
| `redact_secrets` | `AGENT_MEM_VAULT_REDACT_SECRETS` | `true` | Redact token, key and password patterns before anything is written. Accepts `true` or `false`. |
| `features.visibility` | none | `true` | `private` records stay out of the brief and of listings unless `include_private` is passed. |
| `features.receipts` | none | `false` | Adds the `receipt` kind and the `write_receipt` tool. |
| `features.companion` | none | `false` | Adds the `get_companion` and `update_companion` tools. |
| `features.hooks` | none | `false` | Turns on the `hook session-start` and `hook stop` outputs. |
| `features.git_autocommit` | none | `false` | Commit each change in the vault's git repository. Never pushes. |
| `companion.max_chars` | none | `3000` | Size cap for each companion card. |

A bad value is reported with the key that caused it, and the command exits with status 2.

## Features

### visibility (on by default)

A record has `visibility: public | internal | private` (default `internal`) and
`validity: valid | rejected`.

- `private` records never appear in `get_project_brief`. They appear in `search_memory`,
  `list_contexts` and `read_latest_context` only when `include_private` is true.
- `rejected` records stay on file but are left out of the brief, and listings mark them `[rejected]`.
  A rejection needs a `rejected_reason`.
- Change them with `update_memory`, or by editing the note in Obsidian.

### receipts

Immutable records of finished work: files and commits touched, plus optional harness and session.
Created with `write_receipt`. `update_memory` and `supersedes` refuse receipts. Without the feature,
`receipt/` folders are not scanned.

### companion

Two short cards per namespace, `last-session` and `threads`, stored under
`<namespace>/_companion/`. `update_companion` replaces a card whole; a card over `max_chars` is
rejected with a request to compact it, and nothing is written. `get_project_brief` appends the
last-session card.

### hooks

`agent-mem-vault hook session-start --client claude|codex` prints the project brief (capped at 9000
characters) for the namespace `project/<git root folder name>`. `hook stop` prints a nudge to record
decisions, once per change in the working tree, and stays silent outside a git work tree or when
the client says a stop hook is already active. With the feature off both print nothing and exit 0.
`hook print-config` works either way. Every hook path exits 0 on error and logs the reason to stderr,
so a hook never blocks your session.

### git_autocommit

After each write, if the vault is a git repository, the touched paths are committed with a message
like `avm: create decision 3f9a2c1e`. The server never pushes. The `.gitignore` entry for
`.agent-mem-vault/` that it adds is left for you to commit.

## Command line

| Command | Purpose |
|---|---|
| `agent-mem-vault` | Run the MCP server over stdio. |
| `doctor` | Check config, vault, record counts, issues and git state. |
| `list`, `search QUERY`, `handoffs` | Human-readable views. Filters: `--namespace`, `--agent`, `--limit`, and for `list` and `search` also `--type`, `--kind`, `--tag`, `--include-private`; `handoffs` takes `--status`. |
| `hook ...` | Client hook entry points. |
| `--version` | Print the version. |

## Security defaults

Inputs are length limited and control characters are stripped. Paths that resolve outside the vault
are refused. Redaction covers GitHub and Slack tokens, `sk-` style keys, and `api_key=`, `token=`,
`secret=` and `password=` assignments.
