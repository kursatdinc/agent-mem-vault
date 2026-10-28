# agent-vault-memory: design

Status: pre-alpha. This file is the contract the implementation follows.

## Purpose
A local MCP server that gives coding agents (Claude Code, Codex, any MCP client) durable, typed,
shared memory whose single source of truth is an Obsidian vault: one Markdown file per record,
YAML frontmatter, editable by a human in Obsidian. The server keeps no database and no persistent
index; every query reads the files. Obsidian's own index (graph view, backlinks, Bases) is the
only persistent index.

## Non-goals
No embeddings, no SQLite, no network calls, no dependency on the Obsidian app being open, never
writes `.obsidian/`, never launches Obsidian, never pushes git.

## Runtime and packaging
- Python >= 3.12, src layout, package `agent_vault_memory`, console script `agent-vault-memory`.
- Runtime dependencies: `mcp` (official SDK, FastMCP), `PyYAML`, `PyStemmer`. Nothing else.
- Dev: `uv`, `pytest`, `ruff`. Tests use temporary vaults with synthetic data only.
- `agent-vault-memory` with no arguments runs the MCP server over stdio. Subcommands:
  `doctor`, `list`, `search`, `handoffs`, `import`, `hook`.

## Configuration
Precedence: built-in defaults < config file < environment variables.
- Config file: `$AGENT_VAULT_MEMORY_CONFIG`, else `~/.config/agent-vault-memory/config.yaml`.
- Env: `AGENT_VAULT_MEMORY_VAULT` (vault path), `AGENT_VAULT_MEMORY_DEFAULT_NAMESPACE`,
  `AGENT_VAULT_MEMORY_REDACT_SECRETS` (`true`/`false`).

```yaml
vault: ~/path/to/vault          # required (or env)
default_namespace: default
redact_secrets: true
kinds: [note, decision, assumption, task, risk, handoff, snapshot]   # receipt added when enabled
features:
  receipts: false
  companion: false
  visibility: true
  hooks: false
  git_autocommit: false
companion:
  max_chars: 3000
```

## Vault layout
```
<vault>/
  <namespace-slug>/
    _index.md                       # generated hub note, links every record of the namespace
    _companion/last-session.md      # companion feature
    _companion/threads.md           # companion feature
    <kind>/<YYYY-MM-DD>-<title-slug>-<id8>.md
  _dashboards/memory.base           # generated only if absent
  .agent-vault-memory/              # server-private: lock file, tmp/ for atomic writes
```
- `namespace-slug`: namespace lowercased, every run of characters outside `[a-z0-9]` replaced by
  `-`, trimmed (`project/ai-agents` -> `project-ai-agents`). The frontmatter `namespace` is
  authoritative; the folder is cosmetic.
- `title-slug`: same rule on the title, cut to 48 characters. `id8`: first 8 hex chars of the id.
- The filename is fixed at creation. Title edits never rename files.
- A file is a record candidate only if it sits at `<ns-slug>/<kind>/*.md` with `<kind>` a known
  kind. Everything else (user notes, hubs, dashboards, companion cards) is ignored by record reads.
- `.agent-vault-memory/` is added to the vault's `.gitignore` when the server creates it inside a
  git repository.

## Record format
```markdown
---
id: 3f9a2c1e-...            # uuid4 string, never changes
kind: decision
namespace: project/ai-agents
agent: claude-code
title: Use ADK 2.11 for the agent runtime
created: 2026-10-28T09:13:05Z
updated: 2026-10-28T09:13:05Z
revision: 1
visibility: internal         # public | internal | private
validity: valid              # valid | rejected
tags: [runtime, adk]
status: accepted             # optional free text
related_files: ["[[...]]"]   # optional
supersedes: ["[[project-ai-agents/decision/2026-09-02-old-a1b2c3d4]]"]   # optional
superseded_by: "[[...]]"     # optional
next_action: ...             # optional
branch: ...                  # optional
commit: ...                  # optional
# handoff only:
to: claude-code
read: false
read_at: 2026-10-28T10:00:00Z
# rejected only:
rejected_reason: ...
agent-written: true
---
<content, Markdown, written in English>

<!-- avm:related:start -->
## Related
- Supersedes [[project-ai-agents/decision/2026-09-02-old-a1b2c3d4|Old title]]
<!-- avm:related:end -->
```
- Only keys with a value are written. One type per key across the vault. Timestamps are UTC ISO
  8601 with `Z`.
- Links are full vault-relative paths without `.md`. They go in frontmatter and in the generated
  Related block; the server rewrites only the text between the `avm:related` markers.
- Memory content is always English. Tool descriptions say so; nothing detects language.
- Handoff content keeps the legacy shape: `## Summary\n<summary>\n\n## Full Context\n<context>`,
  title `Handoff to <to>`.

## Writes and concurrency
- Every write takes an exclusive `fcntl.flock` on `<vault>/.agent-vault-memory/lock` (timeout 5 s,
  then a clear error), so two server processes never interleave read-modify-write.
- Files are written to `<vault>/.agent-vault-memory/tmp/` and moved into place with `os.replace`
  (atomic on one filesystem). Leftover tmp files at startup are incomplete writes: removed and
  logged to stderr.
- Updates (read/ack/reopen a handoff, supersede marking, update_memory) re-read the file under the
  lock, require `revision` to match the expected one when the caller passes `expected_revision`,
  write `revision + 1`, and re-check the file hash immediately before `os.replace`; if a human
  changed it in between, retry once, then return a conflict. Nothing is overwritten silently.
- After each write: regenerate the namespace hub `_index.md`; create `_dashboards/memory.base` if
  absent; if `features.git_autocommit` and the vault is a git repo, commit the touched paths with
  message `avm: <op> <kind> <id8>` (never push). Hub, dashboard or git failures are logged to
  stderr and never fail the write.

## Reads
- Each query walks the vault (skipping dot-directories), parses candidate records, filters, ranks
  and forgets. No cache on disk.
- Free text: tokens are `\w+` lowercased and stemmed with PyStemmer `english` (in-process memo).
  A record matches when every query stem occurs in title + content + tags. Score = 3 x title stem
  hits + content stem hits; ties broken by newest `created`.
- Ordering for list operations: newest `created` first (the legacy store was newest-first).
- Invalid candidates (unparseable YAML, missing `id`/`kind`/`namespace`, unknown kind, duplicate
  id) are skipped and reported through `list_issues` and `doctor`; they are never modified.
- Link resolution (for `get_links` and the Related block) follows Obsidian's rules: exact
  vault-relative path, else basename match with shortest path winning ties, else frontmatter
  `aliases`; strip `#heading`, `|display`, leading `!`.

## Tools (MCP)
The first 13 keep the names, parameters and reply texts of shared-memory-mcp so existing
instructions keep working.

| Tool | Notes |
|---|---|
| `save_context` | kind `note` |
| `save_memory` | kind, title, content, tags, status, relatedFiles, branch, commit, nextAction, + `supersedes` (ids) |
| `create_handoff` | namespace, to, summary, context, + `supersedes` (ids: those pending handoffs become read with `superseded_by`) |
| `create_snapshot` | kind `snapshot` |
| `get_project_brief` | latest snapshot, else the 10 most recent records; excludes private and rejected |
| `read_handoff` | newest pending handoff for the agent, marks it read |
| `peek_handoff`, `ack_handoff`, `reopen_handoff`, `list_handoffs` | as before |
| `read_latest_context`, `list_contexts`, `search_memory` | as before; `type` is `handoff` for kind handoff, else `context` |
| `update_memory` | new: id, expected_revision, any of title/content/tags/status/visibility/validity/rejected_reason |
| `get_links` | new: outgoing links and backlinks of a record |
| `list_issues` | new: invalid record candidates with reason |
| `write_receipt` | feature `receipts`: immutable kind `receipt` with refs (files, commits), harness, session |
| `get_companion`, `update_companion` | feature `companion`: per-namespace last-session and threads cards, `max_chars` enforced (over the cap -> error asking the agent to compact) |

Visibility (feature on): `private` records never appear in the brief and appear in search/list only
with `include_private: true`. Validity: `rejected` records stay, are excluded from the brief and are
marked in search output.

## CLI
- `doctor`: config, vault path, `.obsidian/` present, record count by kind, issues, tmp leftovers,
  git status (branch, dirty, ahead/behind). If Obsidian is running (`pgrep -x Obsidian`) and the
  `obsidian` CLI exists, compare its unresolved-link count for the memory folders with ours and
  print differences. Never launches Obsidian.
- `list`, `search`, `handoffs`: human-readable views of the same store functions.
- `import <contexts.json>`: one-time import from a shared-memory-mcp JSON store. Keeps ids and
  timestamps; a handoff whose summary starts with `Supersedes <id8>` marks the referenced pending
  handoff (prefix match, same namespace) as read with `superseded_by`. Idempotent: ids already in
  the vault are skipped. The source file is never modified.
- `hook session-start|stop --client claude|codex` (feature `hooks`): prints the hook payload
  (session-start: the project brief for the namespace derived from the git root basename as
  `project/<basename>`; stop: a nudge to record decisions). `hook print-config --client ...` prints
  the settings snippet to install; the CLI never edits client settings itself.

## Security
Inputs are length-limited and control characters stripped (limits ported from shared-memory-mcp).
Secret redaction (token, key and password patterns) is on by default. Paths resolving outside the
vault are refused.
