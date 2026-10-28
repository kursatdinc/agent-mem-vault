# Tools Reference

Nineteen tools: sixteen always on, and three behind feature flags. The first 13 keep the names,
parameters and reply texts of [shared-memory-mcp](https://github.com/gamazyn/shared-memory-mcp). Memory content is written in
English; every tool description says so.

Conventions:

- `namespace` is optional everywhere. It defaults to `default_namespace` from the
  [configuration](https://github.com/kursatdinc/agent-mem-vault/wiki/Configuration), usually set per call to `project/<repo>`. Max 100 characters.
- `tags` is a list of up to 20 tags of at most 64 characters. In filters, a record must carry all
  the tags given.
- `limit` is a number; the default is 10.
- `include_private` only has an effect while `features.visibility` is on.
- Expected failures (invalid input, a vault problem) come back as tool errors whose text says what to
  fix. Not finding a record is a normal reply, such as `Memory not found.`
- Redaction is applied to content before it is written, when `redact_secrets` is on.

Kinds: `note`, `decision`, `assumption`, `task`, `risk`, `handoff`, `snapshot`, and `receipt` when
the feature is on. Listings use `type`: `handoff` for kind `handoff`, `context` for everything else.

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
| `kind` | enum | yes | `note`, `decision`, `assumption`, `task`, `risk`, `snapshot`. `handoff` is refused (use `create_handoff`); `receipt` is created only by `write_receipt`. |
| `title` | string | yes | |
| `content` | string | yes | |
| `namespace` | string | no | |
| `status` | string, max 100 | no | Free text, for example `open`, `accepted`, `done`. |
| `relatedFiles` | list of strings, each max 500 | no | |
| `branch` | string, max 500 | no | |
| `commit` | string, max 500 | no | |
| `nextAction` | string, max 200 | no | |
| `tags` | list of strings | no | |
| `supersedes` | list of record ids | no | Records of the same namespace that this one replaces. Each is marked `superseded_by`. Already-superseded records and receipts are refused. |

Returns `Memory saved with ID: <id>`.

### create_snapshot

Save a durable summary of a namespace (kind `snapshot`, tag `snapshot`). The latest snapshot is what
`get_project_brief` returns.

| Parameter | Type | Required |
|---|---|---|
| `agent`, `title`, `content` | string | yes |
| `namespace` | string | no |

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
| `status` | string | no | |
| `visibility` | `public`, `internal`, `private` | no | |
| `validity` | `valid`, `rejected` | no | `rejected` needs `rejected_reason`. |
| `rejected_reason` | string | no | Allowed only when the resulting validity is `rejected`. |

At least one field to change is required. Other arguments are refused. Receipts cannot be updated.
Returns `Memory updated. ID: <id>. Revision: <n>`, `Memory not found.`, or
`Revision conflict: expected revision <a> but the current revision is <b>. Read the record again before updating.`

## Handoffs

A handoff is a record of kind `handoff`, titled `Handoff to <to>`, with `to` and `read` fields.
See [Multi-Agent Handoffs](https://github.com/kursatdinc/agent-mem-vault/wiki/Multi-Agent-Handoffs) for the lifecycle.

### create_handoff

| Parameter | Type | Required | Notes |
|---|---|---|---|
| `to` | string | yes | Destination agent. |
| `summary` | string, max 200 | yes | |
| `context` | string | yes | Full context needed to continue. |
| `namespace` | string | no | |
| `supersedes` | list of handoff ids | no | Those handoffs become read and get `superseded_by`. Only handoffs of the same namespace. |

The body is `## Summary` and `## Full Context`. Returns `Handoff created for <to>. ID: <id>`.

### read_handoff

Read the newest pending handoff for an agent and mark it read.

| Parameter | Type | Required |
|---|---|---|
| `agent` | string | yes |
| `namespace` | string | no |

Returns the handoff text, or `No pending handoff.`

### peek_handoff

Same as `read_handoff` without marking it read. Parameters: `agent` (required), `namespace`.

### ack_handoff

Mark a handoff read by id. Parameters: `id` (required), `namespace`. Returns
`Handoff marked as read. ID: <id>` or `Handoff not found.`

### reopen_handoff

Mark a read handoff pending again. Parameters: `id` (required), `namespace`. Returns
`Handoff reopened. ID: <id>` or `Handoff not found.`

### list_handoffs

| Parameter | Type | Required | Notes |
|---|---|---|---|
| `namespace` | string | no | |
| `agent` | string | no | Destination agent filter. |
| `status` | `all`, `pending`, `read` | no | Default `all`. |
| `limit` | number | no | |

Returns one line per handoff, newest first, or `No handoffs found.`

## Read

### get_project_brief

The latest non-private, non-rejected snapshot of the namespace. If there is none, a generated brief
of the most recent records, one line each (`[kind] title (agent): content`). With the companion
feature on, the last-session card is appended.

| Parameter | Type | Required | Notes |
|---|---|---|---|
| `namespace` | string | no | |
| `limit` | number | no | Recent items when there is no snapshot; default 10. |

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
| `type` | `context`, `handoff` | no | |
| `kind` | enum | no | One of the active kinds. |
| `handoffStatus` | `all`, `pending`, `read` | no | |
| `limit` | number | no | |
| `include_private` | boolean | no | Default false. |

Returns numbered lines or `No matching memory found.`

### list_contexts

Recent records, newest first. Parameters: `namespace`, `agent`, `tags`, `type`, `kind`, `limit`,
`include_private`, as in `search_memory`. Returns `No saved context yet.` when empty.

### read_latest_context

The most recent `context` record (any kind except handoff), optionally by agent.

| Parameter | Type | Required |
|---|---|---|
| `namespace` | string | no |
| `agent` | string | no |
| `include_private` | boolean | no |

Returns `**<title>** - <agent> - <timestamp>` followed by the content, or `No context found.`

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

### get_companion (feature `companion`)

Parameter: `namespace`. Returns the last-session and threads cards of the namespace.

### update_companion (feature `companion`)

| Parameter | Type | Required | Notes |
|---|---|---|---|
| `namespace` | string | no | |
| `last_session` | string | no | New card text: what the last session did and left open. |
| `threads` | string | no | New card text: open threads to pick up. |

At least one card is required. Each card is capped at `companion.max_chars` (default 3000) after
redaction; if any card is over the cap, nothing is written and the error asks the agent to compact
the text. Returns `Companion updated.`
