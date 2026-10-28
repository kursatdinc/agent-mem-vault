# Obsidian Integration

The vault is the memory. Obsidian is how you look at it, and the server works the same whether
Obsidian is open or not. The server never launches Obsidian and never writes `.obsidian/`.

## Open a vault

Use any folder as a vault: *Open folder as vault*, or create a new one. The demo vault in
[examples/demo-vault](https://github.com/kursatdinc/agent-mem-vault/tree/main/examples/demo-vault) is ready to open.

## Graph and backlinks

Records link to each other through wikilinks in their frontmatter and in a generated *Related* block:

- A decision that supersedes another links to it, and the older one links forward with
  `superseded_by`. In the graph view a supersedes chain is a visible path.
- Each project has a generated hub note, `<namespace-slug>/<namespace-slug>.md`, linking every record of
  the project. It is named after its folder, so the graph labels it with the project name, and a
  project shows up as a cluster around its hub.
- The backlinks pane of a record shows what replaced it and what refers to it. The `get_links` tool
  returns the same information to an agent.

### Graph tips

The graph's *Filters* and *Groups* take Obsidian search terms (the
[Graph view help](https://obsidian.md/help/plugins/graph) points to the
[Search help](https://obsidian.md/help/plugins/search) for the syntax), so these work:

- **One color per project**: add a group per project with the query `path:project-harbor-api`, and
  another with `path:project-lantern-mobile`, and give each its own color.
- **Color by kind**: groups with property searches such as `[kind:decision]`, `[kind:risk]` and
  `[kind:handoff]`.
- **Focus on one project**: put `path:project-harbor-api` in the *Search files* filter.
- **Spot rejected ideas**: a group with `[validity:rejected]`.

## The Bases dashboard

`_dashboards/memory.base` is created the first time the server writes. It is an
[Obsidian Bases](https://help.obsidian.md/bases) file with three table views over the records the
server wrote (`agent-written` is true):

| View | Shows |
|---|---|
| Pending handoffs | handoffs with `read` false: name, destination, namespace, created |
| Decisions and risks | valid decisions and risks, grouped by namespace, with kind and status |
| All records | every record except generated notes |

The file is created only if absent. Edit it freely: add views, change filters. The server will not
overwrite it. Opening a `.base` file needs a version of Obsidian that includes the Bases core plugin.

## Hand edits

Edit a record like any note. Common things to do:

- **Reject a decision**: set `validity: rejected` and add `rejected_reason: ...`. It stops steering
  agents (it leaves the brief) and stays on file, and listings mark it `[rejected]`.
- **Keep a record out of automatic context**: set `visibility: private`.
- **Fix a wrong fact**: rewrite the text. Leave `id`, `kind` and `namespace` alone.
- **Close a risk**: change `status`.

What is safe:

- Edits are picked up on the next query; there is no index to rebuild.
- When an agent updates a record you changed, the server re-reads it under a lock and checks the
  `revision`. If you edited it during the write it retries once, then reports a conflict and leaves
  your version in place. The agent is told to read the record again.
- The server only rewrites the text between the `avm:related` markers in the body. Keep those two
  comment lines if you want the generated links to keep updating.
- Do not edit generated hub notes: they are rewritten on the next write.

If a note stops parsing (for example broken YAML), it is reported by `list_issues` and `doctor` with
the reason, and never modified.

## doctor and the Obsidian CLI

`agent-mem-vault doctor` reports the config, the vault path, whether `.obsidian/` is present,
record counts by kind, issues, temporary files left by an interrupted write, and the vault's git
state.

It also counts unresolved links in the memory folders itself. If Obsidian is running
(detected with `pgrep -x Obsidian`) and the `obsidian` command line tool is installed, `doctor` runs
`obsidian unresolved verbose format=json` in the vault directory and compares Obsidian's unresolved
link count for the memory folders with its own, printing any differences. This catches a link that
Obsidian and the server resolve differently.

- If the tool is missing or Obsidian is not running, the check is skipped with a note.
- If the CLI prints something unexpected, `doctor` prints "output not understood" and carries on.
- `doctor` never launches Obsidian.

## Git

Put the vault in a git repository for a full history of what your agents decided. With
`features.git_autocommit` the server commits every change (`avm: <operation> <kind> <id8>`) and never
pushes. Without it, the vault is an ordinary working tree you can commit by hand. The server's private
folder `.agent-mem-vault/` is git-ignored automatically when the server creates it.
