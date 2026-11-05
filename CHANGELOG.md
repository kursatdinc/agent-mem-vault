# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

## [2.1.0] - 2026-11-05

The brief tells an open risk from a mitigated one, search and listings stop surfacing records that
were closed, and search favours recent records.

### Removed

- `review_by` on risks: the `review_by` parameter of `save_memory` and `update_memory` (MCP tools and
  store), its date validation, and the `review_by` column of the dashboard's active decisions and
  risks view. Nothing read it. A `review_by` already in a record file still loads and stays on
  update, and a `review_by` argument from an older client is ignored.

### Changed

- Each active-record line of the brief shows the record's status, `- [<kind>: <status>] <title> - id
  <id8>` (`- [<kind>]` when there is none), so `[risk: mitigated]` no longer reads like an open risk.
- `search_memory` and `list_contexts` leave out closed records by default, the same ones the brief
  leaves out: any record with `superseded_by`, and any record whose status is `superseded` or
  `resolved`, a free-text status of a task or note included. Pass `include_closed: true` (on the CLI,
  `--include-closed`) to see them. `read_latest_context` still returns them.
- `search_memory` (and `search` on the CLI) ranks recent records higher: the text score is multiplied
  by `0.5 + 0.5 x 2^(-age_days / 30)`, the age taken from `created`, so a match counts fully when new,
  three quarters at 30 days and never less than half. A record with more than twice another's text
  score still ranks above it however old it is; ties still go to the newest record.

### Upgrading from 2.0.x

Upgrade the package; no migration is needed. A `review_by` argument is ignored, so a call that also
changes something else still succeeds without storing the date, while an `update_memory` call that
passes only `review_by` now fails with `nothing to update`; drop it from agent instructions. An
existing `_dashboards/memory.base` keeps its `review_by` column, since the dashboard is written only
when absent: delete the file to get the new one on the next write, or remove the `note.review_by`
line yourself. To find an old decision that was superseded, search with `include_closed`.

## [2.0.1] - 2026-11-05

Hubs now link everything the server writes, so no agent-mem-vault note is an orphan in Obsidian's
graph.

### Added

- `agent-mem-vault rebuild-hubs [SLUG ...]` rebuilds the hub of each given namespace folder, or of
  every one, prints one line per file it wrote or removed, reports an unknown folder and skips it, and
  commits with `features.git_autocommit`. Scripts such as a vault sync job call it instead of the
  store's internal hub refresh.

### Changed

- The hub ends with a `## companion` section linking the namespace's existing companion cards and a
  line linking `_dashboards/memory.base`.
- Writing a companion card refreshes the namespace hub and commits it with the card, so a first card
  is linked at once.
- `migrate --apply` ends by rebuilding every hub and prints each touched hub file, so one command
  upgrades a 2.0.0 vault's hubs; with no legacy handoffs left it still rebuilds them and commits the
  result as `avm: rebuild hubs`.

### Fixed

- Companion cards and the dashboard showed as orphan nodes in the graph.
- A namespace left with no records and no cards (for example after its handoffs were archived) kept
  an empty hub; its generated hub is now removed, and its folder once empty. Only a file with the
  hub's own frontmatter (`generated: true`, `agent-written: true` and the folder's namespace) is
  removed, so a note you wrote at the hub path stays.
- Records created in the same second were ordered in the hub by file modification time, which differs
  on each machine that syncs the vault, so the machines kept rewriting each other's hubs. They are
  now ordered by path.
- A git autocommit no longer fails when one of its paths was neither on disk nor tracked.

### Upgrading from 2.0.0

Upgrade the package, then run `agent-mem-vault migrate --apply` (or `agent-mem-vault rebuild-hubs`)
once on one machine and sync the vault.

## [2.0.0] - 2026-11-05

A new memory model: open work lives in two companion cards per project, decisions and risks have a
lifecycle, and the brief says when memory needs consolidating. Handoffs are gone. This release breaks
the 1.x tool surface; see *Upgrading from 1.x* below.

### Removed

- The handoff kind and its tools: `create_handoff`, `read_handoff`, `peek_handoff`, `list_handoffs`,
  `ack_handoff` and `reopen_handoff`, the `handoffs` CLI command, the `handoffStatus` and `type`
  filters of `search_memory` and `list_contexts` (and `--type` on the CLI), and the pending-handoffs
  dashboard view. Open work goes in the `threads` companion card; to move work to another machine,
  push a wip branch and let the synced vault carry the threads card.

### Added

- `agent-mem-vault migrate --dry-run | --apply` moves every legacy handoff of every namespace to
  `<ns-dir>/_archive/handoffs/`, where reads never look, refreshes the hub notes, and commits the
  move when the vault is a git work tree. `doctor` points at it while legacy handoffs remain.
- Lifecycle statuses: a decision is `accepted` (default) or `superseded`; a risk is `open` (default),
  `mitigated` or `resolved`. Other kinds keep a free-text status.
- `review_by` (`YYYY-MM-DD`) on risks, in `save_memory` and `update_memory`.
- `supersedes` on `update_memory` and `create_snapshot`. Superseding a decision sets it to
  `superseded`, superseding a risk sets it to `resolved`.
- Every id parameter (`update_memory`, `get_links`, `supersedes`) accepts a unique prefix of at least
  eight characters.

### Changed

- `features.companion` is on by default. The threads card holds one line per open work thread,
  `- <branch or topic>: <status>; next: <step>`; any other line is refused, and an empty string
  clears the card.
- `get_project_brief` returns, in order: the last-session card, the threads card, the latest snapshot
  that is not superseded, private or rejected, the active records created after that snapshot (kind,
  title and id), and a final `Consolidation due: <reason>` line when that snapshot is older than seven
  days, or when there is no snapshot but there are active records. The header is
  `**Project brief for <namespace>**`; its `limit` now caps the listed active records.
- Listing, search and `read_latest_context` lines show the status and the first eight characters of
  the id: `1. [decision: accepted] (alpha) Pick storage - planner - <time> - id 3f9a2c1e`. The
  `context/` prefix is gone.
- A tool call or CLI listing without a namespace uses `project/<git root name>` of the working
  directory; `default_namespace` applies only outside a git work tree. `doctor` prints that rule.
- The stop hook asks the agent to update the companion cards, and to save a decision or risk only
  when one was made or verified. For Codex it now prints `{"decision": "block", "reason": ...}` like
  for Claude Code: Codex rejects plain text at `Stop`.
- The dashboard's decisions view lists only active decisions and risks and shows `review_by`.

### Upgrading from 1.x

1. Upgrade the package: `uv tool upgrade agent-mem-vault` (or `uv tool install agent-mem-vault`), and
   restart your agents so `uvx` starts the 2.0.0 server.
2. Check your config file: a `features.companion: false` line copied from the 1.x example keeps the
   companion cards and their tools off; remove it or set it to `true`. The hooks run only with
   `features.hooks: true`.
3. Preview, then archive the old handoffs, on one machine:
   `agent-mem-vault migrate --dry-run`, then `agent-mem-vault migrate --apply`. Sync the vault
   repository to your other machines afterwards.
4. Re-register the hooks: print the snippet with
   `agent-mem-vault hook print-config --client claude` (and `--client codex`) and replace the old
   entries in your client settings, so the new stop nudge is used.
5. Update agent instructions that call handoff tools: read the brief at session start, keep
   `last_session` and `threads` current with `update_companion`, and record a decision or risk only
   when one was made or verified.
6. Optional: delete `_dashboards/memory.base` to get the new dashboard on the next write; an existing
   dashboard is never overwritten.

Decisions saved with a 1.x status outside the new lifecycle (for example `proposed`) still load; only
a new status is validated.

## [1.0.0] - 2026-10-29

First stable release.

### Added

- MCP server that stores agent memory as one Markdown note per record in an Obsidian vault, with
  YAML frontmatter that Obsidian reads as properties. No database and no persistent index; no
  network calls.
- Typed records: `decision`, `risk`, `handoff`, `snapshot`, `note`, `assumption`, `task`, and
  optional `receipt`, grouped by namespace (usually `project/<repo>`).
- Nineteen MCP tools: `save_memory`, `save_context`, `create_snapshot`, `update_memory`,
  `create_handoff`, `read_handoff`, `peek_handoff`, `ack_handoff`, `reopen_handoff`, `list_handoffs`,
  `get_project_brief`, `search_memory`, `list_contexts`, `read_latest_context`, `get_links`,
  `list_issues`, plus `write_receipt`, `get_companion` and `update_companion` behind feature flags.
- Handoff lifecycle (pending, read, acknowledged, reopened) and `supersedes` chains for decisions
  and handoffs.
- Stemmed free-text search over title, content and tags.
- Hand-edit safety: per-record revisions, conflict replies instead of silent overwrites, and
  `list_issues` for notes that cannot be parsed. Writes are serialized with a file lock and replaced
  atomically.
- Generated hub notes per namespace, named after their folder so Obsidian's graph labels them with the
  project name, and a Bases dashboard (`_dashboards/memory.base`) for pending
  handoffs, open decisions and risks.
- Record visibility (`private` records stay out of automatic context) and validity (`rejected`
  records stay on file but stop steering agents).
- Secret redaction on by default.
- Optional features: receipts, companion cards, client hooks for Claude Code and Codex, and git
  autocommit in the vault repository (never pushes).
- CLI: `doctor` (with Obsidian CLI unresolved-link parity), `list`, `search`, `handoffs`,
  and `hook`.
- Demo vault in `examples/demo-vault`, regenerated by `scripts/build_demo_vault.py`, and example
  configuration for Claude Code and Codex.
- Wiki, contributing guide, code of conduct, security policy, issue and pull request templates,
  and Dependabot configuration.
- Release pipeline: pushing a `vX.Y.Z` tag builds the sdist and wheel, attaches them to a GitHub
  release, and publishes to PyPI through Trusted Publishing. See `docs/RELEASING.md`.

[Unreleased]: https://github.com/kursatdinc/agent-mem-vault/compare/v2.1.0...HEAD
[2.1.0]: https://github.com/kursatdinc/agent-mem-vault/compare/v2.0.1...v2.1.0
[2.0.1]: https://github.com/kursatdinc/agent-mem-vault/compare/v2.0.0...v2.0.1
[2.0.0]: https://github.com/kursatdinc/agent-mem-vault/compare/v1.0.0...v2.0.0
[1.0.0]: https://github.com/kursatdinc/agent-mem-vault/releases/tag/v1.0.0
