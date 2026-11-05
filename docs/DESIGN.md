# agent-mem-vault: design

Status: stable. This file is the contract the implementation follows.

## Purpose
A local MCP server that gives coding agents (Claude Code, Codex, any MCP client) durable, typed,
shared memory whose single source of truth is an Obsidian vault: one Markdown file per record,
YAML frontmatter, editable by a human in Obsidian. The server keeps no database and no persistent
index; every query reads the files. Obsidian's own index (graph view, backlinks, Bases) is the
only persistent index.

## Memory model
The layers follow CoALA (working, episodic, semantic, procedural memory):
- Working memory is the agent's context window. The server does not store it.
- Episodic and prospective memory are two companion cards per namespace, `last_session` (what the
  last session did, what is unverified, the next step) and `threads` (one line per open work
  thread). Both are overwritten, never appended, and the SessionStart hook loads them every session.
- Semantic memory is `decision` and `risk` records with a lifecycle, plus `snapshot` records that
  summarize a namespace. Consolidation folds what accumulated since the last snapshot into a new one
  and closes stale records through `supersedes`; with `features.git_autocommit` every change is a
  vault git commit, so it can be reverted.
- Procedural memory is the agents' instruction files and skills, outside this server.
- Not stored: production incidents (they belong in the issue tracker) and anything a client keeps
  in its own memory. A risk is recorded only for a lasting constraint.

## Non-goals
No embeddings, no SQLite, no network calls, no dependency on the Obsidian app being open, never
writes `.obsidian/`, never launches Obsidian, never pushes git.

## Runtime and packaging
- Python >= 3.12, src layout, package `agent_mem_vault`, console script `agent-mem-vault`.
- Runtime dependencies: `mcp>=2.3,<3` (official SDK, `MCPServer`; expected failures are raised as `ToolError` so callers read the text), `PyYAML`, `PyStemmer`. Nothing else.
- Dev: `uv`, `pytest`, `ruff`. Tests use temporary vaults with synthetic data only.
- `agent-mem-vault` with no arguments runs the MCP server over stdio. Subcommands:
  `doctor`, `list`, `search`, `migrate`, `hook`.

## Configuration
Precedence: built-in defaults < config file < environment variables.
- Config file: `$AGENT_MEM_VAULT_CONFIG`, else `~/.config/agent-mem-vault/config.yaml`.
- Env: `AGENT_MEM_VAULT_VAULT` (vault path), `AGENT_MEM_VAULT_DEFAULT_NAMESPACE`,
  `AGENT_MEM_VAULT_REDACT_SECRETS` (`true`/`false`).
- A tool call or CLI listing without a namespace uses `project/<basename of the git root>` of the
  process's working directory (the rule the hooks use); `default_namespace` applies only outside a git
  work tree.

```yaml
vault: ~/path/to/vault          # required (or env)
default_namespace: default      # fallback outside a git work tree
redact_secrets: true
kinds: [note, decision, assumption, task, risk, snapshot]   # receipt added when enabled
features:
  receipts: false
  companion: true
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
    <namespace-slug>.md             # generated hub note: links the records, the cards and the dashboard
    _companion/last-session.md      # companion feature
    _companion/threads.md           # companion feature
    _archive/handoffs/*.md          # 1.x handoffs moved by `migrate`; never read
    <kind>/<YYYY-MM-DD>-<title-slug>-<id8>.md
  _dashboards/memory.base           # generated only if absent
  .agent-mem-vault/              # server-private: lock file, tmp/ for atomic writes
```
- `namespace-slug`: namespace lowercased, every run of characters outside `[a-z0-9]` replaced by
  `-`, trimmed (`project/harbor-api` -> `project-harbor-api`). The frontmatter `namespace` is
  authoritative; the folder is cosmetic.
- `title-slug`: same rule on the title, cut to 48 characters. `id8`: first 8 hex chars of the id.
- The filename is fixed at creation. Title edits never rename files.
- A file is a record candidate only if it sits at `<ns-slug>/<kind>/*.md` with `<kind>` a known
  kind. Everything else (user notes, hubs, dashboards, companion cards, the archive, and 1.x
  `handoff/` folders) is ignored by record reads.
- `.agent-mem-vault/` is added to the vault's `.gitignore` when the server creates it inside a
  git repository.

## Record format
```markdown
---
id: 3f9a2c1e-...            # uuid4 string, never changes
kind: decision
namespace: project/harbor-api
agent: claude-code
title: Use ADK 2.11 for the agent runtime
created: 2026-10-28T09:13:05Z
updated: 2026-10-28T09:13:05Z
revision: 1
visibility: internal         # public | internal | private
validity: valid              # valid | rejected
tags: [runtime, adk]
status: accepted             # decision: accepted | superseded; risk: open | mitigated | resolved; else free text
related_files: ["[[...]]"]   # optional
supersedes: ["[[project-harbor-api/decision/2026-09-02-old-a1b2c3d4]]"]   # optional
superseded_by: "[[...]]"     # optional
next_action: ...             # optional
branch: ...                  # optional
commit: ...                  # optional
# rejected only:
rejected_reason: ...
agent-written: true
---
<content, Markdown, written in English>

<!-- avm:related:start -->
## Related
- Supersedes [[project-harbor-api/decision/2026-09-02-old-a1b2c3d4|Old title]]
<!-- avm:related:end -->
```
- Only keys with a value are written. One type per key across the vault. Timestamps are UTC ISO
  8601 with `Z`.
- Links are full vault-relative paths without `.md`. They go in frontmatter and in the generated
  Related block; the server rewrites only the text between the `avm:related` markers.
- Memory content is always English. Tool descriptions say so; nothing detects language.
- Lifecycle: a new decision defaults to `accepted` and a new risk to `open`. A status outside the
  kind's states is refused on save and update; a hand-written legacy status still loads. Superseding
  sets `superseded_by` on the old record and closes it: a decision becomes `superseded`, a risk
  `resolved`; other kinds keep their status.
- Ids: every id parameter takes the full id or a unique prefix of at least 8 characters; an
  ambiguous prefix is an error naming the number of matches.

## Writes and concurrency
- Every write takes an exclusive `fcntl.flock` on `<vault>/.agent-mem-vault/lock` (timeout 5 s,
  then a clear error), so two server processes never interleave read-modify-write.
- Files are written to `<vault>/.agent-mem-vault/tmp/` and moved into place with `os.replace`
  (atomic on one filesystem). Leftover tmp files at startup are incomplete writes: removed and
  logged to stderr.
- Updates (supersede marking, update_memory) re-read the file under the lock, require `revision` to
  match the expected one when the caller passes `expected_revision`, write `revision + 1`, and re-check the file hash immediately before `os.replace`; if a human
  changed it in between, retry once, then return a conflict. Nothing is overwritten silently.
- After each write: regenerate the namespace hub `<namespace-slug>/<namespace-slug>.md`; create `_dashboards/memory.base` if
  absent; if `features.git_autocommit` and the vault is a git repo, commit the touched paths with
  message `avm: <op> <kind> <id8>` (never push). Hub, dashboard or git failures are logged to
  stderr and never fail the write. A companion card write regenerates the hub as well and commits it
  with the card (`avm: update companion <ns-slug>`).
- The hub lists the records grouped by kind, newest first (records of the same second by path, never by
  file time, so every synced machine renders the same hub), then a `## companion` section linking each
  card file that exists (`[[<ns-slug>/_companion/threads|threads]]`), then the line
  `Dashboard: [[_dashboards/memory.base|memory dashboard]]`, so no note the server writes is a graph
  orphan. A namespace with no records and no cards gets no hub: an existing hub is removed, and its
  folder too once empty. Only a file with the whole hub frontmatter (`generated: true`,
  `agent-written: true` and a `namespace` of that folder) counts as a hub; any other file at the hub
  path is left alone.
- Decision: the hub is named after its folder (`proj/proj.md`) because Obsidian's graph labels nodes by file
  name, so every project shows under its own name instead of a column of identical `_index` nodes.
- Decision: the hub is skipped when unchanged (it holds no timestamps) and is never written over a file
  without `generated: true`. Autocommit uses `git add` plus a path-limited `git commit` on exactly the
  touched paths; the vault's `.gitignore` edit is left for the user to commit.
- Decision: record frontmatter is always block style with inline lists (a record without lists would
  otherwise render as a single `{...}` line, which Obsidian does not read as properties).

## Reads
- Each query walks the vault (skipping dot-directories), parses candidate records, filters, ranks
  and forgets. No cache on disk.
- Free text: tokens are `\w+` lowercased and stemmed with PyStemmer `english` (in-process memo).
  A record matches when every query stem occurs in title + content + tags. Score = 3 x title stem
  hits + content stem hits; ties broken by newest `created`.
- Ordering for list operations: newest `created` first.
- `search_memory` and `list_contexts` hide closed records unless `include_closed` is true
  (`--include-closed` on the CLI). Closed is the opposite of active in the brief: `superseded_by` is
  set, or the status is `superseded` or `resolved`. `read_latest_context` does not filter them.
- Invalid candidates (unparseable YAML, missing `id`/`kind`/`namespace`, unknown kind, duplicate
  id) are skipped and reported through `list_issues` and `doctor`; they are never modified.
- Link resolution (for `get_links` and the Related block) follows Obsidian's rules: exact
  vault-relative path, else basename match with shortest path winning ties, else frontmatter
  `aliases`; strip `#heading`, `|display`, leading `!`.
- Decision: link scanning reads wikilinks from every frontmatter string and from the body outside code
  spans and fences; matching ignores case after the exact-path attempt.

## Tools (MCP)
The names, parameters and reply texts below are stable: agent instructions may depend on them.

| Tool | Notes |
|---|---|
| `save_context` | kind `note` |
| `save_memory` | kind, title, content, tags, status, relatedFiles, branch, commit, nextAction, + `supersedes` (ids) |
| `create_snapshot` | kind `snapshot`, + `supersedes` (ids); a superseded snapshot drops out of the brief |
| `get_project_brief` | see *Brief* below |
| `read_latest_context`, `list_contexts`, `search_memory` | filters: agent, tags, kind, limit, include_private; `list_contexts` and `search_memory` also include_closed |
| `update_memory` | id, expected_revision, any of title/content/tags/status/visibility/validity/rejected_reason, + `supersedes` (ids, appended to the record's list); kind, namespace and id are not parameters (extra arguments are ignored, so an update that passes only them fails with `nothing to update`); a stale `expected_revision` is a normal reply naming the current revision, a file changed twice during the write is a tool error |
| `get_links` | outgoing links and backlinks of a record |
| `list_issues` | invalid record candidates with reason |
| `write_receipt` | feature `receipts`: immutable kind `receipt` with refs (files, commits), harness, session |
| `get_companion`, `update_companion` | feature `companion` (on by default): per-namespace last-session and threads cards, `max_chars` enforced (over the cap -> error asking the agent to compact) |

Every listing, search and `read_latest_context` line ends with `id <first 8 characters of the id>`, and
listing lines carry the status in their bracket group: `1. [decision: accepted] (alpha) Pick storage -
planner - <time> - id 3f9a2c1e`.

### Brief
`get_project_brief` returns `**Project brief for <namespace>**` and then, each part only when present:
1. the last-session card (`## Last session`) and the threads card (`## Threads`), while the
   companion feature is on;
2. the latest snapshot that is not superseded, private or rejected
   (`## Snapshot: <title> (<YYYY-MM-DD>, id <id8>)` and its content);
3. the active records created after that snapshot, or all of them when there is none
   (`## Since the snapshot` / `## Active records`), newest first, one
   `- [<kind>: <status>] <title> - id <id8>` line each (`- [<kind>]` when the record has no status), at
   most `limit` (default 10) plus `- ... and <n> more`. Active means not a snapshot, no
   `superseded_by`, status not `superseded` or `resolved`, not private, not rejected;
4. `Consolidation due: latest snapshot is <n> days old` when that snapshot is older than seven days,
   or `Consolidation due: no snapshot yet and <n> active records` when there is no snapshot but there
   are active records.

An empty namespace reads `No saved memory found for namespace: <namespace>`.

Visibility (feature on): `private` records never appear in the brief and appear in search/list only
with `include_private: true`. Validity: `rejected` records stay, are excluded from the brief and are
marked in search output.

- Decision: `features.visibility` and `features.companion` are on by default (as the config example
  above shows); every other feature is off. The optional `include_private` parameter exists on
  `list_contexts`, `search_memory` and `read_latest_context` in both states and only has an effect
  while the feature is on. The `[rejected]` mark sits inside the bracket group of a listing line
  (`[note [rejected]]`, `[decision: accepted [rejected]]`) and is printed only while the feature is on. `list` and `search` on the CLI take `--include-private`.
- Decision: `receipt` is a known kind only while `features.receipts` is on; with it off, `receipt/`
  folders are not scanned. Receipts are immutable: `update_memory` and `supersedes` refuse them. `refs`
  are written to frontmatter and to the Related list as code spans, not wikilinks, because they are
  repository paths and SHAs that would otherwise count as unresolved links. `receipt` is not accepted by
  `save_memory`; it is only created by `write_receipt`.
- Decision: the companion cap applies to each card separately (`last_session`, `threads`), measured after
  redaction, and an update replaces the whole card. If either card is over the cap nothing is written.
  Every non-blank line of `threads` must read `- <branch or topic>: <status>; next: <step>`, and a
  line is removed when its thread is done; an empty `threads` clears the card. Cards carry
  `kind: companion` and `agent-written: true`; a file at a card path without `kind: companion` is
  never overwritten.
- Decision: there is no handoff kind. Open work lives in `threads`; moving work to another machine is a
  wip branch plus the synced threads card.

## CLI
- `doctor`: config, vault path, `.obsidian/` present, record count by kind, issues, tmp leftovers,
  git status (branch, dirty, ahead/behind). If Obsidian is running (`pgrep -x Obsidian`) and the
  `obsidian` CLI exists, compare its unresolved-link count for the memory folders with ours and
  print differences. Never launches Obsidian.
  Decision: parity runs `obsidian unresolved verbose format=json` in the vault directory and expects a JSON
  list of entries with a link and its source files (the CLI docs do not pin the shape); anything else
  prints "output not understood" instead of failing.
- `list`, `search`: human-readable views of the same store functions.
- `migrate --dry-run | --apply`: moves every file in a 1.x `<ns-dir>/handoff/` folder to
  `<ns-dir>/_archive/handoffs/` and prints each move. `--apply` takes the lock, rewrites links between
  the moved files to their archive path, skips (and reports) a taken archive path, removes the emptied
  `handoff/` folder, rebuilds every hub as `rebuild-hubs` does (one command upgrades a 2.0.0 vault's
  hubs), prints each touched hub file, and commits all of it as `avm: migrate <n> legacy handoffs`
  (`avm: rebuild hubs` when nothing moved) when the vault is a git work tree. `--dry-run` writes
  nothing. `doctor` prints the number of legacy handoffs while any remain.
- `rebuild-hubs [SLUG ...]`: regenerates the hub of each given namespace folder slug, or of every
  namespace folder (a top-level folder whose name is its own slug, plus the slug of every record's
  namespace) when none is given, under the lock, and removes the hub of a namespace that has no records
  and no cards as above. Prints `wrote <path>` or `removed <path>` per touched file, or
  `Hubs are up to date.`; an unknown slug is reported on stderr and skipped, and the exit status is 0.
  With `features.git_autocommit` and a git work tree the touched files are committed as
  `avm: rebuild hubs`. It is the public entry point for scripts (for example a vault sync job); the
  hub title takes the namespace of the folder's newest record, else the one its cards name.
  Decision: a removed file that git never tracked is left out of an autocommit instead of failing it.
- `hook session-start|stop --client claude|codex` (feature `hooks`): prints the hook payload
  (session-start: the project brief for the namespace derived from the git root basename as
  `project/<basename>`, the cwd basename outside a git work tree; stop: a nudge to update the companion
  cards, `threads` only when a thread opened or closed, and to record a decision or risk only when one
  was made or verified). `hook print-config --client ...` prints
  the settings snippet to install; the CLI never edits client settings itself.
  Decision: both events do nothing (empty output, exit 0) while `features.hooks` is off; `print-config`
  works regardless. Output conventions: session-start prints
  `{"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": ...}}` for Claude Code and
  plain text for Codex, capped at 9000 characters (a truncated brief ends with `[brief truncated]`,
  followed by the brief's `Consolidation due` line when it had one). The stop nudge is
  `{"decision": "block", "reason": ...}` for both clients (Codex rejects plain text at `Stop`), and is skipped when
  the input has `stop_hook_active: true`. The change signature (HEAD plus a hash of
  `git status --porcelain`) is stored per namespace in `<vault>/.agent-mem-vault/state/stop-<ns-slug>`;
  outside a git work tree the stop hook stays silent. Every hook path exits 0 on any error and logs the
  reason to stderr; the error path of a missing vault setting or vault directory included.

## Security
Inputs are length-limited and control characters stripped.
Secret redaction (token, key and password patterns) is on by default. Paths resolving outside the
vault are refused.
