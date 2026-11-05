# Tools Reference

Thirteen tools: ten always on, two that the `companion` feature (on by default) adds, and one behind
the `receipts` feature. Memory content is written in English; every tool description says so.

Conventions:

- `namespace` is optional everywhere. It defaults to `project/<git root name>` of the directory the
  server runs in, and to `default_namespace` from the
  [configuration](https://github.com/kursatdinc/agent-mem-vault/wiki/Configuration) outside a git
  work tree. Max 100 characters.
- Every id parameter (`id`, `supersedes`) takes the full id or a unique prefix of at least eight
  characters, such as the `id 3f9a2c1e` that ends each listing line. An ambiguous prefix is an error.
- `tags` is a list of up to 20 tags of at most 64 characters. In filters, a record must carry all
  the tags given.
- `limit` is a number; the default is 10.
- `include_private` only has an effect while `features.visibility` is on.
- Expected failures (invalid input, a vault problem) come back as tool errors whose text says what to
  fix. Not finding a record is a normal reply, such as `Memory not found.`
- Redaction is applied to content before it is written, when `redact_secrets` is on.

Kinds: `note`, `decision`, `assumption`, `task`, `risk`, `snapshot`, and `receipt` when the feature
is on. Statuses: a decision is `accepted` or `superseded`, a risk `open`, `mitigated` or `resolved`;
other kinds take free text.

Listing lines look like
`1. [decision: accepted] (project/harbor-api) Pin PostgreSQL 16 in CI and production - codex - 3/8/2026, 9:01:00 AM - id eb0b3836`.

## Write

### save_context

Save a free-form note (kind `note`).

| Parameter | Type | Required | Notes |
|---|---|---|---|
| `agent` | string, max 100 | yes | Who is saving, for example `claude-code`. |
| `title` | string, max 200 | yes | |
| `content` | string, max 200000 | yes | |
| `namespace` | string | no | |
| `tags` | list of strings | no | |

Returns `Context saved with ID: <id>`.

### save_memory

Save a structured record.

| Parameter | Type | Required | Notes |
|---|---|---|---|
| `agent` | string | yes | |
| `kind` | enum | yes | `note`, `decision`, `assumption`, `task`, `risk`, `snapshot`. `receipt` is created only by `write_receipt`. |
| `title` | string | yes | |
| `content` | string | yes | |
| `namespace` | string | no | |
| `status` | string, max 100 | no | decision: `accepted` (default) or `superseded`; risk: `open` (default), `mitigated` or `resolved`; other kinds: free text. |
| `review_by` | `YYYY-MM-DD` | no | Risks only: when to look at the risk again. |
| `relatedFiles` | list of strings, each max 500 | no | |
| `branch` | string, max 500 | no | |
| `commit` | string, max 500 | no | |
| `nextAction` | string, max 200 | no | |
| `tags` | list of strings | no | |
| `supersedes` | list of record ids | no | Records of the same namespace that this one replaces. Each is marked `superseded_by`; a superseded decision becomes `superseded` and a superseded risk `resolved`. Already-superseded records and receipts are refused. |

Returns `Memory saved with ID: <id>`.

### create_snapshot

Save a durable summary of a namespace (kind `snapshot`, tag `snapshot`). The latest snapshot that is
not superseded, private or rejected opens the snapshot part of `get_project_brief`.

| Parameter | Type | Required | Notes |
|---|---|---|---|
| `agent`, `title`, `content` | string | yes | |
| `namespace` | string | no | |
| `supersedes` | list of record ids | no | Usually the previous snapshot, plus any records the snapshot consolidates. |

Returns `Snapshot created with ID: <id>`.

### update_memory

Change fields of an existing record in place. Kind, namespace, id and file name never change.

| Parameter | Type | Required | Notes |
|---|---|---|---|
| `id` | string | yes | |
| `expected_revision` | integer, at least 1 | no | If the record's revision differs, nothing is written and the reply is a conflict message naming the current revision. |
| `title` | string | no | |
| `content` | string | no | Replaces the whole body text; the generated Related block is kept. |
| `tags` | list of strings | no | Replaces all tags. |
| `status` | string | no | Validated against the record's kind, as in `save_memory`. |
| `review_by` | `YYYY-MM-DD` | no | Risks only. |
| `visibility` | `public`, `internal`, `private` | no | |
| `validity` | `valid`, `rejected` | no | `rejected` needs `rejected_reason`. |
| `rejected_reason` | string | no | Allowed only when the resulting validity is `rejected`. |
| `supersedes` | list of record ids | no | Added to the record's `supersedes` list and Related block; the targets are closed as in `save_memory`. A record cannot supersede itself. |

At least one field to change is required. Other arguments are refused. Receipts cannot be updated.
Returns `Memory updated. ID: <id>. Revision: <n>`, `Memory not found.`, or
`Revision conflict: expected revision <a> but the current revision is <b>. Read the record again before updating.`

## Read

### get_project_brief

`**Project brief for <namespace>**`, then each part that exists, in this order:

1. `## Last session` and `## Threads`: the companion cards, while the feature is on.
2. `## Snapshot: <title> (<YYYY-MM-DD>, id <id8>)`: the latest snapshot that is not superseded,
   private or rejected, with its content.
3. `## Since the snapshot` (or `## Active records` without a snapshot): active records created after
   that snapshot, newest first, as `- [<kind>: <status>] <title> - id <id8>` (`- [<kind>]` when the
   record has no status). Active means not superseded, not `superseded` or `resolved`, not private
   and not rejected.
4. `Consolidation due: latest snapshot is <n> days old` when the snapshot is older than seven days,
   or `Consolidation due: no snapshot yet and <n> active records`.

An empty namespace reads `No saved memory found for namespace: <namespace>`.

| Parameter | Type | Required | Notes |
|---|---|---|---|
| `namespace` | string | no | |
| `limit` | number | no | Active records to list, default 10; the rest are counted as `- ... and <n> more`. |

### search_memory

Free-text search plus filters. Text is lowercased and stemmed, so `caching` finds `cache` and
`cached`. A record matches when every query stem appears in its title, content or tags. Title hits
count three times as much as content hits; ties go to the newest record.

| Parameter | Type | Required | Notes |
|---|---|---|---|
| `namespace` | string | no | |
| `query` | string | no | Without it the filters alone apply. |
| `agent` | string | no | Agent that wrote the record. |
| `tags` | list of strings | no | |
| `kind` | enum | no | One of the active kinds. |
| `limit` | number | no | |
| `include_private` | boolean | no | Default false. |

Returns numbered lines or `No matching memory found.`

### list_contexts

Recent records, newest first. Parameters: `namespace`, `agent`, `tags`, `kind`, `limit`,
`include_private`, as in `search_memory`. Returns `No saved context yet.` when empty.

### read_latest_context

The most recent record of any kind, optionally by agent.

| Parameter | Type | Required |
|---|---|---|
| `namespace` | string | no |
| `agent` | string | no |
| `include_private` | boolean | no |

Returns `**<title>** - <agent> - <timestamp> - id <id8>` followed by the content, or `No context found.`

### get_links

Outgoing links and backlinks of a record, resolved the way Obsidian resolves them.

| Parameter | Type | Required |
|---|---|---|
| `id` | string | yes |

Returns the lists, with unresolved targets called out, or `Memory not found.`

## Health

### list_issues

No parameters. Lists vault files that look like records but cannot be used, with the reason: invalid
YAML, a missing `id`, `kind` or `namespace`, an unknown kind, a kind that does not match its folder,
or a duplicate id. The files are never modified. Returns `No issues found.` when clean.

## Optional tools

### write_receipt (feature `receipts`)

| Parameter | Type | Required | Notes |
|---|---|---|---|
| `agent` | string | yes | |
| `title` | string | yes | |
| `summary` | string | yes | What was done. |
| `refs` | list of strings, max 50, each max 500 | yes | File paths or commit SHAs. |
| `namespace` | string | no | |
| `harness` | string, max 100 | no | For example `claude-code`. |
| `session` | string, max 500 | no | |

Returns `Receipt saved with ID: <id>`. Receipts are immutable.

### get_companion (feature `companion`, on by default)

Parameter: `namespace`. Returns the last-session and threads cards of the namespace, or
`No companion cards yet.`

### update_companion (feature `companion`, on by default)

| Parameter | Type | Required | Notes |
|---|---|---|---|
| `namespace` | string | no | |
| `last_session` | string | no | What this session did, what is still unverified, and the next step. |
| `threads` | string | no | One line per open work thread, `- <branch or topic>: <status>; next: <step>`. Drop a thread's line when it is done; an empty string means no open thread. Any other line shape is refused. |

At least one card is required. Each card is capped at `companion.max_chars` (default 3000) after
redaction; if any card is over the cap, nothing is written and the error asks the agent to compact
the text. Returns `Companion updated.`
