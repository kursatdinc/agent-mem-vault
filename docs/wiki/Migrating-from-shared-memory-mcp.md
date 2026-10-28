# Migrating from shared-memory-mcp

agent-mem-vault keeps the names, parameters and reply texts of the first 13 tools of
[shared-memory-mcp](https://github.com/gamazyn/shared-memory-mcp), so agent instructions that call
`save_memory`, `create_handoff`, `read_handoff` and the rest keep working without changes. What
changes is where the memory lives: one Markdown note per record in an Obsidian vault instead of one
JSON file.

## Steps

1. Create or choose the vault and configure the server, as in
   [Getting Started](https://github.com/kursatdinc/agent-mem-vault/wiki/Getting-Started).
2. Import the old store:

   ```sh
   agent-mem-vault import ~/.shared-memory-mcp/contexts.json
   ```

   Run it with `AGENT_MEM_VAULT_VAULT` set, or with the vault in your config file.
3. Run `agent-mem-vault doctor` and open the vault in Obsidian to look at the result.
4. Replace the old MCP server entry in your clients with the new one.

## What the import does

- Keeps record ids and timestamps. `created` and `updated` come from the old `timestamp`; for a read
  handoff `updated` is its `readAt`.
- An entry without a `type` or `kind` becomes a `note`.
- Writes the oldest entries first and sets each file's modification time to the old timestamp, so
  records from the same second keep their original newest-first order.
- A handoff whose summary starts with `Supersedes <id8>` marks the pending handoff with that id
  prefix (same namespace) as read, with `superseded_by`. If the prefix matches more than one pending
  handoff nothing is marked and the import reports an error; no match is silent.
- Is idempotent: ids already in the vault are skipped, so you can run it again.
- Never modifies the source file.
- Reports `imported`, `skipped`, `superseded-marked` and `errors`. An entry that cannot be converted
  (unknown kind, missing title, bad timestamp) is counted and listed; the rest still import.

## Renaming namespaces

`--namespace-map OLD=NEW` imports records of namespace `OLD` into `NEW`, and can be repeated. It also
applies to the default namespace name:

```sh
agent-mem-vault import contexts.json --namespace-map default=project/my-repo
```

## What is different afterwards

| | shared-memory-mcp | agent-mem-vault |
|---|---|---|
| Storage | One JSON file | One Markdown note per record in a vault |
| Extra tools | | `update_memory`, `get_links`, `list_issues`, plus optional receipt and companion tools |
| Supersede | Convention in handoff text | `supersedes` parameter and `superseded_by` links |
| Editing by hand | Edit the JSON | Edit the note in Obsidian; revisions protect against overwrites |
| Search | Text and filters | Stemmed text and the same filters |

Memory content is written in English by convention in both. Unlike the old store, the memory is
also readable as a graph and a dashboard; see
[Obsidian Integration](https://github.com/kursatdinc/agent-mem-vault/wiki/Obsidian-Integration).
