# Record Format

Every record is one Markdown file with YAML frontmatter. The frontmatter is what the server queries
and what Obsidian shows as properties.

## Where files live

```
<vault>/
  <namespace-slug>/
    <namespace-slug>.md             generated hub note
    _companion/                     companion cards (feature companion)
    <kind>/<YYYY-MM-DD>-<title-slug>-<id8>.md
  _dashboards/memory.base           generated dashboard
  .agent-mem-vault/              server-private: lock file and tmp/ for atomic writes
```

- `namespace-slug`: the namespace lowercased, every run of characters outside `a-z0-9` replaced by
  `-`. `project/harbor-api` becomes `project-harbor-api`. The `namespace` in the frontmatter is
  authoritative; the folder name is cosmetic.
- `title-slug`: the title slugged the same way, cut to 48 characters. `id8` is the first eight hex
  characters of the id.
- The file name is fixed when the record is created. Editing a title never renames the file.
- A file counts as a record only if it sits at `<namespace-slug>/<kind>/*.md` with a known kind.
  Everything else in the vault (your own notes, hubs, dashboards, companion cards) is ignored by the
  record queries.
- `.agent-mem-vault/` is added to the vault's `.gitignore` when the server creates it inside a git
  repository.

## An example

```markdown
---
id: 234bc139-823f-5c1c-b7bb-d37ea1c3ee3c
kind: decision
namespace: project/harbor-api
agent: claude-code
title: Move order storage to PostgreSQL
created: 2026-03-06T09:01:00Z
updated: 2026-03-08T09:02:00Z
revision: 2
visibility: internal
validity: valid
tags: [storage]
status: accepted
supersedes: ['[[project-harbor-api/decision/2026-03-02-use-sqlite-for-the-first-release-d61740a1]]']
superseded_by: '[[project-harbor-api/decision/2026-03-08-pin-postgresql-16-in-ci-and-production-eb0b3836]]'
agent-written: true
---
The pilot grew to three workers, which SQLite cannot serve safely. PostgreSQL gives concurrent writers and point-in-time recovery.

<!-- avm:related:start -->
## Related
- Supersedes [[project-harbor-api/decision/2026-03-02-use-sqlite-for-the-first-release-d61740a1|Use SQLite for the first release]]
- Superseded by [[project-harbor-api/decision/2026-03-08-pin-postgresql-16-in-ci-and-production-eb0b3836|Pin PostgreSQL 16 in CI and production]]
<!-- avm:related:end -->
```

## Frontmatter fields

| Field | Meaning |
|---|---|
| `id` | UUID string, never changes. |
| `kind` | `note`, `decision`, `assumption`, `task`, `risk`, `handoff`, `snapshot`, or `receipt` (feature). Must match the folder. |
| `namespace` | For example `project/harbor-api`. |
| `agent` | Who wrote it. Handoffs use `handoff` here and carry the destination in `to`. |
| `title` | Shown in listings and the graph. |
| `created`, `updated` | UTC ISO 8601 with `Z`. |
| `revision` | Starts at 1 and increases with every change. Used for conflict checks. |
| `visibility` | `public`, `internal` (default) or `private`. |
| `validity` | `valid` (default) or `rejected`. |
| `tags` | List of strings. |
| `status` | Optional free text, for example `open` or `accepted`. |
| `related_files`, `branch`, `commit`, `next_action` | Optional workflow metadata. |
| `supersedes`, `superseded_by` | Wikilinks to the records this one replaces, and the record that replaced it. |
| `to`, `read`, `read_at` | Handoffs only: destination, whether it was read, and when. |
| `rejected_reason` | Rejected records only. |
| `refs`, `harness`, `session` | Receipts only. |
| `agent-written` | `true` for records the server wrote. The dashboard filters on it. |

Only keys that have a value are written. A key has one type across the whole vault.

## Links

Links in frontmatter and in the generated Related block are full vault-relative paths without
`.md`, so they resolve the same way in Obsidian. The server rewrites only the text between the
`avm:related` markers. Everything above and below them is yours.

Link resolution follows Obsidian's rules: an exact vault-relative path, otherwise a base name match
with the shortest path winning, otherwise frontmatter `aliases`. `#heading`, `|display` and a
leading `!` are ignored.

## Handoff body

```markdown
## Summary
<summary>

## Full Context
<context>
```

The title is `Handoff to <to>`.

## Generated files

- `<namespace-slug>/<namespace-slug>.md`: a hub note named after its folder, so Obsidian's graph labels it
  with the project name. It links every record of the namespace, grouped by kind, newest first. It carries `generated: true`, is rewritten on each write, and is never written over a
  file that does not carry that marker.
- `_dashboards/memory.base`: created once if absent, then left to you.

## Hand edits

You may edit any record in Obsidian: change the title, status or tags, rewrite the content, mark a
decision rejected. The next query reads the new text. If an agent updates the record at the same
moment, the update retries once and then reports a conflict instead of overwriting your change. See
[Obsidian Integration](https://github.com/kursatdinc/agent-mem-vault/wiki/Obsidian-Integration).

A file with broken frontmatter is not lost: it shows up in `list_issues` and `doctor` with the reason
and stays exactly as you left it.
